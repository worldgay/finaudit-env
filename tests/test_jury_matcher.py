"""The organisers' matcher/reward block (docs/CHECKS.txt): tests 1-20 and open examples M01-M12.

Fixture: one issue A of a supported type T, canonical affected record R1, 10000 KZT minor units,
one admissible evidence set {D1, D2}; tolerance 0 unless stated; inspection_steps 10 by default.
Real results are compared with an absolute error of 1e-9, as the definitions require.
"""
from fractions import Fraction

import pytest

from finaudit.grader.grader import grade
from finaudit.grader.matcher import max_matching, normalize, tolerances

T, OTHER_T = "DUPLICATE_INVOICE", "PERIOD_CUTOFF"
TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")
IDS = frozenset({"R1", "R2", "R3", "R4", "R5", "D1", "D2", "D3"})
EID = "ep-fixture"
EPS = 1e-9


def issue(iid="A", affected=("R1",), amount=10000, cur="KZT", typ=T):
    return {"issue_id": iid, "type": typ, "affected_ids": sorted(affected), "expected_amount_minor": amount,
            "currency": cur, "evidence_sets": [["D1", "D2"]], "scenario": None}


def F(affected=("R1",), amount=10000, cur="KZT", ev=("D1", "D2"), typ=T, explanation="short reason"):
    return {"type": typ, "affected_ids": list(affected), "claimed_amount_minor": amount, "currency": cur,
            "evidence_ids": list(ev), "explanation": explanation}


def run(issues, findings, steps=10, tau=0):
    tol = tolerances({"amount_tolerance_minor": {t: tau for t in TYPES}})
    return grade({"episode_id": EID, "issues": issues}, {"episode_id": EID, "findings": findings},
                 IDS, steps, tol)


def check(res, tp, fp, fn, p, r, f1, reward):
    assert (res.tp, res.fp, res.fn) == (tp, fp, fn)
    for got, want in ((res.precision, p), (res.recall, r), (res.f1, f1), (res.reward, reward)):
        assert abs(got - float(Fraction(want))) <= EPS, (got, want)


def test_01_one_correct():
    check(run([issue()], [F()]), 1, 0, 0, 1, 1, 1, Fraction(98, 100))


def test_02_empty_answer_on_errors():
    check(run([issue()], []), 0, 0, 1, 0, 0, 0, -1)


def test_03_empty_truth_empty_answer():
    check(run([], []), 0, 0, 0, 0, 0, 1, Fraction(98, 100))


def test_04_false_accusation_on_clean():
    check(run([], [F()]), 0, 1, 0, 0, 0, 0, -1)


def test_05_two_identical_correct():
    check(run([issue()], [F(), F()]), 1, 1, 0, Fraction(1, 2), 1, Fraction(2, 3), Fraction(47, 150))
    assert run([issue()], [F(), F()]).reward <= run([issue()], [F()]).reward


@pytest.mark.parametrize("finding", [
    F(typ=OTHER_T),                      # 06 wrong type
    F(affected=("R2",)),                 # 07 other existing, unaffected record
    F(amount=10001),                     # 08 amount off with tolerance 0
    F(cur="USD"),                        # 09 other currency
    F(ev=("D1",)),                       # 10 incomplete evidence set
    F(ev=("D1", "U-404")),               # 11 missing evidence id instead of D2
], ids=["06", "07", "08", "09", "10", "11"])
def test_06_to_11_wrong_field(finding):
    check(run([issue()], [finding]), 0, 1, 1, 0, 0, 0, -1)


def test_12_flag_everything():
    findings = [F(affected=(r,), typ=t) for r in ("R1", "R2", "R3", "R4", "R5") for t in TYPES]
    assert len(findings) == 20
    check(run([issue()], findings), 1, 19, 0, Fraction(1, 20), 1, Fraction(2, 21), Fraction(-871, 1050))


def test_13_one_of_two():
    issues = [issue("A"), issue("B", affected=("R2",))]
    check(run(issues, [F()]), 1, 0, 1, 1, Fraction(1, 2), Fraction(2, 3), Fraction(47, 150))


def test_14_one_right_one_false():
    issues = [issue("A"), issue("B", affected=("R2",))]
    check(run(issues, [F(), F(affected=("R3",))]), 1, 1, 1, Fraction(1, 2), Fraction(1, 2), Fraction(1, 2),
          Fraction(-2, 100))


@pytest.mark.parametrize("steps,reward", [(0, 1), (50, Fraction(90, 100)), (100, Fraction(80, 100))],
                         ids=["15", "16", "17"])
