"""Безопасный арифметический калькулятор: числа, + - * /, унарные минус/плюс, скобки; Decimal(28)."""
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
            raise EnvError("BAD_EXPRESSION", "допускаются только числа")
        text = ast.get_source_segment(src, node) or ""
        return Decimal(text)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        val = _eval(node.operand, src)
        return -val if isinstance(node.op, ast.USub) else +val
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left, src), _eval(node.right, src)
        if isinstance(node.op, ast.Div) and right == 0:
            raise EnvError("BAD_EXPRESSION", "деление на ноль")
        return _BINOPS[type(node.op)](left, right)
    raise EnvError("BAD_EXPRESSION", "неподдерживаемый синтаксис")


def evaluate(expression: object) -> str:
    """Вычисляет ``expression`` и возвращает десятичный результат обычной строкой."""
    if not isinstance(expression, str):
        raise EnvError("BAD_ARGS", "expression должен быть строкой")
    if len(expression) > MAX_LEN:
        raise EnvError("BAD_EXPRESSION", "expression длиннее 200 символов")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError):
        raise EnvError("BAD_EXPRESSION", "не удалось разобрать выражение") from None
    with decimal.localcontext() as ctx:
        ctx.prec = 28
        ctx.traps[decimal.Inexact] = False
        try:
            value = _eval(tree, expression.strip())
        except (decimal.DecimalException, ArithmeticError):
            raise EnvError("BAD_EXPRESSION", "арифметический сбой") from None
    if value.is_zero():
        return "0"
    if abs(value.adjusted()) > 40:
        raise EnvError("BAD_EXPRESSION", "результат вне допустимого диапазона")
    text = format(value.normalize(), "f")
    return text
