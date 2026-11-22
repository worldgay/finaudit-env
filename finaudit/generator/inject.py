"""Инжекторы ошибок: каждый делает одно причинное изменение и возвращает созданную Issue."""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from decimal import Decimal

from finaudit.generator.books import fx_plug_row, invoice_rows, new_row, plug_amount, to_base
from finaudit.generator.world import World, add_invoice, stamp
from finaudit.util.ids import IdFactory
from finaudit.util.money import convert, inverse_convert
from finaudit.util.timeutil import make_local


class NoCandidate(Exception):
    """Выбрасывается, когда инжектору нечего портить (генератор повторяет попытку)."""


@dataclass(frozen=True)
class Issue:
    """Одна скрытая ошибка в том виде, как она записана в truth.json."""

    issue_id: str
    type: str
    affected_ids: tuple[str, ...]
    expected_amount_minor: int
    currency: str
    evidence_sets: tuple[tuple[str, ...], ...]
    scenario: str | None

    def to_dict(self) -> dict:
        """Форма JSON."""
        return {"issue_id": self.issue_id, "type": self.type, "affected_ids": list(self.affected_ids),
                "expected_amount_minor": self.expected_amount_minor, "currency": self.currency,
                "evidence_sets": [list(e) for e in self.evidence_sets], "scenario": self.scenario}


@dataclass(frozen=True)
class ProvenanceEntry:
    """Что изменил инжектор (table, id, field, before -> after) и в каком порядке."""

    issue_id: str
    injector: str
    changes: tuple[dict, ...]
    order: int

    def to_dict(self) -> dict:
        """Форма JSON."""
        return {"issue_id": self.issue_id, "injector": self.injector,
                "changes": list(self.changes), "order": self.order}


@dataclass
class Ctx:
    """Изменяемое рабочее состояние, общее для инжекторов одного эпизода."""

    w: World
    rows: list[dict]
    ids: IdFactory
    rng: random.Random
    used: set[str] = field(default_factory=set)
    issues: list[Issue] = field(default_factory=list)
    provenance: list[ProvenanceEntry] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)

    def inv(self, iid: str) -> dict:
        """Счёт по invoice_id."""
        return next(i for i in self.w.invoices if i["invoice_id"] == iid)

    def pay(self, pid: str) -> dict:
        """Платёж по payment_id."""
        return next(p for p in self.w.payments if p["payment_id"] == pid)

    def pay_rows(self, pid: str) -> list[dict]:
        """Строки ledger с payment_id ``pid``."""
        return [r for r in self.rows if r["payment_id"] == pid]

    def principal(self, iid: str) -> dict:
        """Строка AR/AP, проводящая сам счёт (без payment_id)."""
        return next(r for r in self.rows if r["invoice_id"] == iid and r["payment_id"] is None
                    and r["account"] in ("AR", "AP"))

    def counterpart(self, iid: str) -> dict:
        """Строка REVENUE/EXPENSE, проводящая счёт."""
        return next(r for r in self.rows if r["invoice_id"] == iid and r["payment_id"] is None
                    and r["account"] in ("REVENUE", "EXPENSE"))

    def alloc_row(self, pid: str, iid: str) -> dict:
        """Строка AR/AP, распределяющая платёж ``pid`` на счёт ``iid``."""
        return next(r for r in self.pay_rows(pid) if r["invoice_id"] == iid
                    and r["account"] in ("AR", "AP"))

    def set(self, row: dict, fld: str, value) -> None:
        """Меняет одно поле строки ledger и записывает изменение."""
        self.changes.append({"table": "ledger", "id": row["row_id"], "field": fld,
                             "before": row[fld], "after": value})
        row[fld] = value

    def set_amount(self, row: dict, amount: int) -> None:
        """Меняет ненулевую сторону строки."""
        self.set(row, "debit_minor" if row["debit_minor"] > 0 else "credit_minor", amount)

    def add(self, row: dict) -> None:
        """Добавляет строку ledger и записывает изменение."""
        self.rows.append(row)
        self.changes.append({"table": "ledger", "id": row["row_id"], "field": "*",
                             "before": None, "after": dict(row)})

    def remove(self, row: dict) -> None:
        """Удаляет строку ledger и записывает изменение."""
        self.rows.remove(row)
        self.changes.append({"table": "ledger", "id": row["row_id"], "field": "*",
                             "before": dict(row), "after": None})

    def rebalance(self, group: list[dict], template: dict, invoice_id: str | None) -> None:
        """Заново подставляет FX_GAIN_LOSS, чтобы группа строк снова сходилась."""
        fx_rows = [r for r in group if r["account"] == "FX_GAIN_LOSS"]
        bal = plug_amount(group)
        for r in fx_rows:
            self.remove(r)
        plug = fx_plug_row(self.ids, self.w, template, bal, invoice_id)
        if plug:
            self.add(plug)

    def record(self, issue: Issue, injector: str) -> Issue:
        """Сохраняет ошибку вместе с журналом изменений, накопленным с прошлой записи."""
        self.issues.append(issue)
        order = len(self.provenance)
        self.provenance.append(ProvenanceEntry(issue.issue_id, injector, tuple(self.changes), order))
        self.changes = []
        return issue


