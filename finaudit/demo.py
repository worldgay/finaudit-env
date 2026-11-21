"""`make demo`: a terminal walk-through on an I1 episode (no private data used by the auditor)."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from finaudit.env.core import FinAuditEnv
from finaudit.generator.episode_io import read_files
from finaudit.generator.generate import generate_to_dir, load_config
from finaudit.generator.transform import transform
from finaudit.runner import POLICIES, ROOT, run_episode_train
from finaudit.util.canon import dumps, sha256_text
from finaudit.util.money import round_half_even
from finaudit.util.timeutil import parse_ts, zone

SEED = 4242
NO_OTHER_ERRORS = {t: {"count": 0} for t in ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION",
                                              "PERIOD_CUTOFF")}


def say(text: str = "") -> None:
    """Print one line."""
    sys.stdout.write(text + "\n")


class Walk:
    """Executes actions on the env and prints them."""

    def __init__(self, env: FinAuditEnv) -> None:
        self.env = env

    def __call__(self, action: dict) -> dict:
        obs, reward, term, trunc, info = self.env.step(action)
        shown = {k: v for k, v in action.items() if k != "findings"}
        if "findings" in action:
            shown["findings"] = f"<{len(action['findings']['findings'])} findings>"
        res = dumps(obs["result"] if obs["ok"] else obs["error"])
        say(f"  step {self.env.steps_used:3d} > {dumps(shown)}")
        say(f"           < {res[:150]}{'…' if len(res) > 150 else ''}")
        if term or trunc:
            say(f"           reward={reward:+.3f} info={dumps(info)}")
        return obs


def _all(walk: Walk, table: str) -> list[dict]:
    rows, cursor = [], None
    while True:
        obs = walk({"action": "list_records", "table": table, "cursor": cursor, "limit": 50})
        rows += obs["result"]["records"]
        cursor = obs["result"]["next_cursor"]
        if cursor is None:
            return rows


def scripted_audit(ep_dir: Path) -> None:
    """Find a late-evening foreign payment on the last day and check its FX and allocation."""
    env = FinAuditEnv()
    obs, _ = env.reset(0, {"episode_dir": str(ep_dir), "mode": "train"})
    m = obs["result"]["manifest"]
    say(f"Company {m['company_name']}, base {m['base_currency']}, tz {m['timezone']}, "
        f"period {m['period_start']}..{m['period_end']}, counts {m['counts']}")
    walk = Walk(env)
    pays = _all(walk, "payments")
    tz = zone(m["timezone"])
    late = [p for p in pays if p["currency"] != m["base_currency"] and
            parse_ts(p["timestamp"]).astimezone(tz).date().isoformat() == m["period_end"]
            and parse_ts(p["timestamp"]).astimezone(tz).hour >= 21]
    pay = walk({"action": "get_document", "doc_id": late[0]["doc_id"]})["result"]["document"]
    local_day = parse_ts(pay["timestamp"]).astimezone(tz).date().isoformat()
    say(f"  -> payment {pay['payment_id']} at {pay['timestamp']} is {local_day} local time")
    invs = {i["invoice_id"]: i for i in _all(walk, "invoices")}
    inv = invs[pay["invoice_refs"][0]["invoice_id"]]
    rows = [r for r in _all(walk, "ledger") if r["payment_id"] == pay["payment_id"]]
    exps = m["currency_exponents"]
    es, eb = exps[pay["currency"]], exps[m["base_currency"]]
    pay_rate = walk({"action": "get_record", "table": "fx",
                     "id": f"fx:{local_day}:{pay['currency']}:{m['base_currency']}"})["result"]["record"]
    raw = walk({"action": "calculator",
                "expression": f"{abs(pay['amount_minor'])} / {10 ** es} * {pay_rate['rate']} * {10 ** eb}"})
    want_bank = round_half_even(Decimal(raw["result"]["value"]))
    bank = next(r for r in rows if r["account"] == "BANK")
    inv_day = parse_ts(inv["issued_at"]).astimezone(tz).date().isoformat()
    inv_rate = walk({"action": "get_record", "table": "fx",
                     "id": f"fx:{inv_day}:{pay['currency']}:{m['base_currency']}"})["result"]["record"]["rate"]
    ar = sum(r["credit_minor"] - r["debit_minor"] for r in rows
             if r["account"] == "AR" and r["invoice_id"] == inv["invoice_id"])
    alloc = walk({"action": "calculator", "expression": f"{ar} / {inv_rate} / {10 ** (eb - es)}"})
    allocated = round_half_even(Decimal(alloc["result"]["value"]))
    gap = pay["invoice_refs"][0]["amount_minor"] - allocated
    say(f"  -> BANK booked {bank['debit_minor'] + bank['credit_minor']} vs policy {want_bank}; "
        f"unallocated {gap} {pay['currency']} minor units")
    findings = [
        {"type": "FX_CONVERSION", "affected_ids": [pay["payment_id"]],
         "claimed_amount_minor": abs(bank["debit_minor"] + bank["credit_minor"] - want_bank),
         "currency": m["base_currency"], "evidence_ids": [pay["doc_id"], pay_rate["fx_id"], bank["row_id"]],
         "explanation": "BANK line converted at a rate of another date"},
        {"type": "PAYMENT_ALLOCATION", "affected_ids": [inv["invoice_id"], pay["payment_id"]],
         "claimed_amount_minor": gap, "currency": pay["currency"],
         "evidence_ids": [pay["doc_id"], inv["doc_id"], f"fx:{inv_day}:{pay['currency']}:{m['base_currency']}"]
         + [r["row_id"] for r in rows],
         "explanation": "part of the payment parked on SUSPENSE"}]
    walk({"action": "submit", "findings": {"episode_id": m["episode_id"], "findings": findings}})


def main() -> int:
    """Run the demo."""
    tmp = Path(tempfile.mkdtemp(prefix="demo-"))
    cfg = {**load_config(ROOT / "configs" / "i1.json"), "errors": NO_OTHER_ERRORS}
    ep = generate_to_dir(SEED, cfg, tmp)
    say("== 1. Scripted auditor on an I1 episode (FX + partial allocation at the period boundary) ==")
    scripted_audit(ep)
    say("\n== 2. The four baseline policies on the same episode (train mode) ==")
    for k, name in enumerate(POLICIES):
        r = run_episode_train(ep, name, policy_seed=k)
        say(f"  {name:15s} reward={r['reward']:+.3f} F1={r['f1']:.3f} P={r['precision']:.3f} "
            f"R={r['recall']:.3f} steps={r['steps']}")
    say("\n== 3. Attacks (see REPORT.md for the 20-episode numbers) ==")
    from finaudit.attacks import measure_attacks
    for key, val in measure_attacks([ep]).items():
        say(f"  {key:32s} {val:+.4f}")
    say("\n== 4. Shuffle + rename every id; replay the same seed ==")
    moved = transform(ep, 1, tmp / "t")
    a, b = run_episode_train(ep, "oracle"), run_episode_train(moved, "oracle")
    say(f"  oracle reward original={a['reward']} transformed={b['reward']} ({ep.name} -> {moved.name})")
    again = generate_to_dir(SEED, cfg, tmp / "replay")
    same = sha256_text(dumps(read_files(again))) == sha256_text(dumps(read_files(ep)))
    say(f"  same seed -> identical sha256 of all files: {same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
