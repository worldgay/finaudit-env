"""Хранилище открытых записей только для чтения, с пагинацией и индексами."""
from __future__ import annotations

import base64
import json

from finaudit.env.errors import EnvError
from finaudit.util.canon import dumps
from finaudit.util.records import fx_id

TABLES = ("ledger", "invoices", "payments", "fx")
ID_FIELD = {"ledger": "row_id", "invoices": "doc_id", "payments": "doc_id", "fx": "fx_id"}


def _copy(obj: object) -> object:
    """Глубокая копия через JSON, чтобы агенты никогда не могли изменить хранилище."""
    return json.loads(dumps(obj))


def encode_cursor(table: str, offset: int) -> str:
    """Непрозрачный стабильный курсор: base64url от {"t": table, "o": offset}."""
    raw = dumps({"o": offset, "t": table}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, table: str, size: int) -> int:
    """Проверяет курсор и возвращает его смещение (иначе BAD_CURSOR)."""
    try:
        pad = "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(cursor + pad).decode("utf-8"))
        offset = data["o"]
        ok = (set(data) == {"o", "t"} and data["t"] == table and isinstance(offset, int)
              and not isinstance(offset, bool) and 0 <= offset < size
              and encode_cursor(table, offset) == cursor)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError, RecursionError):
        ok = False
    if not ok:
        raise EnvError("BAD_CURSOR", "курсор не подходит для этой таблицы")
    return offset


class Store:
    """Открытые записи в порядке файла плюс индексы по ID."""

    def __init__(self, public: dict) -> None:
        fx_rows = [{**r, "fx_id": fx_id(r)} for r in public["fx"]]
        self.tables: dict[str, list[dict]] = {"ledger": public["ledger"], "invoices": public["invoices"],
                                              "payments": public["payments"], "fx": fx_rows}
        self.index = {t: {r[ID_FIELD[t]]: r for r in rows} for t, rows in self.tables.items()}
        self.documents = {**{d["doc_id"]: ("invoice", d) for d in public["invoices"]},
                          **{d["doc_id"]: ("payment", d) for d in public["payments"]}}
        self.ids = frozenset().union(*[set(ix) for ix in self.index.values()])
        # удобные псевдонимы: invoice_id / payment_id и fx-ID без префикса "fx:"
        self.alias = {"invoices": {d["invoice_id"]: d for d in public["invoices"]},
                      "payments": {d["payment_id"]: d for d in public["payments"]},
                      "fx": {r["fx_id"][3:]: r for r in fx_rows}, "ledger": {}}

    def page(self, table: str, cursor: str | None, limit: int) -> dict:
        """Одна страница ``table``, начиная с ``cursor``."""
        rows = self.tables[table]
        offset = 0 if cursor is None else decode_cursor(cursor, table, len(rows))
        end = min(len(rows), offset + limit)
        nxt = encode_cursor(table, end) if end < len(rows) else None
        return {"table": table, "records": _copy(rows[offset:end]), "next_cursor": nxt}

    def get(self, table: str, ident: str) -> dict:
        """Одна запись по её ID."""
        rec = self.index[table].get(ident) or self.alias[table].get(ident)
        if rec is None:
            raise EnvError("NOT_FOUND", "нет записи с таким id")
        return {"table": table, "record": _copy(rec)}

    def document(self, doc_id: str) -> dict:
        """Счёт или платёж по doc_id."""
        hit = self.documents.get(doc_id)
        if hit is None:
            raise EnvError("NOT_FOUND", "нет документа с таким id")
        return {"doc_type": hit[0], "document": _copy(hit[1])}
