"""Непрозрачные идентификаторы из ГПСЧ эпизода.

В алфавите нет гласных, поэтому ID никогда не складывается в слово (никаких подсказок).
"""
from __future__ import annotations

import random

ALPHABET = "0123456789BCDFGHJKLMNPQRSTVWXZ"


class IdFactory:
    """Генерирует уникальные непрозрачные ID вида ``INV-7F3K2Q``."""

    def __init__(self, rng: random.Random, taken: set[str] | None = None) -> None:
        self._rng = rng
        self._taken: set[str] = set(taken or ())

    def new(self, prefix: str, length: int = 6) -> str:
        """Возвращает новый ID ``<prefix>-<length символов>``, ранее не выдававшийся."""
        while True:
            body = "".join(self._rng.choice(ALPHABET) for _ in range(length))
            ident = f"{prefix}-{body}"
            if ident not in self._taken:
                self._taken.add(ident)
                return ident

    def reserve(self, idents: list[str]) -> None:
        """Помечает ID как занятые."""
        self._taken.update(idents)


def episode_id(rng: random.Random) -> str:
    """Возвращает непрозрачный ID эпизода ``ep-<12 hex>``."""
    return "ep-" + "".join(rng.choice("0123456789abcdef") for _ in range(12))