def test_15_to_17_step_cost(steps, reward):
    check(run([issue()], [F()], steps=steps), 1, 0, 0, 1, 1, 1, reward)
    assert abs(run([issue()], [F()], steps=10).reward - run([issue()], [F()], steps=50).reward - 0.08) <= EPS


@pytest.mark.parametrize("findings", [
    [F()] * 31,                                                   # 18 more than 30 findings
    [F(ev=tuple(f"D{i}" for i in range(11)))],                    # 19 eleven distinct evidence ids
    [F(explanation="x" * 1001)],                                  # 20 1001 ASCII characters
], ids=["18", "19", "20"])
def test_18_to_20_structure_limits(findings):
    res = run([issue()], findings)
    assert not res.valid and res.reward == -1.0


def test_explanation_limit_counts_code_points():
    assert run([issue()], [F(explanation="ж" * 1000)]).valid
    assert not run([issue()], [F(explanation="ж" * 1001)]).valid


# ---------------------------------------------------------------- open examples M01-M12
def m_issue(iid="A", amount=10000):
    return issue(iid, affected=("R1", "R2"), amount=amount)


def M(**kw):
    return F(**{"affected": ("R1", "R2"), **kw})


def test_m01_repeated_affected_id_is_a_set():
    assert run([m_issue()], [M(affected=("R2", "R1", "R1"))]).tp == 1


def test_m02_extra_unaffected_id():
    res = run([m_issue()], [M(affected=("R1", "R2", "R3"))])
    assert (res.fp, res.fn) == (1, 1)


def test_m03_superset_of_existing_evidence():
    assert run([m_issue()], [M(ev=("D2", "D1", "D3"))]).tp == 1


def test_m04_unknown_evidence_id():
    res = run([m_issue()], [M(ev=("D1", "D2", "U"))])
    assert (res.tp, res.fp, res.fn) == (0, 1, 1)


def test_m05_limit_checked_before_dedup():
    res = run([m_issue()], [M(ev=("D1",) * 10 + ("D2",))])
    assert not res.valid and res.reward == -1.0


@pytest.mark.parametrize("cur", ["kzt", "KZT ", " KZT"])
def test_m06_currency_compared_exactly(cur):
    res = run([m_issue()], [M(cur=cur)])
    assert res.valid and (res.tp, res.fp, res.fn) == (0, 1, 1)


def test_m07_amount_off_by_one_with_zero_tolerance():
    res = run([m_issue()], [M(amount=10001)])
    assert (res.fp, res.fn) == (1, 1)


def test_m08_published_tolerance_one_is_inclusive():
    assert run([m_issue()], [M(amount=10001)], tau=1).tp == 1
    assert run([m_issue()], [M(amount=9999)], tau=1).tp == 1
    assert run([m_issue()], [M(amount=10002)], tau=1).tp == 0


@pytest.mark.parametrize("amount", ["10000", True, 10000.0])
def test_m09_amount_must_be_json_integer(amount):
    res = run([m_issue()], [M(amount=amount)])
    assert not res.valid and res.reward == -1.0


def test_m10_maximum_not_greedy():
    a, b = m_issue("A", 10000), m_issue("B", 10002)
    findings = [M(amount=10001), M(amount=10000)]  # F0 fits A and B (tau=1), F1 fits only A
    res = run([a, b], findings, tau=1)
    assert (res.tp, res.fp, res.fn) == (2, 0, 0)
    assert sorted(res.matches) == [(0, "B"), (1, "A")]


def test_m11_deterministic_tie_break():
    a, b = m_issue("A"), m_issue("B")
    res = run([b, a], [M(), M()])
    assert res.tp == 2 and list(res.matches) == [(0, "A"), (1, "B")]
    pairs = max_matching([normalize(M()), normalize(M())], [a, b], IDS)
    assert pairs == [(0, "A"), (1, "B")]


def test_m12_identical_findings_not_merged():
    res = run([m_issue()], [M(), M()])
    assert (res.tp, res.fp, res.fn) == (1, 1, 0)
    assert abs(res.reward - run([issue()], [F(), F()]).reward) <= EPS


def test_finding_order_never_changes_scores():
    issues = [m_issue("A"), m_issue("B", 10002), issue("C", affected=("R3",))]
    findings = [M(amount=10001), M(), F(affected=("R3",)), F(affected=("R4",)), M(amount=10002)]
    base = run(issues, findings, tau=1)
    for shift in range(1, len(findings)):
        res = run(issues, findings[shift:] + findings[:shift], tau=1)
        assert (res.tp, res.fp, res.fn, res.reward) == (base.tp, base.fp, base.fn, base.reward)
