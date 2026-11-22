"""Один детерминированный ГПСЧ на эпизод."""
from __future__ import annotations

import random

from finaudit.util.canon import config_hash, sha256_text


def derive_seed(*parts: object) -> int:
    """Выводит 64-битный целый seed из произвольных частей (без hash())."""
    text = "|".join(str(p) for p in parts)
    return int(sha256_text(text)[:16], 16)


def make_rng(seed: int, config: dict, version: str, attempt: int = 0) -> random.Random:
    """Создаёт ГПСЧ эпизода из (seed, канонический хеш config, версия, попытка)."""
    return random.Random(derive_seed(seed, config_hash(config), version, attempt))
