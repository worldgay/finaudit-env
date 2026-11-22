"""Скрытая история: компания, контрагенты, сделки, счета, платежи, курсы FX."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from finaudit.util.ids import IdFactory
from finaudit.util.leak import text_has_hint
from finaudit.util.money import CURRENCY_EXPONENT
from finaudit.util.timeutil import days_in_month, make_local, render_ts

TZ_POOL = ["Asia/Almaty", "Asia/Tokyo", "Europe/Berlin", "Europe/London", "America/New_York", "UTC"]
BASE_POOL = ["KZT", "USD", "EUR"]
ANCHOR = {"KZT": Decimal("1"), "USD": Decimal("500"), "EUR": Decimal("545"),
          "GBP": Decimal("635"), "JPY": Decimal("3.3")}
MAJOR_RANGE = {"KZT": (20000, 3000000), "USD": (50, 8000), "EUR": (50, 8000),
               "GBP": (50, 6000), "JPY": (5000, 1000000)}
SYLLABLES = ["vel", "tra", "no", "ka", "mir", "zen", "lo", "ber", "sa", "ten", "qua", "ri",
             "mo", "dal", "vik", "ora", "pel", "tan", "zor", "lin", "gra", "fen", "hol", "bri"]
SUFFIXES = ["LLP", "Ltd", "GmbH", "Corp", "Trading", "Group", "Holdings", "Industrial LLP"]
SERVICES = ["Consulting hours", "Equipment rental", "Software subscription", "Freight forwarding",
            "Warehouse storage", "Technical maintenance", "Marketing services", "Office supplies",
            "Cleaning services", "Data hosting", "Spare parts", "Training session",
            "Legal advisory", "Packaging materials", "Security services", "Courier delivery"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class World:
    """Скрытая истинная история одной компании за один месяц."""

    company_name: str
    base: str
    foreign: list[str]
    tz: str
    period_start: date
    period_end: date
    fx: dict[tuple[str, str], str]
    entities: list[dict]
    invoices: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    meta: dict[str, dict] = field(default_factory=dict)
    journals: list[dict] = field(default_factory=list)
    distractors: list[str] = field(default_factory=list)
    slots: dict[str, list] = field(default_factory=lambda: {"I1": [], "I2": []})

    def exp(self, currency: str) -> int:
        """Экспонента минимальных единиц валюты."""
        return CURRENCY_EXPONENT[currency]

    def rate(self, currency: str, day: date) -> str:
        """Курс policy валюта->база для местной календарной даты ("1" для базы)."""
        if currency == self.base:
            return "1"
        return self.fx[(day.isoformat(), currency)]

    def ratio(self, currency: str, day: date) -> Decimal:
        """Минимальных единиц базы на одну минимальную единицу источника на ``day``."""
        exp_diff = self.exp(self.base) - self.exp(currency)
        return Decimal(self.rate(currency, day)) * (Decimal(10) ** exp_diff)

    def last_day(self) -> int:
        """Номер последнего дня периода."""
        return self.period_end.day

    def entities_of(self, role: str) -> list[dict]:
        """Контрагенты в роли ``role`` (customer / supplier)."""
        return [e for e in self.entities if e["role"] == role]


def company_name(rng: random.Random) -> str:
    """Вымышленное название компании, собранное из слогов."""
    while True:
        stem = "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3)))
        name = f"{stem.capitalize()} {rng.choice(SUFFIXES)}"
        if not text_has_hint(name):
            return name


def make_fx(rng: random.Random, base: str, foreign: list[str], start: date, end: date) -> dict:
    """Ежедневное случайное блуждание курса для каждой иностранной валюты, 6 знаков, без ровных участков."""
    out: dict[tuple[str, str], str] = {}
    q = Decimal("0.000001")
    for cur in foreign:
        level = ANCHOR[cur] / ANCHOR[base] * Decimal(rng.randint(950, 1050)) / Decimal(1000)
        prev = None
        day = start
        while day <= end:
            step = Decimal(rng.randint(-120, 120)) / Decimal(10000)
            level = level * (Decimal(1) + step)
            val = level.quantize(q)
            if prev is not None and val == prev:
                val = prev + q
            out[(day.isoformat(), cur)] = str(val)
            prev = val
            day += timedelta(days=1)
    return out


def new_world(rng: random.Random, cfg: dict, ids: IdFactory) -> World:
    """Создаёт компанию, период, таблицу FX и контрагентов."""
    base = cfg.get("base_currency") or rng.choice(BASE_POOL)
    pool = [c for c in cfg["foreign_currencies"] if c != base]
    foreign = sorted(rng.sample(pool, rng.randint(1, min(3, len(pool)))))
    tz = cfg.get("timezone") or rng.choice(TZ_POOL)
    year, month = rng.choice([2025, 2026]), rng.randint(1, 12)
    start = date(year, month, 1)
    end = date(year, month, days_in_month(year, month))
    fx = make_fx(rng, base, foreign, start - timedelta(days=7), end + timedelta(days=7))
    n_ent = rng.randint(6, 30)
    entities = []
    for i in range(n_ent):
        role = "customer" if i % 2 == 0 else "supplier"
        entities.append({"entity_id": ids.new("E", 4), "name": company_name(rng), "role": role})
    return World(company_name(rng), base, foreign, tz, start, end, fx, entities)


def random_moment(w: World, rng: random.Random, day_lo: int, day_hi: int,
                  hour_lo: int = 8, hour_hi: int = 20) -> datetime:
    """Случайный момент рабочего времени в день периода (с 1)."""
    day = w.period_start + timedelta(days=rng.randint(day_lo, day_hi) - 1)
    return make_local(day, rng.randint(hour_lo, hour_hi), rng.choice([0, 10, 15, 20, 30, 40, 45, 50]),
                      w.tz)


def stamp(rng: random.Random, moment: datetime) -> str:
    """Рендерит момент: ~35% документов записаны в +00:00."""
    return render_ts(moment, utc=rng.random() < 0.35)


def random_total_major(rng: random.Random, currency: str) -> int:
    """Случайный размер счёта в основных единицах валюты."""
    lo, hi = MAJOR_RANGE[currency]
    return rng.randint(lo, hi)


def random_items(w: World, rng: random.Random, currency: str, label: str | None = None,
                 n_items: int | None = None) -> list[dict]:
    """Случайные позиции счёта; ``label`` (период услуги) добавляется к описаниям."""
    scale = 10 ** w.exp(currency)
    n = n_items or rng.randint(1, 3)
    month_label = f"{MONTHS[w.period_start.month - 1]} {w.period_start.year}"
    items = []
    for service in rng.sample(SERVICES, n):
        qty = rng.randint(1, 12)
        unit = max(1, random_total_major(rng, currency) // (qty * n)) * scale
        unit += rng.randint(0, scale - 1) if scale > 1 else 0
        tag = label or rng.choice([month_label, f"order {rng.randint(1000, 9999)}",
                                   f"batch {rng.randint(10, 99)}"])
        items.append({"description": f"{service}, {tag}", "quantity": qty,
                      "unit_price_minor": unit, "amount_minor": qty * unit})
    return items


def add_invoice(w: World, rng: random.Random, ids: IdFactory, *, direction: str, entity: dict,
                currency: str, moment: datetime, kind: str, items: list[dict] | None = None,
                posted: bool = True) -> dict:
    """Создаёт и регистрирует счёт."""
    items = items if items is not None else random_items(w, rng, currency)
    inv = {"doc_id": ids.new("D"), "invoice_id": ids.new("INV"), "entity_id": entity["entity_id"],
           "direction": direction, "issued_at": stamp(rng, moment),
           "due_at": stamp(rng, moment + timedelta(days=30)), "currency": currency,
           "total_minor": sum(i["amount_minor"] for i in items), "line_items": items}
    w.invoices.append(inv)
    w.meta[inv["invoice_id"]] = {"kind": kind, "moment": moment, "posted": posted}
    return inv


def add_payment(w: World, rng: random.Random, ids: IdFactory, *, invs: list[dict],
                amounts: list[int], moment: datetime, kind: str) -> dict:
    """Создаёт и регистрирует платёж, распределённый на ``invs`` суммами ``amounts``."""
    first = invs[0]
    direction = "incoming" if first["direction"] == "receivable" else "outgoing"
    pay = {"doc_id": ids.new("D"), "payment_id": ids.new("PAY"), "timestamp": stamp(rng, moment),
           "currency": first["currency"], "amount_minor": sum(amounts),
           "entity_id": first["entity_id"], "direction": direction,
           "invoice_refs": [{"invoice_id": i["invoice_id"], "amount_minor": a}
                            for i, a in zip(invs, amounts)]}
    w.payments.append(pay)
    w.meta[pay["payment_id"]] = {"kind": kind, "moment": moment}
    return pay
