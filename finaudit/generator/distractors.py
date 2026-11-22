"""Корректные, но коварные случаи, ломающие наивные правила аудита (никогда не настоящие ошибки)."""
from __future__ import annotations

import random
from datetime import timedelta

from finaudit.generator.world import (SERVICES, World, add_invoice, add_payment,
                                      random_moment, random_total_major)
from finaudit.util.ids import IdFactory
from finaudit.util.money import convert
from finaudit.util.timeutil import make_local, offset_minutes, render_ts

KINDS = ("split_payment", "multi_invoice_payment", "overpayment_refund", "weekly_recurring",
         "boundary_time", "next_month_invoices", "fx_gain_loss", "rounding")


def _pick_currency(w: World, rng: random.Random, foreign_bias: float = 0.55) -> str:
    return rng.choice(w.foreign) if rng.random() < foreign_bias else w.base


def add_split(w: World, rng: random.Random, ids: IdFactory) -> None:
    """Один иностранный счёт, оплаченный 2-3 платежами (всё корректно)."""
    cur = rng.choice(w.foreign)
    ent = rng.choice(w.entities_of("customer"))
    inv_m = random_moment(w, rng, 1, w.last_day() - 6)
    inv = add_invoice(w, rng, ids, direction="receivable", entity=ent, currency=cur,
                      moment=inv_m, kind="split_payment")
    total, k = inv["total_minor"], rng.randint(2, 3)
    ratio_rate = w.rate(cur, inv_m.date())
    parts: list[int] = []
    for _ in range(60):  # предпочитаем части, чьё округление отличается от целого на одну единицу
        cuts = sorted(rng.sample(range(1, total), k - 1))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [total])]
        conv_sum = sum(convert(p, w.exp(cur), ratio_rate, w.exp(w.base)) for p in parts)
        if conv_sum != convert(total, w.exp(cur), ratio_rate, w.exp(w.base)):
            break
    days = sorted(rng.sample(range(inv_m.day + 1, w.last_day() + 1), k))
    for part, day in zip(parts, days):
        add_payment(w, rng, ids, invs=[inv], amounts=[part],
                    moment=random_moment(w, rng, day, day), kind="split_payment")
    w.distractors.append("split_payment")


def add_multi(w: World, rng: random.Random, ids: IdFactory) -> None:
    """Один платёж, закрывающий 2-3 счёта одного контрагента."""
    direction = rng.choice(["receivable", "payable"])
    role = "customer" if direction == "receivable" else "supplier"
    ent, cur = rng.choice(w.entities_of(role)), _pick_currency(w, rng)
    invs = [add_invoice(w, rng, ids, direction=direction, entity=ent, currency=cur,
                        moment=random_moment(w, rng, 1, w.last_day() - 3),
                        kind="multi_invoice_payment") for _ in range(rng.randint(2, 3))]
    latest = max(w.meta[i["invoice_id"]]["moment"].day for i in invs)
    add_payment(w, rng, ids, invs=invs, amounts=[i["total_minor"] for i in invs],
                moment=random_moment(w, rng, latest + 1, w.last_day()), kind="multi_invoice_payment")
    w.distractors.append("multi_invoice_payment")


