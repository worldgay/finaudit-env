"""Opaque identifiers drawn from the episode RNG.

The alphabet has no vowels, so an ID can never spell a word (no hints).
"""
from __future__ import annotations

import random

ALPHABET = "0123456789BCDFGHJKLMNPQRSTVWXZ"


class IdFactory:
    """Generates unique opaque IDs such as ``INV-7F3K2Q``."""

    def __init__(self, rng: random.Random, taken: set[str] | None = None) -> None:
        self._rng = rng
        self._taken: set[str] = set(taken or ())

    def new(self, prefix: str, length: int = 6) -> str:
        """Return a fresh ID ``<prefix>-<length chars>`` never returned before."""
        while True:
            body = "".join(self._rng.choice(ALPHABET) for _ in range(length))
            ident = f"{prefix}-{body}"
            if ident not in self._taken:
                self._taken.add(ident)
                return ident

    def reserve(self, idents: list[str]) -> None:
        """Mark IDs as taken."""
        self._taken.update(idents)


def episode_id(rng: random.Random) -> str:
    """Return an opaque episode id ``ep-<12 hex>``."""
    return "ep-" + "".join(rng.choice("0123456789abcdef") for _ in range(12))
