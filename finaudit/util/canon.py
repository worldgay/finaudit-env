"""Canonical JSON serialisation and hashing helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Keys that select *how* an episode is used, not *what* is generated.
_NON_DATA_KEYS = ("mode", "episode_dir", "description")


def dumps(obj: Any) -> str:
    """Return the canonical JSON text of ``obj`` (sorted keys, compact, UTF-8)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of UTF-8 encoded ``text``."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    """Return the hex SHA-256 digest of the file at ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def data_config(config: dict) -> dict:
    """Return the part of ``config`` that influences generated data."""
    return {k: v for k, v in config.items() if k not in _NON_DATA_KEYS}


def config_hash(config: dict) -> str:
    """Return the canonical hash of the data-relevant part of a config."""
    return sha256_text(dumps(data_config(config)))


def write_json(path: str | Path, obj: Any) -> None:
    """Write ``obj`` as canonical JSON followed by a newline."""
    Path(path).write_text(dumps(obj) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> Any:
    """Read a JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
