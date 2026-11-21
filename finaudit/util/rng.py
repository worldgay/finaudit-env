"""Single deterministic RNG per episode."""
from __future__ import annotations

import random

from finaudit.util.canon import config_hash, sha256_text


def derive_seed(*parts: object) -> int:
    """Derive a 64-bit integer seed from arbitrary parts (no hash())."""
    text = "|".join(str(p) for p in parts)
    return int(sha256_text(text)[:16], 16)


def make_rng(seed: int, config: dict, version: str, attempt: int = 0) -> random.Random:
    """Create the episode RNG from (seed, canonical config hash, version, attempt)."""
    return random.Random(derive_seed(seed, config_hash(config), version, attempt))
