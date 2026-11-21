"""Clean double-entry books derived from the hidden history (policy.json rules)."""
from __future__ import annotations

import random

from finaudit.generator.world import World, random_moment, random_total_major, stamp
from finaudit.util.ids import IdFactory
from finaudit.util.money import convert
from finaudit.util.timeutil import in_period, local_date

ACCOUNTS = ("AR", "AP", "REVENUE", "EXPENSE", "BANK", "SUSPENSE", "FX_GAIN_LOSS")


def new_row(ids: IdFactory, ts: str, account: str, amount: int, side: str, base: str,
            entity_id: str | None, invoice_id: str | None, payment_id: str | None) -> dict:
    """Create one ledger row; ``side`` is 'dr' or 'cr', ``amount`` > 0."""
    return {"row_id": ids.new("L"), "timestamp": ts, "account": account,
            "debit_minor": amount if side == "dr" else 0,
            "credit_minor": amount if side == "cr" else 0, "currency": base,
            "entity_id": entity_id, "invoice_id": invoice_id, "payment_id": payment_id}


def to_base(w: World, amount: int, currency: str, day) -> int:
    """Policy conversion of ``amount`` (minor, currency) to base minor units on ``day``."""
    return convert(amount, w.exp(currency), w.rate(currency, day), w.exp(w.base))


def invoice_rows(w: World, rng: random.Random, ids: IdFactory, inv: dict,
                 ts: str | None = None) -> list[dict]:
    """Principal (AR/AP) and counterpart (REVENUE/EXPENSE) rows of an invoice."""
    day = w.meta[inv["invoice_id"]]["moment"].date()
    amt = to_base(w, inv["total_minor"], inv["currency"], day)
    ts = ts or stamp(rng, w.meta[inv["invoice_id"]]["moment"])
    args = (w.base, inv["entity_id"], inv["invoice_id"], None)
    if inv["direction"] == "receivable":
        return [new_row(ids, ts, "AR", amt, "dr", *args), new_row(ids, ts, "REVENUE", amt, "cr", *args)]
    return [new_row(ids, ts, "EXPENSE", amt, "dr", *args), new_row(ids, ts, "AP", amt, "cr", *args)]


def plug_amount(group: list[dict]) -> int:
    """Signed debit-minus-credit of a row group excluding FX_GAIN_LOSS rows."""
    return sum(r["debit_minor"] - r["credit_minor"] for r in group if r["account"] != "FX_GAIN_LOSS")


def fx_plug_row(ids: IdFactory, w: World, template: dict, balance: int,
                invoice_id: str | None = None) -> dict | None:
    """FX_GAIN_LOSS row that balances a group with debit-credit ``balance``."""
    if balance == 0:
        return None
    side = "cr" if balance > 0 else "dr"
    return new_row(ids, template["timestamp"], "FX_GAIN_LOSS", abs(balance), side, w.base,
                   template["entity_id"], invoice_id, template["payment_id"])


def payment_rows(w: World, rng: random.Random, ids: IdFactory, pay: dict) -> list[dict]:
    """BANK row at the payment-date rate, AR/AP rows at invoice rates, FX difference row."""
    moment = w.meta[pay["payment_id"]]["moment"]
    ts = stamp(rng, moment)
    cur, pid, ent = pay["currency"], pay["payment_id"], pay["entity_id"]
    bank = to_base(w, pay["amount_minor"], cur, moment.date())
    incoming = pay["direction"] == "incoming"
    bank_side = ("dr" if bank > 0 else "cr") if incoming else ("cr" if bank > 0 else "dr")
    rows = [new_row(ids, ts, "BANK", abs(bank), bank_side, w.base, ent, None, pid)]
    for ref in pay["invoice_refs"]:
        inv_day = w.meta[ref["invoice_id"]]["moment"].date()
        amt = to_base(w, ref["amount_minor"], cur, inv_day)
        if incoming:
            side = "cr" if amt > 0 else "dr"
            rows.append(new_row(ids, ts, "AR", abs(amt), side, w.base, ent, ref["invoice_id"], pid))
        else:
            side = "dr" if amt > 0 else "cr"
            rows.append(new_row(ids, ts, "AP", abs(amt), side, w.base, ent, ref["invoice_id"], pid))
    plug = fx_plug_row(ids, w, rows[0], plug_amount(rows))
    return rows + ([plug] if plug else [])


