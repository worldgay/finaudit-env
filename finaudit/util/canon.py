"""Каноническая сериализация JSON и хеширование."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Ключи, которые выбирают, *как* используется эпизод, а не *что* генерируется.
_NON_DATA_KEYS = ("mode", "episode_dir", "description")


def dumps(obj: Any) -> str:
    """Возвращает канонический JSON-текст ``obj`` (сортированные ключи, компактно, UTF-8)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    """Возвращает hex-дайджест SHA-256 от ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Возвращает hex-дайджест SHA-256 от ``text`` в кодировке UTF-8."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    """Возвращает hex-дайджест SHA-256 файла по пути ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def data_config(config: dict) -> dict:
    """Возвращает часть ``config``, влияющую на генерируемые данные."""
    return {k: v for k, v in config.items() if k not in _NON_DATA_KEYS}


def config_hash(config: dict) -> str:
    """Возвращает канонический хеш значимой для данных части config."""
    return sha256_text(dumps(data_config(config)))


def write_json(path: str | Path, obj: Any) -> None:
    """Записывает ``obj`` как канонический JSON с переводом строки в конце."""
    Path(path).write_text(dumps(obj) + "\n", encoding="utf-8")


def read_json(path: str | Path) -> Any:
    """Читает JSON-файл."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
