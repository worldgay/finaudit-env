"""Normalisation, admissible pairs and maximum bipartite matching (sections 5.2-5.4).

Conventions follow the organisers' check definitions (docs/CHECKS.md, "Точные соглашения matcher"):
strings (type, currency, every id) are compared exactly - no case folding, no trimming;
affected_ids and evidence_ids are sets; the amount tolerance is a fixed non-negative integer per
finding type published in policy.json (``amount_tolerance_minor``), 0 when absent.
"""
from __future__ import annotations

from dataclasses import dataclass

from finaudit.grader.validate_findings import FINDING_TYPES

DEFAULT_TOLERANCE = 0


@dataclass(frozen=True)
class NormFinding:
    """A finding after normalisation."""

    type: str
    affected_ids: tuple[str, ...]
    claimed: int
    currency: str
    evidence: frozenset[str]


def normalize(f: dict) -> NormFinding:
    """affected_ids / evidence_ids become sets of exact strings; nothing else changes."""
    return NormFinding(type=f["type"], affected_ids=tuple(sorted(set(f["affected_ids"]))),
                       claimed=f["claimed_amount_minor"], currency=f["currency"],
                       evidence=frozenset(f["evidence_ids"]))


def tolerances(policy: object) -> dict[str, int]:
    """Per-type tolerance from a policy document; anything missing or malformed counts as 0."""
    table = policy.get("amount_tolerance_minor") if isinstance(policy, dict) else None
    out = {t: DEFAULT_TOLERANCE for t in FINDING_TYPES}
    if isinstance(table, dict):
        for t, v in table.items():
            if isinstance(t, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                out[t] = v
    return out


def admissible(f: NormFinding, issue: dict, public_ids: set[str] | frozenset[str],
               tol: dict[str, int] | None = None) -> bool:
    """All conditions of section 5.3 hold for the pair (finding, issue)."""
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
    """Size of a maximum matching between ``findings`` and ``issues`` (augmenting paths)."""
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
    """Maximum one-to-one matching with the organisers' deterministic tie-break.

    Among all maximum matchings pick the lexicographically smallest sorted sequence of
    (issue_id, finding index) pairs, issue ids ordered by Unicode code points: issues are fixed in
    that order, each taking the smallest finding index that still allows a maximum matching.
    Returns (finding index, issue_id) pairs sorted by finding index.
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
