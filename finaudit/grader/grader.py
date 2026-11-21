"""grade(truth, findings, public_ids, inspection_steps, tol) -> GradeResult."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from finaudit.grader.matcher import max_matching, normalize
from finaudit.grader.reward import INVALID_REWARD, metrics, terminal_reward
from finaudit.grader.validate_findings import validate_findings


@dataclass(frozen=True)
class GradeResult:
    """Outcome of grading one submission."""

    valid: bool
    reason: str | None
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    reward: float
    inspection_steps: int
    matches: tuple[tuple[int, str], ...]

    def to_dict(self) -> dict:
        """JSON form."""
        d = asdict(self)
        d["matches"] = [list(m) for m in self.matches]
        return d

    def agent_info(self) -> dict:
        """The train-mode info dict (section 4.4)."""
        return {"precision": self.precision, "recall": self.recall, "f1": self.f1, "tp": self.tp,
                "fp": self.fp, "fn": self.fn, "inspection_steps": self.inspection_steps}


def empty_findings(episode_id: str) -> dict:
    """The answer graded on truncation."""
    return {"episode_id": episode_id, "findings": []}


def grade(truth: dict, findings: object, public_ids: set[str] | frozenset[str],
          inspection_steps: int, tol: dict[str, int] | None = None) -> GradeResult:
    """Validate, match and score a submission against truth.

    ``tol`` is the per-type amount tolerance (``matcher.tolerances(policy)``); ``None`` means 0.
    """
    issues = truth["issues"]
    reason = validate_findings(findings, truth["episode_id"])
    if reason:
        return GradeResult(False, reason, 0, 0, len(issues), 0.0, 0.0, 0.0, INVALID_REWARD,
                           inspection_steps, ())
    normed = [normalize(f) for f in findings["findings"]]  # type: ignore[index]
    matches = max_matching(normed, issues, public_ids, tol)
    tp = len(matches)
    fp, fn = len(normed) - tp, len(issues) - tp
    p, r, f1 = metrics(tp, fp, fn, len(issues), len(normed))
    return GradeResult(True, None, tp, fp, fn, float(p), float(r), float(f1),
                       terminal_reward(f1, inspection_steps),
                       inspection_steps, tuple(matches))
