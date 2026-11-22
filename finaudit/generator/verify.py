"""verify_episode(): структурные проверки + reference_audit(public) == truth + достаточность доказательств."""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from finaudit.generator.episode_io import parse_public, public_ids, read_files
from finaudit.generator.reference_audit import reference_audit
from finaudit.generator.revert import pre_error_problems
from finaudit.util.canon import dumps, sha256_text
from finaudit.util.leak import scan_text
from finaudit.util.timeutil import parse_date, parse_ts

SIZE = {"ledger": (200, 2000), "documents": (20, 200), "issues": (0, 12)}
ID_PATTERNS = {"row_id": r"^L-[0-9A-Z]{6}$", "doc_id": r"^D-[0-9A-Z]{6}$",
               "invoice_id": r"^INV-[0-9A-Z]{6}$", "payment_id": r"^PAY-[0-9A-Z]{6}$",
               "entity_id": r"^E-[0-9A-Z]{4}$"}
MAX_EVIDENCE_UNION = 98


def _ids_ok(record: dict, keys: tuple[str, ...]) -> bool:
    return all(record.get(k) is None or re.match(ID_PATTERNS[k], record[k]) for k in keys)


def _structure(pub: dict) -> list[str]:
    bad: list[str] = []
    m, led = pub["manifest"], pub["ledger"]
    inv_ids = {i["invoice_id"] for i in pub["invoices"]}
    pay_ids = {p["payment_id"] for p in pub["payments"]}
    for r in led:
        if not ((r["debit_minor"] > 0) ^ (r["credit_minor"] > 0)) or min(r["debit_minor"], r["credit_minor"]) < 0:
            bad.append(f"one-sided {r['row_id']}")
        if r["currency"] != m["base_currency"] or not _ids_ok(r, ("row_id", "entity_id", "invoice_id", "payment_id")):
            bad.append(f"row fields {r['row_id']}")
        if (r["invoice_id"] and r["invoice_id"] not in inv_ids) or (r["payment_id"] and r["payment_id"] not in pay_ids):
            bad.append(f"dangling ref {r['row_id']}")
        parse_ts(r["timestamp"])
    if sum(r["debit_minor"] for r in led) != sum(r["credit_minor"] for r in led):
        bad.append("ledger unbalanced")
    for inv in pub["invoices"]:
        parse_ts(inv["issued_at"])
        if sum(li["amount_minor"] for li in inv["line_items"]) != inv["total_minor"] or \
                not _ids_ok(inv, ("doc_id", "invoice_id", "entity_id")):
            bad.append(f"invoice {inv['invoice_id']}")
    for pay in pub["payments"]:
        parse_ts(pay["timestamp"])
        if sum(r["amount_minor"] for r in pay["invoice_refs"]) != pay["amount_minor"] or \
                not _ids_ok(pay, ("doc_id", "payment_id", "entity_id")):
            bad.append(f"payment {pay['payment_id']}")
    bad.extend(_counts_and_fx(pub))
    return bad


def _counts_and_fx(pub: dict) -> list[str]:
    bad: list[str] = []
    m = pub["manifest"]
    n_docs = len(pub["invoices"]) + len(pub["payments"])
    counts = {"ledger": len(pub["ledger"]), "invoices": len(pub["invoices"]),
              "payments": len(pub["payments"]), "fx": len(pub["fx"]), "documents": n_docs}
    if counts != m["counts"]:
        bad.append("manifest counts")
    for key in ("ledger", "documents"):
        lo, hi = SIZE[key]
        if not lo <= counts[key] <= hi:
            bad.append(f"size {key}={counts[key]}")
    have = {(r["date"], r["source_currency"]) for r in pub["fx"]}
    start, end = parse_date(m["period_start"]), parse_date(m["period_end"])
    used = {d["currency"] for d in pub["invoices"] + pub["payments"]} - {m["base_currency"]}
    day = start - timedelta(days=7)
    while day <= end + timedelta(days=7):
        bad.extend(f"fx missing {day} {c}" for c in sorted(used) if (day.isoformat(), c) not in have)
        day += timedelta(days=1)
    return bad


def _key(item: dict) -> str:
    return dumps([item["type"], sorted(item["affected_ids"]), item["expected_amount_minor"],
                  item["currency"], sorted(sorted(e) for e in item["evidence_sets"])])


def _truth_vs_audit(pub: dict, truth: dict) -> list[str]:
    found = sorted(_key(f) for f in reference_audit(pub))
    want = sorted(_key(i) for i in truth["issues"])
    if found == want:
        return []
    extra = sorted(set(found) - set(want))
    missing = sorted(set(want) - set(found))
    return [f"audit != truth: extra={extra[:3]} missing={missing[:3]}"]


def _evidence(pub: dict, truth: dict) -> list[str]:
    bad: list[str] = []
    ids = public_ids(pub)
    union: set[str] = set()
    if not SIZE["issues"][0] <= len(truth["issues"]) <= SIZE["issues"][1]:
        bad.append("issue count")
    if truth["episode_id"] != pub["manifest"]["episode_id"]:
        bad.append("episode id mismatch")
    for issue in truth["issues"]:
        if not issue["evidence_sets"]:
            bad.append(f"no evidence {issue['issue_id']}")
            continue
        for ev in issue["evidence_sets"]:
            if len(ev) > 10 or any(e not in ids for e in ev):
                bad.append(f"evidence {issue['issue_id']}")
        union.update(issue["evidence_sets"][0])
    if len(union) > MAX_EVIDENCE_UNION:
        bad.append("evidence union too large")
    return bad


def _leaks(files: dict[str, str], truth: dict) -> list[str]:
    extra = tuple(i["issue_id"] for i in truth["issues"])
    bad = []
    for name, text in files.items():
        if name.startswith("public/") and name != "public/policy.json":
            hits = scan_text(text, extra)
            if hits:
                bad.append(f"leak {name}: {hits[:3]}")
    return bad


def verify_files(files: dict[str, str]) -> list[str]:
    """Возвращает список проблем эпизода в памяти (пусто = валиден)."""
    pub = parse_public(files)
    truth = json.loads(files["private/truth.json"])
    problems = _structure(pub) + _truth_vs_audit(pub, truth) + _evidence(pub, truth) + _leaks(files, truth)
    prov_text = files.get("private/provenance.json")
    if prov_text:
        provenance = json.loads(prov_text)
        if truth["issues"] and not provenance.get("injections"):
            problems.append("provenance has no change log")
        problems += pre_error_problems(pub, provenance)
    gen_text = files.get("private/generation.json")
    if gen_text:
        sha = json.loads(gen_text).get("public_sha256", {})
        for name, digest in sha.items():
            if sha256_text(files[f"public/{name}"]) != digest:
                problems.append(f"sha mismatch {name}")
    return problems


def verify_episode(episode_dir: str | Path) -> list[str]:
    """Проверяет каталог эпизода на диске."""
    return verify_files(read_files(episode_dir))


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m finaudit.generator.verify EPISODE_DIR [...]  (код выхода 1 при любой проблеме)."""
    import sys
    dirs = argv if argv is not None else sys.argv[1:]
    status = 0
    for d in dirs:
        problems = verify_episode(d)
        sys.stdout.write(f"{d}: {'OK' if not problems else problems}\n")
        status |= bool(problems)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
