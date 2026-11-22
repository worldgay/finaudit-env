"""Структурная проверка отправленного объекта findings (раздел 5.1)."""
from __future__ import annotations

FINDING_TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")
FINDING_KEYS = frozenset({"type", "affected_ids", "claimed_amount_minor", "currency",
                          "evidence_ids", "explanation"})
MAX_FINDINGS, MAX_IDS, MAX_EVIDENCE, MAX_EXPLANATION = 30, 10, 10, 1000


def _str_list(value: object, allow_empty: bool, limit: int) -> bool:
    return (isinstance(value, list) and (allow_empty or len(value) > 0) and len(value) <= limit
            and all(isinstance(v, str) for v in value))


def _finding_problem(f: object) -> str | None:
    if not isinstance(f, dict):
        return "вывод не является объектом"
    if set(f) != FINDING_KEYS:
        return "ключи вывода не совпадают"
    if not isinstance(f["type"], str):  # неизвестная строка типа — валидный вывод, который никогда не сопоставляется
        return "некорректный type"
    if not _str_list(f["affected_ids"], allow_empty=False, limit=MAX_IDS):
        return "некорректный affected_ids"
    amount = f["claimed_amount_minor"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        return "некорректный claimed_amount_minor"
    if not isinstance(f["currency"], str):  # matcher сравнивает точно с truth
        return "некорректный currency"
    if not _str_list(f["evidence_ids"], allow_empty=True, limit=MAX_EVIDENCE):
        return "некорректный evidence_ids"
    if not isinstance(f["explanation"], str) or len(f["explanation"]) > MAX_EXPLANATION:
        return "некорректный explanation"
    return None


def validate_findings(obj: object, episode_id: str) -> str | None:
    """Возвращает короткую причину, если ``obj`` структурно невалиден, иначе ``None``."""
    if not isinstance(obj, dict):
        return "объект findings не является объектом"
    if set(obj) != {"episode_id", "findings"}:
        return "ключи объекта findings не совпадают"
    if obj["episode_id"] != episode_id:
        return "episode_id не совпадает"
    items = obj["findings"]
    if not isinstance(items, list):
        return "findings не является списком"
    if len(items) > MAX_FINDINGS:
        return "слишком много выводов"
    for f in items:
        problem = _finding_problem(f)
        if problem:
            return problem
    return None