def _sorted(*items: str) -> tuple[str, ...]:
    return tuple(sorted(items))


def _day(ctx: Ctx, ident: str) -> date:
    return ctx.w.meta[ident]["moment"].date()


def _plain_posted(ctx: Ctx, foreign: bool = False) -> list[dict]:
    w = ctx.w
    return [i for i in w.invoices if w.meta[i["invoice_id"]]["kind"] == "plain"
            and w.meta[i["invoice_id"]]["posted"] and i["invoice_id"] not in ctx.used
            and (not foreign or i["currency"] != w.base)]


def _plain_payments(ctx: Ctx, foreign: bool = False) -> list[dict]:
    w = ctx.w
    out = []
    for p in w.payments:
        iid = p["invoice_refs"][0]["invoice_id"]
        if (w.meta[p["payment_id"]]["kind"] == "plain" and len(p["invoice_refs"]) == 1
                and p["amount_minor"] > 0 and p["payment_id"] not in ctx.used
                and iid not in ctx.used and (not foreign or p["currency"] != w.base)):
            out.append(p)
    return out


def inject_duplicate(ctx: Ctx, orig: dict | None = None, scenario: str | None = None) -> tuple[Issue, dict]:
    """Копирует счёт (новые doc/invoice ID, те же строки, дата сдвинута на 0-3 дня) и проводит его."""
    w, rng = ctx.w, ctx.rng
    if orig is None:
        cands = _plain_posted(ctx)
        if not cands:
            raise NoCandidate("duplicate")
        orig = rng.choice(cands)
    day = _day(ctx, orig["invoice_id"])
    shifts = [d for d in (0, 1, 2, 3, -1, -2, -3)
              if w.period_start <= day + timedelta(days=d) <= w.period_end]
    if scenario:
        shifts = [d for d in shifts if d >= 0]
    moment = make_local(day + timedelta(days=rng.choice(shifts)), rng.randint(8, 20),
                        rng.choice([0, 15, 30, 45]), w.tz)
    dup = add_invoice(w, rng, ctx.ids, direction=orig["direction"],
                      entity={"entity_id": orig["entity_id"]}, currency=orig["currency"],
                      moment=moment, kind="dup_copy", items=copy.deepcopy(orig["line_items"]))
    ctx.changes.append({"table": "invoices", "id": dup["doc_id"], "field": "*",
                        "before": None, "after": copy.deepcopy(dup)})
    for row in invoice_rows(w, rng, ctx.ids, dup):
        ctx.add(row)
    ctx.used.update({orig["invoice_id"], dup["invoice_id"]})
    p_orig, p_dup = ctx.principal(orig["invoice_id"]), ctx.principal(dup["invoice_id"])
    issue = Issue(ctx.ids.new("iss"), "DUPLICATE_INVOICE", _sorted(orig["invoice_id"], dup["invoice_id"]),
                  dup["total_minor"], dup["currency"],
                  (_sorted(orig["doc_id"], dup["doc_id"], p_orig["row_id"], p_dup["row_id"]),),
                  scenario)
    return ctx.record(issue, "duplicate_invoice"), dup


