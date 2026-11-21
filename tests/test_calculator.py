import pytest

from finaudit.env.calculator import evaluate
from finaudit.env.errors import EnvError


@pytest.mark.parametrize("expr,want", [
    ("1+2*3", "7"), ("(1+2)*3", "9"), ("10/4", "2.5"), ("-3+1", "-2"),
    ("1250000 * 512.3482 / 100", "6404352.5"), ("0.1+0.2", "0.3"), ("  7 - 7 ", "0"),
    ("(1250000 * 512.3482) / 100", "6404352.5"), ("1/3", "0.3333333333333333333333333333"),
])
def test_ok(expr, want):
    assert evaluate(expr) == want


@pytest.mark.parametrize("expr", [
    "__import__('os')", "a+1", "2**10", "[1]", "1" * 201, "1/0", "'1'", "True+1", "1 if 1 else 2",
    "abs(-1)", "1;2", "", "1j", "0x10", "1e100000*1e100000", "(1,2)", "1 // 2", "5 % 2",
])
def test_rejected(expr):
    with pytest.raises(EnvError) as exc:
        evaluate(expr)
    assert exc.value.code == "BAD_EXPRESSION"
    assert len(exc.value.message) <= 120


def test_non_string_is_bad_args():
    with pytest.raises(EnvError) as exc:
        evaluate(5)
    assert exc.value.code == "BAD_ARGS"


def test_exactly_200_chars_allowed():
    expr = "10" + "+0" * 98 + "+1"
    assert len(expr) == 200
    assert evaluate(expr) == "11"
