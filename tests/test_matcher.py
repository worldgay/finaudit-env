from finaudit.grader.grader import grade
from finaudit.grader.matcher import admissible, max_matching, normalize, tolerances

IDS = {"D-1", "D-2", "L-1", "L-2", "fx:2026-10-01:USD:KZT", "D-3", "L-3"}


def issue(iid, typ="DUPLICATE_INVOICE", affected=("INV-A", "INV-B"), amount=100000, cur="USD",
          ev=(("D-1", "D-2"), ("L-1", "L-2"))):
    return {"issue_id": iid, "type": typ, "affected_ids": sorted(affected), "expected_amount_minor": amount,
            "currency": cur, "evidence_sets": [list(e) for e in ev], "scenario": None}


def f(typ="DUPLICATE_INVOICE", affected=("INV-A", "INV-B"), amount=100000, cur="USD", ev=("D-1", "D-2")):
    return {"type": typ, "affected_ids": list(affected), "claimed_amount_minor": amount, "currency": cur,
            "evidence_ids": list(ev), "explanation": ""}


def truth(*issues):
    return {"episode_id": "ep-x", "issues": list(issues)}


def score(issues, findings, tol=None):
    return grade(truth(*issues), {"episode_id": "ep-x", "findings": findings}, IDS, 0, tol)


def test_normalization_is_exact():
    n = normalize(f(affected=("INV-B", "INV-A", "INV-A"), ev=("D-2", "D-1", "D-1")))
    assert n.affected_ids == ("INV-A", "INV-B") and n.evidence == frozenset({"D-1", "D-2"})
    assert admissible(n, issue("i1"), IDS)
    for bad in (f(typ="duplicate_invoice"), f(cur="usd"), f(cur=" USD"), f(affected=(" INV-B", "INV-A")),
                f(ev=(" D-1", "D-2"))):
        assert not admissible(normalize(bad), issue("i1"), IDS), bad


def test_id_case_is_preserved():
    assert not admissible(normalize(f(affected=("inv-a", "INV-B"))), issue("i1"), IDS)


def test_affected_permutation():
    assert score([issue("i1")], [f(affected=("INV-B", "INV-A"))]).tp == 1


def test_tolerance_default_zero():
    base = 100000
    for delta, tp in ((0, 1), (1, 0), (-1, 0), (100, 0)):
        assert score([issue("i1", amount=base)], [f(amount=base + delta)]).tp == tp, delta


def test_tolerance_published_per_type():
    tol = tolerances({"amount_tolerance_minor": {"DUPLICATE_INVOICE": 100}})
    assert tol == {"DUPLICATE_INVOICE": 100, "PAYMENT_ALLOCATION": 0, "FX_CONVERSION": 0, "PERIOD_CUTOFF": 0}
    for delta, tp in ((100, 1), (-100, 1), (101, 0), (-101, 0), (0, 1)):
        assert score([issue("i1", amount=100000)], [f(amount=100000 + delta)], tol).tp == tp, delta
    fx = issue("i1", typ="FX_CONVERSION")
    assert score([fx], [f(typ="FX_CONVERSION", amount=100001)], tol).tp == 0


def test_tolerance_malformed_counts_as_zero():
    for policy in (None, {}, {"amount_tolerance_minor": {"DUPLICATE_INVOICE": -1}},
                   {"amount_tolerance_minor": {"DUPLICATE_INVOICE": True}},
                   {"amount_tolerance_minor": {"DUPLICATE_INVOICE": "5"}}, {"amount_tolerance_minor": [1]}):
        assert tolerances(policy)["DUPLICATE_INVOICE"] == 0, policy


def test_alternative_evidence_set_suffices():
    assert score([issue("i1")], [f(ev=("L-2", "L-1"))]).tp == 1
    assert score([issue("i1")], [f(ev=("L-2", "D-1"))]).tp == 0


def test_superset_evidence_ok_but_unknown_id_fails():
    assert score([issue("i1")], [f(ev=("D-1", "D-2", "L-3"))]).tp == 1
    assert score([issue("i1")], [f(ev=("D-1", "D-2", "D-404"))]).tp == 0


def test_maximum_not_greedy_matching():
    # f0 подходит обеим ошибкам; f1 подходит только i1. Жадный f0->i1 оставил бы f1 без пары.
    tol = tolerances({"amount_tolerance_minor": {"DUPLICATE_INVOICE": 30}})
    i1 = issue("i1", amount=100000)
    i2 = issue("i2", amount=100050)
    findings = [normalize(f(amount=100025)), normalize(f(amount=100000))]
    pairs = max_matching(findings, [i2, i1], IDS, tol)
    assert pairs == [(0, "i2"), (1, "i1")]
    assert score([i1, i2], [f(amount=100025), f(amount=100000)], tol).tp == 2


def test_repeat_finding_counts_once():
    r = score([issue("i1")], [f(), f()])
    assert (r.tp, r.fp, r.fn) == (1, 1, 0)


def test_deterministic_pairs():
    i1, i2 = issue("i1"), issue("i2")
    a = max_matching([normalize(f()), normalize(f())], [i2, i1], IDS)
    b = max_matching([normalize(f()), normalize(f())], [i1, i2], IDS)
    assert a == b
