"""Safe arithmetic calculator: numbers, + - * /, unary minus/plus, parentheses; Decimal(28)."""
from __future__ import annotations

import ast
import decimal
from decimal import Decimal

from finaudit.env.errors import EnvError

MAX_LEN = 200
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def _eval(node: ast.AST, src: str) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval(node.body, src)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise EnvError("BAD_EXPRESSION", "only numbers are allowed")
        text = ast.get_source_segment(src, node) or ""
        return Decimal(text)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        val = _eval(node.operand, src)
        return -val if isinstance(node.op, ast.USub) else +val
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left, src), _eval(node.right, src)
        if isinstance(node.op, ast.Div) and right == 0:
            raise EnvError("BAD_EXPRESSION", "division by zero")
        return _BINOPS[type(node.op)](left, right)
    raise EnvError("BAD_EXPRESSION", "unsupported syntax")


def evaluate(expression: object) -> str:
    """Evaluate ``expression`` and return the decimal result as a plain string."""
    if not isinstance(expression, str):
        raise EnvError("BAD_ARGS", "expression must be a string")
    if len(expression) > MAX_LEN:
        raise EnvError("BAD_EXPRESSION", "expression longer than 200 characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError):
        raise EnvError("BAD_EXPRESSION", "cannot parse expression") from None
    with decimal.localcontext() as ctx:
        ctx.prec = 28
        ctx.traps[decimal.Inexact] = False
        try:
            value = _eval(tree, expression.strip())
        except (decimal.DecimalException, ArithmeticError):
            raise EnvError("BAD_EXPRESSION", "arithmetic error") from None
    if value.is_zero():
        return "0"
    if abs(value.adjusted()) > 40:
        raise EnvError("BAD_EXPRESSION", "result out of range")
    text = format(value.normalize(), "f")
    return text