def add_refund(w: World, rng: random.Random, ids: IdFactory) -> None:
    """Покупатель переплачивает по счёту и позже получает возврат (отрицательный платёж)."""
    ent, cur = rng.choice(w.entities_of("customer")), _pick_currency(w, rng)
    inv_m = random_moment(w, rng, 1, w.last_day() - 4)
    inv = add_invoice(w, rng, ids, direction="receivable", entity=ent, currency=cur, moment=inv_m,
                      kind="overpayment_refund")
    extra = max(1, inv["total_minor"] * rng.randint(1, 10) // 100)
    pay_day = rng.randint(inv_m.day + 1, w.last_day() - 1)
    add_payment(w, rng, ids, invs=[inv], amounts=[inv["total_minor"] + extra],
                moment=random_moment(w, rng, pay_day, pay_day), kind="overpayment_refund")
    add_payment(w, rng, ids, invs=[inv], amounts=[-extra],
                moment=random_moment(w, rng, pay_day + 1, w.last_day()), kind="overpayment_refund")
    w.distractors.append("overpayment_refund")


def add_weekly(w: World, rng: random.Random, ids: IdFactory) -> None:
    """Еженедельная услуга: тот же контрагент и сумма каждые 7 дней, разная метка недели."""
    ent, cur = rng.choice(w.entities_of("customer")), _pick_currency(w, rng)
    n = 4 if w.last_day() >= 23 and rng.random() < 0.5 else 3
    start = rng.randint(1, w.last_day() - 7 * (n - 1))
    service = rng.choice(SERVICES)
    scale = 10 ** w.exp(cur)
    unit = max(1, random_total_major(rng, cur) // 4) * scale
    hour, minute = rng.randint(9, 17), rng.choice([0, 30])
    for k in range(n):
        day = w.period_start + timedelta(days=start - 1 + 7 * k)
        week = day.isocalendar()[1]
        items = [{"description": f"{service}, week {week}", "quantity": 1,
                  "unit_price_minor": unit, "amount_minor": unit}]
        add_invoice(w, rng, ids, direction="receivable", entity=ent, currency=cur,
                    moment=make_local(day, hour, minute, w.tz), kind="weekly_recurring", items=items)
    w.distractors.append("weekly_recurring")


def add_boundary(w: World, rng: random.Random, ids: IdFactory) -> bool:
    """Проведённый документ периода, чья запись в +00:00 показывает дату вне периода."""
    late = make_local(w.period_end, 23, rng.choice([30, 40, 50]), w.tz)
    early = make_local(w.period_start, 0, rng.choice([10, 20, 30]), w.tz)
    if offset_minutes(late) < 0:
        moment = late
    elif offset_minutes(early) > 0:
        moment = early
    else:
        return False
    ent = rng.choice(w.entities_of("customer"))
    inv = add_invoice(w, rng, ids, direction="receivable", entity=ent,
                      currency=rng.choice(w.foreign), moment=moment, kind="boundary_time")
    inv["issued_at"] = render_ts(moment, utc=True)
    w.distractors.append("boundary_time")
    return True


def add_next_month(w: World, rng: random.Random, ids: IdFactory, n: int) -> None:
    """Счета, выставленные в первые дни следующего месяца (должны остаться непроведёнными)."""
    for k in range(n):
        direction = rng.choice(["receivable", "payable"])
        role = "customer" if direction == "receivable" else "supplier"
        day = w.period_end + timedelta(days=1 if k == 0 else rng.randint(1, 5))
        hour = rng.randint(0, 2) if k == 0 else rng.randint(8, 20)
        moment = make_local(day, hour, rng.choice([5, 15, 25, 45]), w.tz)
        inv = add_invoice(w, rng, ids, direction=direction, entity=rng.choice(w.entities_of(role)),
                          currency=_pick_currency(w, rng), moment=moment, kind="next_month",
                          posted=False)
        if k == 0:
            inv["issued_at"] = render_ts(moment, utc=True)
    w.distractors.append("next_month_invoices")


def detect_natural(w: World, rows: list[dict]) -> None:
    """Регистрирует естественно возникающие виды (строки FX gain/loss, остаток округления в 1 единицу)."""
    if any(r["account"] == "FX_GAIN_LOSS" for r in rows):
        w.distractors.append("fx_gain_loss")
    for inv in w.invoices:
        if inv["direction"] != "receivable":
            continue
        ar = [r for r in rows if r["invoice_id"] == inv["invoice_id"] and r["account"] == "AR"]
        bal = sum(r["debit_minor"] - r["credit_minor"] for r in ar)
        paid = sum(ref["amount_minor"] for p in w.payments for ref in p["invoice_refs"]
                   if ref["invoice_id"] == inv["invoice_id"])
        if paid == inv["total_minor"] and len(ar) > 2 and abs(bal) == 1:
            w.distractors.append("rounding")
            return
