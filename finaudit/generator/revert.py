"""Откатывает записанные внесения ошибок (provenance.json), чтобы восстановить книги *до* любой ошибки.

Не зависит от внутренностей генератора: только проигрывает журнал изменений в обратном порядке на открытых
записях, затем проверяет бухгалтерские равенства до ошибки независимым эталонным аудитором.
"""
from __future__ import annotations

import copy

from finaudit.generator.reference_audit import reference_audit
from finaudit.util.timeutil import in_period, local_date, parse_date


def revert(public: dict, provenance: dict) -> dict:
    """Возвращает копию ``public``, в которой отменено каждое записанное изменение (с последнего)."""
    out = copy.deepcopy(public)
    ledger, invoices = out["ledger"], out["invoices"]
    for entry in sorted(provenance.get("injections", []), key=lambda e: e["order"], reverse=True):
        for ch in reversed(entry["changes"]):
            if ch["table"] == "invoices":
                if ch["field"] == "*" and ch["before"] is None:
                    invoices[:] = [i for i in invoices if i["doc_id"] != ch["id"]]
                continue
            if ch["field"] == "*":
                if ch["before"] is None:
                    ledger[:] = [r for r in ledger if r["row_id"] != ch["id"]]
                else:
                    ledger.append(copy.deepcopy(ch["before"]))
            else:
                row = next(r for r in ledger if r["row_id"] == ch["id"])
                row[ch["field"]] = ch["before"]
    return out


def pre_error_problems(public: dict, provenance: dict) -> list[str]:
    """Бухгалтерские равенства, которые должны выполняться до внесения ошибок."""
    clean = revert(public, provenance)
    m = clean["manifest"]
    start, end = parse_date(m["period_start"]), parse_date(m["period_end"])
    led = clean["ledger"]
    bad = []
    if sum(r["debit_minor"] for r in led) != sum(r["credit_minor"] for r in led):
        bad.append("pre-error ledger unbalanced")
    if any(not ((r["debit_minor"] > 0) ^ (r["credit_minor"] > 0)) for r in led):
        bad.append("pre-error row not one-sided")
    if any(not in_period(local_date(r["timestamp"], m["timezone"]), start, end) for r in led):
        bad.append("pre-error row outside the period")
    booked = {r["invoice_id"] for r in led if r["invoice_id"] and r["payment_id"] is None
              and r["account"] in ("AR", "AP")}
    for inv in clean["invoices"]:
        inside = in_period(local_date(inv["issued_at"], m["timezone"]), start, end)
        if inside != (inv["invoice_id"] in booked):
            bad.append(f"pre-error booking status {inv['invoice_id']}")
    paid = {r["payment_id"] for r in led if r["payment_id"] and r["account"] == "BANK"}
    bad += [f"pre-error payment not booked {p['payment_id']}" for p in clean["payments"] if p["payment_id"] not in paid]
    found = reference_audit(clean)
    if found:
        bad.append(f"pre-error books show discrepancies: {[f['type'] for f in found][:3]}")
    return bad