def journal_pair(w: World, rng: random.Random, ids: IdFactory) -> list[dict]:
    """A non-document journal entry (bank charges, payroll, interest) in base currency."""
    moment = random_moment(w, rng, 1, w.last_day(), 7, 21)
    ts = stamp(rng, moment)
    amt = max(1, random_total_major(rng, w.base) // rng.randint(3, 40)) * 10 ** w.exp(w.base)
    dr, cr = ("EXPENSE", "BANK") if rng.random() < 0.75 else ("BANK", "REVENUE")
    return [new_row(ids, ts, dr, amt, "dr", w.base, None, None, None),
            new_row(ids, ts, cr, amt, "cr", w.base, None, None, None)]


def build_books(w: World, rng: random.Random, ids: IdFactory, ledger_range: list[int],
                grow: int = 0, shrink: int = 0) -> list[dict]:
    """Build the clean ledger and pad it with journal entries to a target size.

    ``grow``/``shrink`` reserve room for rows the injectors will add/remove later.
    """
    rows: list[dict] = []
    for inv in w.invoices:
        if w.meta[inv["invoice_id"]]["posted"]:
            rows.extend(invoice_rows(w, rng, ids, inv))
    for pay in w.payments:
        rows.extend(payment_rows(w, rng, ids, pay))
    lo, hi = ledger_range
    floor, ceiling = lo + shrink, hi - grow - 1
    if floor > ceiling:  # window too narrow for the worst case: aim at its middle
        floor = ceiling = (lo + hi - grow + shrink) // 2
    target = rng.randint(max(floor, len(rows)), max(ceiling, len(rows)))
    while len(rows) < target:
        rows.extend(journal_pair(w, rng, ids))
    return rows


def check_invariants(w: World, rows: list[dict]) -> list[str]:
    """Clean-book invariants; returns a list of violations (empty = OK)."""
    bad: list[str] = []
    for r in rows:
        if not ((r["debit_minor"] > 0) ^ (r["credit_minor"] > 0)) or min(r["debit_minor"], r["credit_minor"]) < 0:
            bad.append(f"one-sided:{r['row_id']}")
        if r["currency"] != w.base or not in_period(local_date(r["timestamp"], w.tz), w.period_start, w.period_end):
            bad.append(f"currency-or-period:{r['row_id']}")
    if sum(r["debit_minor"] for r in rows) != sum(r["credit_minor"] for r in rows):
        bad.append("unbalanced")
    by_inv: dict[str, list[dict]] = {}
    by_pay: dict[str, list[dict]] = {}
    for r in rows:
        if r["payment_id"]:
            by_pay.setdefault(r["payment_id"], []).append(r)
        elif r["invoice_id"]:
            by_inv.setdefault(r["invoice_id"], []).append(r)
    bad.extend(_check_invoices(w, by_inv))
    bad.extend(_check_payments(w, by_pay))
    return bad


def _check_invoices(w: World, by_inv: dict[str, list[dict]]) -> list[str]:
    bad = []
    for inv in w.invoices:
        group = by_inv.get(inv["invoice_id"], [])
        if sum(i["amount_minor"] for i in inv["line_items"]) != inv["total_minor"]:
            bad.append(f"items:{inv['invoice_id']}")
        if not w.meta[inv["invoice_id"]]["posted"]:
            if group:
                bad.append(f"posted-out-of-period:{inv['invoice_id']}")
            continue
        day = w.meta[inv["invoice_id"]]["moment"].date()
        want = to_base(w, inv["total_minor"], inv["currency"], day)
        if len(group) != 2 or any(r["debit_minor"] + r["credit_minor"] != want for r in group):
            bad.append(f"invoice-rows:{inv['invoice_id']}")
    return bad


def _check_payments(w: World, by_pay: dict[str, list[dict]]) -> list[str]:
    bad = []
    for pay in w.payments:
        group = by_pay.get(pay["payment_id"], [])
        if sum(r["amount_minor"] for r in pay["invoice_refs"]) != pay["amount_minor"]:
            bad.append(f"refs:{pay['payment_id']}")
        if plug_amount(group) + sum(r["debit_minor"] - r["credit_minor"] for r in group
                                    if r["account"] == "FX_GAIN_LOSS") != 0:
            bad.append(f"payment-unbalanced:{pay['payment_id']}")
        bank = [r for r in group if r["account"] == "BANK"]
        day = w.meta[pay["payment_id"]]["moment"].date()
        want = abs(to_base(w, pay["amount_minor"], pay["currency"], day))
        if len(bank) != 1 or bank[0]["debit_minor"] + bank[0]["credit_minor"] != want:
            bad.append(f"bank:{pay['payment_id']}")
        for ref in pay["invoice_refs"]:
            alloc = [r for r in group if r["invoice_id"] == ref["invoice_id"] and r["account"] in ("AR", "AP")]
            inv_day = w.meta[ref["invoice_id"]]["moment"].date()
            want = abs(to_base(w, ref["amount_minor"], pay["currency"], inv_day))
            if len(alloc) != 1 or alloc[0]["debit_minor"] + alloc[0]["credit_minor"] != want:
                bad.append(f"alloc:{pay['payment_id']}")
    return bad
