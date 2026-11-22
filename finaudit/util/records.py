"""Разбор и рендер форматов открытых таблиц (общий код, только stdlib)."""
from __future__ import annotations

import csv
import io
import json

from finaudit.util.canon import dumps

LEDGER_COLUMNS = ["row_id", "timestamp", "account", "debit_minor", "credit_minor",
                  "currency", "entity_id", "invoice_id", "payment_id"]
FX_COLUMNS = ["date", "source_currency", "target_currency", "rate"]
_INT_COLUMNS = {"debit_minor", "credit_minor"}


def render_csv(columns: list[str], rows: list[dict]) -> str:
    """Рендерит строки как CSV; ``None`` становится пустой ячейкой."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in columns])
    return buf.getvalue()


def render_jsonl(rows: list[dict]) -> str:
    """Рендерит строки как канонические JSON-строки."""
    return "".join(dumps(r) + "\n" for r in rows)


def parse_ledger(text: str) -> list[dict]:
    """Разбирает ledger.csv: пустая ячейка -> None, денежные столбцы -> int."""
    out = []
    for raw in csv.DictReader(io.StringIO(text)):
        row: dict = {}
        for col in LEDGER_COLUMNS:
            val = raw[col]
            if val == "":
                row[col] = None
            elif col in _INT_COLUMNS:
                row[col] = int(val)
            else:
                row[col] = val
        out.append(row)
    return out


def parse_fx(text: str) -> list[dict]:
    """Разбирает строки fx.csv (курс остаётся десятичной строкой)."""
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def fx_id(row: dict) -> str:
    """Возвращает открытый идентификатор строки fx: ``fx:YYYY-MM-DD:SRC:TGT``."""
    return f"fx:{row['date']}:{row['source_currency']}:{row['target_currency']}"


def parse_jsonl(text: str) -> list[dict]:
    """Разбирает JSON-строки."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]
