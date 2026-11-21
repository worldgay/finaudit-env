"""Precision, recall, F1 and the terminal reward (section 5.5)."""
from __future__ import annotations

from fractions import Fraction

INVALID_REWARD = -1.0
STEP_COST = Fraction(2, 1000)


def metrics(tp: int, fp: int, fn: int, n_issues: int, n_findings: int) -> tuple[Fraction, Fraction, Fraction]:
    """Return exact (precision, recall, F1); empty truth + empty answer -> F1 = 1."""
    precision = Fraction(tp, tp + fp) if tp + fp else Fraction(0)
    recall = Fraction(tp, tp + fn) if tp + fn else Fraction(0)
    if n_issues == 0:
        f1 = Fraction(1) if n_findings == 0 else Fraction(0)
    else:
        f1 = Fraction(2 * tp, 2 * tp + fp + fn)
    return precision, recall, f1


def terminal_reward(f1: Fraction, inspection_steps: int) -> float:
    """clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1), computed exactly, then one float conversion."""
    value = 2 * f1 - 1 - STEP_COST * inspection_steps
    value = max(Fraction(-1), min(Fraction(1), value))
    return float(value)
