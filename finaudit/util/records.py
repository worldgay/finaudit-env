"""Parsing and rendering of the public table formats (shared, stdlib only)."""
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
    """Render rows as CSV; ``None`` becomes an empty cell."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in columns])
    return buf.getvalue()


def render_jsonl(rows: list[dict]) -> str:
    """Render rows as canonical JSON lines."""
    return "".join(dumps(r) + "\n" for r in rows)


def parse_ledger(text: str) -> list[dict]:
    """Parse ledger.csv: empty cell -> None, money columns -> int."""
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
    """Parse fx.csv rows (rate stays a decimal string)."""
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def fx_id(row: dict) -> str:
    """Return the public identifier of an fx row: ``fx:YYYY-MM-DD:SRC:TGT``."""
    return f"fx:{row['date']}:{row['source_currency']}:{row['target_currency']}"


def parse_jsonl(text: str) -> list[dict]:
    """Parse JSON lines."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]
