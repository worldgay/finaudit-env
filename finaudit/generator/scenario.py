"""Error plan, scenario slots (I1/I2) and ordinary documents."""
from __future__ import annotations

import random

from finaudit.generator.world import World, add_invoice, add_payment, make_local, random_moment
from finaudit.util.ids import IdFactory

ERROR_TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")
MAX_ISSUES = 12


def _draw(rng: random.Random, spec: list[int] | int) -> int:
    if isinstance(spec, int):
        return spec
    return rng.randint(spec[0], spec[1])


def plan_errors(rng: random.Random, cfg: dict) -> dict[str, int]:
    """Draw how many errors of each type and interaction scenarios to inject (<= 12 issues)."""
    plan = {t: _draw(rng, cfg["errors"][t]["count"]) for t in ERROR_TYPES}
    plan["I1"] = _draw(rng, cfg["interactions"]["I1"])
    plan["I2"] = _draw(rng, cfg["interactions"]["I2"])
    if cfg.get("clean"):
        return {k: 0 for k in plan}
    order = ["I2", "I1", "PERIOD_CUTOFF", "FX_CONVERSION", "PAYMENT_ALLOCATION", "DUPLICATE_INVOICE"]
    while issue_count(plan) > MAX_ISSUES:
        for key in order:
            if plan[key] > 0:
                plan[key] -= 1
                break
    return plan


def issue_count(plan: dict[str, int]) -> int:
    """Number of truth issues a plan produces (each scenario yields two)."""
    return sum(plan[t] for t in ERROR_TYPES) + 2 * plan["I1"] + 2 * plan["I2"]


def doc_need(plan: dict[str, int]) -> int:
    """Lower bound on world documents needed so every injector finds a candidate."""
    return (2 * (plan["PAYMENT_ALLOCATION"] + 1) + plan["FX_CONVERSION"] + 1
            + plan["DUPLICATE_INVOICE"] + 1 + 4 * (plan["I1"] + plan["I2"]))


def add_slots(w: World, rng: random.Random, ids: IdFactory, plan: dict[str, int]) -> None:
    """Pre-build the document pairs that interaction scenarios will corrupt."""
    for _ in range(plan["I1"]):
        cur = rng.choice(w.foreign)
        ent = rng.choice(w.entities_of("customer"))
        inv = add_invoice(w, rng, ids, direction="receivable", entity=ent, currency=cur,
                          moment=random_moment(w, rng, 1, w.last_day() - 2), kind="slot_i1")
        late = make_local(w.period_end, rng.randint(21, 23), rng.choice([5, 20, 35, 50]), w.tz)
        pay = add_payment(w, rng, ids, invs=[inv], amounts=[inv["total_minor"]], moment=late,
                          kind="slot_i1")
        w.slots["I1"].append((inv["invoice_id"], pay["payment_id"]))
    for _ in range(plan["I2"]):
        cur = rng.choice(w.foreign + [w.base])
        ent = rng.choice(w.entities_of("customer"))
        inv_m = random_moment(w, rng, 1, w.last_day() - 5)
        inv = add_invoice(w, rng, ids, direction="receivable", entity=ent, currency=cur,
                          moment=inv_m, kind="slot_i2")
        pay = add_payment(w, rng, ids, invs=[inv], amounts=[inv["total_minor"]],
                          moment=random_moment(w, rng, inv_m.day + 4, w.last_day()), kind="slot_i2")
        w.slots["I2"].append((inv["invoice_id"], pay["payment_id"]))


def _plain_invoice(w: World, rng: random.Random, ids: IdFactory, *, foreign: bool | None = None,
                   max_day: int | None = None) -> dict:
    direction = "receivable" if rng.random() < 0.6 else "payable"
    role = "customer" if direction == "receivable" else "supplier"
    if foreign is None:
        foreign = rng.random() < 0.55
    cur = rng.choice(w.foreign) if foreign else w.base
    return add_invoice(w, rng, ids, direction=direction, entity=rng.choice(w.entities_of(role)),
                       currency=cur, moment=random_moment(w, rng, 1, max_day or w.last_day()),
                       kind="plain")


def _pay_fully(w: World, rng: random.Random, ids: IdFactory, inv: dict) -> None:
    day = w.meta[inv["invoice_id"]]["moment"].day
    if day < w.last_day():
        add_payment(w, rng, ids, invs=[inv], amounts=[inv["total_minor"]],
                    moment=random_moment(w, rng, day + 1, w.last_day()), kind="plain")


def add_plain(w: World, rng: random.Random, ids: IdFactory, plan: dict[str, int],
              target_docs: int) -> None:
    """Add ordinary documents: guaranteed candidates first, then random ones up to target."""
    last = w.last_day()
    for _ in range(plan["PAYMENT_ALLOCATION"] + 1):
        _pay_fully(w, rng, ids, _plain_invoice(w, rng, ids, max_day=last - 1))
    for _ in range(plan["FX_CONVERSION"] + 1):
        inv = _plain_invoice(w, rng, ids, foreign=True)
        if rng.random() < 0.5:
            _pay_fully(w, rng, ids, inv)
    for _ in range(plan["DUPLICATE_INVOICE"] + 1):
        _plain_invoice(w, rng, ids, max_day=last - 3)
    while len(w.invoices) + len(w.payments) < target_docs:
        inv = _plain_invoice(w, rng, ids)
        if rng.random() < 0.6 and len(w.invoices) + len(w.payments) < target_docs:
            _pay_fully(w, rng, ids, inv)
