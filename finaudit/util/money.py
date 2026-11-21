"""Integer money and Decimal FX conversion (never float)."""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

CURRENCY_EXPONENT: dict[str, int] = {"KZT": 2, "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0}


def round_half_even(value: Decimal) -> int:
    """Round a Decimal to an integer using banker's rounding."""
    with localcontext() as ctx:
        ctx.prec = 60
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def convert(amount_minor: int, src_exp: int, rate: str | Decimal, base_exp: int) -> int:
    """Convert minor units of the source currency to minor units of the base.

    base_minor = round_half_even(amount_minor / 10^src_exp * rate * 10^base_exp);
    the sign of ``amount_minor`` is preserved.
    """
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
        raise TypeError("amount_minor must be int")
    with localcontext() as ctx:
        ctx.prec = 60
        mag = Decimal(abs(amount_minor)) * Decimal(rate) * (Decimal(10) ** (base_exp - src_exp))
        out = round_half_even(mag)
    return -out if amount_minor < 0 else out


def inverse_convert(base_minor: int, src_exp: int, rate: str | Decimal, base_exp: int) -> int:
    """Convert base minor units back to source minor units (banker's rounding)."""
    with localcontext() as ctx:
        ctx.prec = 60
        mag = Decimal(abs(base_minor)) / Decimal(rate) / (Decimal(10) ** (base_exp - src_exp))
        out = round_half_even(mag)
    return -out if base_minor < 0 else out
