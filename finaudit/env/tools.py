"""Четыре инструмента расследования (submit обрабатывает core)."""
from __future__ import annotations

from finaudit.env.calculator import evaluate
from finaudit.env.errors import EnvError
from finaudit.env.store import TABLES, Store

PAGE_SIZE = 50
ALLOWED_KEYS = {
    "list_records": ({"action", "table"}, {"cursor", "limit"}),
    "get_record": ({"action", "table", "id"}, set()),
    "get_document": ({"action", "doc_id"}, set()),
    "calculator": ({"action", "expression"}, set()),
    "submit": ({"action", "findings"}, set()),
}


def check_keys(action: dict) -> str:
    """Возвращает имя действия после проверки его ключей (UNKNOWN_ACTION / BAD_ARGS)."""
    name = action.get("action")
    if not isinstance(name, str) or name not in ALLOWED_KEYS:
        raise EnvError("UNKNOWN_ACTION", "неизвестное действие")
    required, optional = ALLOWED_KEYS[name]
    keys = set(action)
    if not required <= keys or keys - required - optional:
        raise EnvError("BAD_ARGS", f"{name}: неверные аргументы")
    return name


def _table(value: object) -> str:
    if not isinstance(value, str):
        raise EnvError("BAD_ARGS", "table должен быть строкой")
    if value not in TABLES:
        raise EnvError("UNKNOWN_TABLE", "неизвестная таблица")
    return value


def _ident(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise EnvError("BAD_ARGS", f"{field} должен быть непустой строкой")
    return value


def list_records(store: Store, action: dict) -> dict:
    """Постраничный список в порядке файла."""
    table = _table(action["table"])
    limit = action.get("limit", PAGE_SIZE)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise EnvError("BAD_ARGS", "limit должен быть целым 1..50")
    if limit > PAGE_SIZE:
        raise EnvError("LIMIT_TOO_LARGE", "limit не может превышать 50")
    cursor = action.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise EnvError("BAD_ARGS", "cursor должен быть строкой или null")
    return store.page(table, cursor, limit)


def get_record(store: Store, action: dict) -> dict:
    """Одна запись по таблице и ID."""
    return store.get(_table(action["table"]), _ident(action["id"], "id"))


def get_document(store: Store, action: dict) -> dict:
    """Счёт или платёж по doc_id."""
    return store.document(_ident(action["doc_id"], "doc_id"))


def calculator(store: Store, action: dict) -> dict:
    """Десятичная арифметика."""
    return {"value": evaluate(action["expression"])}


HANDLERS = {"list_records": list_records, "get_record": get_record,
            "get_document": get_document, "calculator": calculator}
