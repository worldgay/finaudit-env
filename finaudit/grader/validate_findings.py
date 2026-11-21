"""Structural validation of the submitted findings object (section 5.1)."""
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
        return "finding is not an object"
    if set(f) != FINDING_KEYS:
        return "finding keys mismatch"
    if not isinstance(f["type"], str):  # an unknown type string is a valid finding that never matches
        return "bad type"
    if not _str_list(f["affected_ids"], allow_empty=False, limit=MAX_IDS):
        return "bad affected_ids"
    amount = f["claimed_amount_minor"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        return "bad claimed_amount_minor"
    if not isinstance(f["currency"], str):  # compared exactly with truth by the matcher
        return "bad currency"
    if not _str_list(f["evidence_ids"], allow_empty=True, limit=MAX_EVIDENCE):
        return "bad evidence_ids"
    if not isinstance(f["explanation"], str) or len(f["explanation"]) > MAX_EXPLANATION:
        return "bad explanation"
    return None


def validate_findings(obj: object, episode_id: str) -> str | None:
    """Return a short reason when ``obj`` is structurally invalid, else ``None``."""
    if not isinstance(obj, dict):
        return "findings payload is not an object"
    if set(obj) != {"episode_id", "findings"}:
        return "payload keys mismatch"
    if obj["episode_id"] != episode_id:
        return "episode_id mismatch"
    items = obj["findings"]
    if not isinstance(items, list):
        return "findings is not a list"
    if len(items) > MAX_FINDINGS:
        return "too many findings"
    for f in items:
        problem = _finding_problem(f)
        if problem:
            return problem
    return None
