"""Независимый эталонный аудитор.

Читает ТОЛЬКО открытые файлы (manifest, policy, ledger, invoices, payments, fx)
и заново выводит каждое расхождение из опубликованной policy. Он намеренно
не импортирует инжекторы: verify.py сравнивает его результат с truth.json.
"""
from __future__ import annotations

from finaudit.util.canon import dumps
from finaudit.util.money import convert, inverse_convert
from finaudit.util.timeutil import in_period, local_date, parse_date


class _Books:
    """Индексированное представление открытых файлов."""

    def __init__(self, public: dict) -> None:
        m = public["manifest"]
        self.base, self.tz = m["base_currency"], m["timezone"]
        self.start, self.end = parse_date(m["period_start"]), parse_date(m["period_end"])
        self.exps = m["currency_exponents"]
        self.rates = {(r["date"], r["source_currency"]): r["rate"] for r in public["fx"]}
        self.invoices = public["invoices"]
        self.payments = public["payments"]
        self.inv_by_id = {i["invoice_id"]: i for i in self.invoices}
        self.inv_rows: dict[str, list[dict]] = {}
        self.pay_rows: dict[str, list[dict]] = {}
        for r in public["ledger"]:
            if r["payment_id"] is not None:
                self.pay_rows.setdefault(r["payment_id"], []).append(r)
            elif r["invoice_id"] is not None:
                self.inv_rows.setdefault(r["invoice_id"], []).append(r)

    def rate(self, currency: str, day) -> str:
        """Курс по policy для местной даты."""
        return "1" if currency == self.base else self.rates[(day.isoformat(), currency)]

    def conv(self, amount: int, currency: str, day) -> int:
        """Конвертация по policy в минимальные единицы базы."""
        return convert(amount, self.exps[currency], self.rate(currency, day), self.exps[self.base])

    def fx_ref(self, currency: str, day) -> str:
        """Открытый ID строки fx по policy."""
        return f"fx:{day.isoformat()}:{currency}:{self.base}"

    def principal(self, inv: dict) -> dict | None:
        """Строка AR (к получению) или AP (к оплате), проводящая счёт."""
        acct = "AR" if inv["direction"] == "receivable" else "AP"
        rows = [r for r in self.inv_rows.get(inv["invoice_id"], []) if r["account"] == acct]
        return rows[0] if rows else None


def _amount(row: dict) -> int:
    return row["debit_minor"] + row["credit_minor"]


def _finding(typ: str, affected: list[str], amount: int, currency: str, evidence: list[list[str]]) -> dict:
    return {"type": typ, "affected_ids": sorted(affected), "expected_amount_minor": amount,
            "currency": currency, "evidence_sets": [sorted(e) for e in evidence]}


def _invoice_checks(b: _Books) -> list[dict]:
    out = []
    for inv in b.invoices:
        row = b.principal(inv)
        if row is None:
            continue
        day = local_date(inv["issued_at"], b.tz)
        if not in_period(day, b.start, b.end):
            out.append(_finding("PERIOD_CUTOFF", [inv["invoice_id"]], _amount(row), b.base,
                                [[inv["doc_id"], row["row_id"]]]))
            continue
        want = b.conv(inv["total_minor"], inv["currency"], day)
        if _amount(row) != want:
            out.append(_finding("FX_CONVERSION", [inv["invoice_id"]], abs(_amount(row) - want), b.base,
                                [[inv["doc_id"], b.fx_ref(inv["currency"], day), row["row_id"]]]))
    return out


def _duplicate_checks(b: _Books) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for inv in b.invoices:
        if b.principal(inv) is None:
            continue
        key = dumps([inv["direction"], inv["entity_id"], inv["currency"], inv["total_minor"],
                     inv["line_items"]])
        groups.setdefault(key, []).append(inv)
    out = []
    for members in groups.values():
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                gap = abs((local_date(first["issued_at"], b.tz) - local_date(second["issued_at"], b.tz)).days)
                if gap > 3:
                    continue
                rows = [b.principal(first)["row_id"], b.principal(second)["row_id"]]
                out.append(_finding("DUPLICATE_INVOICE", [first["invoice_id"], second["invoice_id"]],
                                    second["total_minor"], first["currency"],
                                    [[first["doc_id"], second["doc_id"]] + rows]))
    return out


def _payment_checks(b: _Books) -> list[dict]:
    out = []
    for pay in b.payments:
        rows = b.pay_rows.get(pay["payment_id"], [])
        cur, day = pay["currency"], local_date(pay["timestamp"], b.tz)
        bank = [r for r in rows if r["account"] == "BANK"]
        if bank:
            want = abs(b.conv(pay["amount_minor"], cur, day))
            if _amount(bank[0]) != want:
                out.append(_finding("FX_CONVERSION", [pay["payment_id"]], abs(_amount(bank[0]) - want),
                                    b.base, [[pay["doc_id"], b.fx_ref(cur, day), bank[0]["row_id"]]]))
        incoming = pay["direction"] == "incoming"
        acct = "AR" if incoming else "AP"
        for ref in pay["invoice_refs"]:
            inv = b.inv_by_id[ref["invoice_id"]]
            inv_day = local_date(inv["issued_at"], b.tz)
            alloc = [r for r in rows if r["invoice_id"] == ref["invoice_id"] and r["account"] == acct]
            signed = sum((r["credit_minor"] - r["debit_minor"]) if incoming
                         else (r["debit_minor"] - r["credit_minor"]) for r in alloc)
            if signed == b.conv(ref["amount_minor"], cur, inv_day):
                continue
            allocated = inverse_convert(signed, b.exps[cur], b.rate(cur, inv_day), b.exps[b.base])
            gap = abs(ref["amount_minor"] - allocated)
            if gap:
                evidence = [pay["doc_id"], inv["doc_id"]] + [r["row_id"] for r in rows]
                if alloc and cur != b.base:
                    evidence.append(b.fx_ref(cur, inv_day))
                out.append(_finding("PAYMENT_ALLOCATION", [ref["invoice_id"], pay["payment_id"]], gap,
                                    cur, [evidence]))
    return out


def reference_audit(public: dict) -> list[dict]:
    """Возвращает все расхождения, найденные в открытых записях (отсортированные, канонические)."""
    b = _Books(public)
    found = _invoice_checks(b) + _duplicate_checks(b) + _payment_checks(b)
    return sorted(found, key=lambda f: dumps([f["type"], f["affected_ids"]]))