def _recoverable_split(ctx: Ctx, amount: int, currency: str, day, frac_lo: int, frac_hi: int) -> int | None:
    """Выбирает x < amount, чьё базовое значение точно конвертируется обратно; возвращает x или None."""
    w = ctx.w
    rate, es, eb = w.rate(currency, day), w.exp(currency), w.exp(w.base)
    full = convert(amount, es, rate, eb)
    for _ in range(40):
        x0 = amount - max(1, amount * ctx.rng.randint(frac_lo, frac_hi) // 100)
        b = convert(x0, es, rate, eb)
        x = inverse_convert(b, es, rate, eb)
        if 0 < x < amount and b > 0 and convert(x, es, rate, eb) == b and b != full:
            return x
    return None


def _alloc_issue(ctx: Ctx, pay: dict, inv: dict, unalloc: int, scenario: str | None) -> Issue:
    group = ctx.pay_rows(pay["payment_id"])
    rows = [r["row_id"] for r in group]
    booked = any(r["invoice_id"] == inv["invoice_id"] and r["account"] in ("AR", "AP") for r in group)
    if booked and pay["currency"] != ctx.w.base:  # сумму можно проверить только по курсу даты счёта
        rows.append(f"fx:{_day(ctx, inv['invoice_id']).isoformat()}:{pay['currency']}:{ctx.w.base}")
    ev = _sorted(pay["doc_id"], inv["doc_id"], *rows)
    issue = Issue(ctx.ids.new("iss"), "PAYMENT_ALLOCATION", _sorted(inv["invoice_id"], pay["payment_id"]),
                  unalloc, pay["currency"], (ev,), scenario)
    return ctx.record(issue, "payment_allocation")


def inject_allocation(ctx: Ctx, pay: dict | None = None, variant: str | None = None,
                      scenario: str | None = None) -> Issue:
    """Оставляет часть (a) или весь (b) платёж на SUSPENSE либо не проводит его вовсе (c)."""
    w, rng = ctx.w, ctx.rng
    if pay is None:
        cands = _plain_payments(ctx)
        if not cands:
            raise NoCandidate("allocation")
        pay = rng.choice(cands)
    ref = pay["invoice_refs"][0]
    inv = ctx.inv(ref["invoice_id"])
    variant = variant or rng.choice(["a", "a", "b", "c"])
    a = ref["amount_minor"]
    x = _recoverable_split(ctx, a, pay["currency"], _day(ctx, inv["invoice_id"]), 15, 70) \
        if variant == "a" else None
    if variant == "a" and x is None:
        variant = "b"
    ctx.used.update({pay["payment_id"], inv["invoice_id"]})
    if variant == "c":
        for row in list(ctx.pay_rows(pay["payment_id"])):
            ctx.remove(row)
        return _alloc_issue(ctx, pay, inv, a, scenario)
    row = ctx.alloc_row(pay["payment_id"], inv["invoice_id"])
    if variant == "b":
        ctx.set(row, "account", "SUSPENSE")
        ctx.set(row, "invoice_id", None)
        return _alloc_issue(ctx, pay, inv, a, scenario)
    full = row["debit_minor"] + row["credit_minor"]
    posted = convert(x, w.exp(pay["currency"]), w.rate(pay["currency"], _day(ctx, inv["invoice_id"])),
                     w.exp(w.base))
    side = "dr" if row["debit_minor"] > 0 else "cr"
    ctx.set_amount(row, posted)
    ctx.add(new_row(ctx.ids, row["timestamp"], "SUSPENSE", full - posted, side, w.base,
                    row["entity_id"], None, pay["payment_id"]))
    return _alloc_issue(ctx, pay, inv, a - x, scenario)


def _wrong_rate(ctx: Ctx, currency: str, moment, variant: str) -> tuple[str, str]:
    """Возвращает (вариант, неверный курс) для момента документа."""
    w = ctx.w
    day = moment.date()
    utc_day = moment.astimezone(timezone.utc).date()
    if variant == "utc" and utc_day != day:
        return "utc", w.rate(currency, utc_day)
    if variant == "inverse":
        inv_rate = (Decimal(1) / Decimal(w.rate(currency, day))).quantize(Decimal("0.000001"))
        return "inverse", str(inv_rate)
    shift = ctx.rng.choice([-3, -2, -1, 1, 2, 3]) if variant != "next" else 1
    return "shift", w.rate(currency, day + timedelta(days=shift))


def inject_fx(ctx: Ctx, target: dict | None = None, variant: str | None = None,
              scenario: str | None = None) -> Issue:
    """Проводит документ в базовой валюте по курсу другой даты (или по обратному курсу)."""
    w, rng = ctx.w, ctx.rng
    cands = [target] if target else _plain_posted(ctx, foreign=True) + _plain_payments(ctx, foreign=True)
    rng.shuffle(cands)
    for doc in cands:
        is_pay = "payment_id" in doc
        ident = doc["payment_id"] if is_pay else doc["invoice_id"]
        moment = w.meta[ident]["moment"]
        amount = abs(doc["amount_minor"] if is_pay else doc["total_minor"])
        correct = to_base(w, amount, doc["currency"], moment.date())
        want = variant or rng.choice(["utc", "shift", "shift", "inverse"])
        _, rate = _wrong_rate(ctx, doc["currency"], moment, want)
        wrong = convert(amount, w.exp(doc["currency"]), rate, w.exp(w.base))
        if wrong == correct or wrong <= 0:
            continue
        ctx.used.add(ident)
        if is_pay:
            ctx.used.add(doc["invoice_refs"][0]["invoice_id"])
            row = next(r for r in ctx.pay_rows(ident) if r["account"] == "BANK")
            ctx.set_amount(row, wrong)
            ctx.rebalance(ctx.pay_rows(ident), row, None)
        else:
            row = ctx.principal(ident)
            ctx.set_amount(row, wrong)
            if rng.random() < 0.5:
                ctx.set_amount(ctx.counterpart(ident), wrong)
            else:
                group = [r for r in ctx.rows if r["invoice_id"] == ident and r["payment_id"] is None]
                ctx.rebalance(group, row, ident)
        fx_ref = f"fx:{moment.date().isoformat()}:{doc['currency']}:{w.base}"
        issue = Issue(ctx.ids.new("iss"), "FX_CONVERSION", (ident,), abs(wrong - correct), w.base,
                      (_sorted(doc["doc_id"], fx_ref, row["row_id"]),), scenario)
        return ctx.record(issue, "fx_conversion")
    raise NoCandidate("fx")


def inject_cutoff(ctx: Ctx) -> Issue:
    """Проводит внутри периода счёт, выставленный после конца периода (по местной дате)."""
    w, rng = ctx.w, ctx.rng
    cands = [i for i in w.invoices if w.meta[i["invoice_id"]]["kind"] == "next_month"
             and i["invoice_id"] not in ctx.used]
    if len(cands) < 2:
        raise NoCandidate("cutoff")
    inv = cands[0] if rng.random() < 0.5 else rng.choice(cands)
    ts = stamp(rng, make_local(w.period_end, rng.randint(9, 20), rng.choice([0, 20, 40]), w.tz))
    for row in invoice_rows(w, rng, ctx.ids, inv, ts=ts):
        ctx.add(row)
    ctx.used.add(inv["invoice_id"])
    row = ctx.principal(inv["invoice_id"])
    issue = Issue(ctx.ids.new("iss"), "PERIOD_CUTOFF", (inv["invoice_id"],),
                  row["debit_minor"] + row["credit_minor"], w.base,
                  (_sorted(inv["doc_id"], row["row_id"]),), None)
    return ctx.record(issue, "period_cutoff")


def inject_i1(ctx: Ctx, iid: str, pid: str) -> None:
    """I1: поздний вечерний иностранный платёж в последний день, BANK по курсу UTC-даты (или следующего
    дня), затем частичное распределение на SUSPENSE. Сначала FX, потом распределение."""
    pay = ctx.pay(pid)
    moment = ctx.w.meta[pid]["moment"]
    utc_differs = moment.astimezone(timezone.utc).date() != moment.date()
    inject_fx(ctx, target=pay, variant="utc" if utc_differs else "next", scenario="I1")
    ctx.used.discard(pid)
    ctx.used.discard(iid)
    inject_allocation(ctx, pay=pay, variant="a", scenario="I1")


def inject_i2(ctx: Ctx, iid: str, pid: str) -> None:
    """I2: счёт продублирован; единственный платёж по нему проведён 50/50 на оригинал и копию."""
    w = ctx.w
    orig, pay = ctx.inv(iid), ctx.pay(pid)
    _, dup = inject_duplicate(ctx, orig=orig, scenario="I2")
    a = pay["invoice_refs"][0]["amount_minor"]
    x = _recoverable_split(ctx, a, pay["currency"], _day(ctx, iid), 50, 50) \
        or _recoverable_split(ctx, a, pay["currency"], _day(ctx, iid), 35, 65)
    if x is None:
        raise NoCandidate("i2")
    row = ctx.alloc_row(pid, iid)
    es, eb = w.exp(pay["currency"]), w.exp(w.base)
    ctx.set_amount(row, convert(x, es, w.rate(pay["currency"], _day(ctx, iid)), eb))
    half = convert(a - x, es, w.rate(pay["currency"], _day(ctx, dup["invoice_id"])), eb)
    side = "dr" if row["debit_minor"] > 0 else "cr"
    ctx.add(new_row(ctx.ids, row["timestamp"], "AR", half, side, w.base, row["entity_id"],
                    dup["invoice_id"], pid))
    ctx.rebalance(ctx.pay_rows(pid), next(r for r in ctx.pay_rows(pid) if r["account"] == "BANK"), None)
    ctx.used.update({pid, iid})
    _alloc_issue(ctx, pay, orig, a - x, "I2")


def run_injections(ctx: Ctx, plan: dict[str, int]) -> None:
    """Применяет план в фиксированном порядке: I1, I2, дубли, распределения, FX, период."""
    for iid, pid in ctx.w.slots["I1"]:
        inject_i1(ctx, iid, pid)
    for iid, pid in ctx.w.slots["I2"]:
        inject_i2(ctx, iid, pid)
    for _ in range(plan["DUPLICATE_INVOICE"]):
        inject_duplicate(ctx)
    for _ in range(plan["PAYMENT_ALLOCATION"]):
        inject_allocation(ctx)
    for _ in range(plan["FX_CONVERSION"]):
        inject_fx(ctx)
    for _ in range(plan["PERIOD_CUTOFF"]):
        inject_cutoff(ctx)
