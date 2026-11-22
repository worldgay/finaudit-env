"""Нормализация, допустимые пары и максимальное паросочетание в двудольном графе (разделы 5.2-5.4).

Соглашения следуют определениям проверок организаторов (docs/CHECKS.txt, "Точные соглашения matcher"):
строки (type, currency, каждый ID) сравниваются точно — без приведения регистра и обрезки пробелов;
affected_ids и evidence_ids — множества; допуск суммы — фиксированное неотрицательное целое для
каждого типа вывода, опубликованное в policy.json (``amount_tolerance_minor``), 0 при отсутствии.
"""
from __future__ import annotations

from dataclasses import dataclass

from finaudit.grader.validate_findings import FINDING_TYPES

DEFAULT_TOLERANCE = 0


@dataclass(frozen=True)
class NormFinding:
    """Вывод после нормализации."""

    type: str
    affected_ids: tuple[str, ...]
    claimed: int
    currency: str
    evidence: frozenset[str]


def normalize(f: dict) -> NormFinding:
    """affected_ids / evidence_ids становятся множествами точных строк; больше ничего не меняется."""
    return NormFinding(type=f["type"], affected_ids=tuple(sorted(set(f["affected_ids"]))),
                       claimed=f["claimed_amount_minor"], currency=f["currency"],
                       evidence=frozenset(f["evidence_ids"]))


def tolerances(policy: object) -> dict[str, int]:
    """Допуск по типам из документа policy; всё отсутствующее или некорректное считается 0."""
    table = policy.get("amount_tolerance_minor") if isinstance(policy, dict) else None
    out = {t: DEFAULT_TOLERANCE for t in FINDING_TYPES}
    if isinstance(table, dict):
        for t, v in table.items():
            if isinstance(t, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out[t] = v
    return out


def admissible(f: NormFinding, issue: dict, public_ids: set[str] | frozenset[str],
               tol: dict[str, int] | None = None) -> bool:
    """Для пары (вывод, ошибка) выполняются все условия раздела 5.3."""
    if f.type != issue["type"] or set(f.affected_ids) != set(issue["affected_ids"]):
        return False
    if f.currency != issue["currency"]:
        return False
    tau = (tol or {}).get(issue["type"], DEFAULT_TOLERANCE)
    if abs(f.claimed - issue["expected_amount_minor"]) > tau:
        return False
    if not f.evidence <= public_ids:
        return False
    return any(set(ev) <= f.evidence for ev in issue["evidence_sets"])


def _kuhn(adj: list[list[int]], findings: list[int], issues: set[int]) -> int:
    """Размер максимального паросочетания между ``findings`` и ``issues`` (увеличивающие пути)."""
    owner: dict[int, int] = {}

    def augment(fi: int, seen: set[int]) -> bool:
        for k in adj[fi]:
            if k not in issues or k in seen:
                continue
            seen.add(k)
            if k not in owner or augment(owner[k], seen):
                owner[k] = fi
                return True
        return False

    return sum(augment(fi, set()) for fi in findings)


def max_matching(findings: list[NormFinding], issues: list[dict],
                 public_ids: set[str] | frozenset[str],
                 tol: dict[str, int] | None = None) -> list[tuple[int, str]]:
    """Максимальное взаимно однозначное паросочетание с детерминированным выбором организаторов.

    Среди всех максимальных паросочетаний выбирается лексикографически наименьшая отсортированная
    последовательность пар (issue_id, индекс вывода), ID ошибок упорядочены по Unicode code points: ошибки
    фиксируются в этом порядке, каждая берёт наименьший индекс вывода, при котором паросочетание ещё максимально.
    Возвращает пары (индекс вывода, issue_id), отсортированные по индексу вывода.
    """
    ordered = sorted(issues, key=lambda i: i["issue_id"])
    adj = [[k for k, iss in enumerate(ordered) if admissible(f, iss, public_ids, tol)] for f in findings]
    free = list(range(len(findings)))
    need = _kuhn(adj, free, set(range(len(ordered))))
    pairs: list[tuple[int, str]] = []
    for k in range(len(ordered)):
        if need == 0:
            break
        rest = set(range(k + 1, len(ordered)))
        for fi in free:
            if k in adj[fi] and 1 + _kuhn(adj, [g for g in free if g != fi], rest) == need:
                pairs.append((fi, ordered[k]["issue_id"]))
                free.remove(fi)
                need -= 1
                break
    return sorted(pairs)
