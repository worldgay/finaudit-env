"""Чтение и запись каталогов эпизодов."""
from __future__ import annotations

import json
from pathlib import Path

from finaudit.util.records import parse_fx, parse_jsonl, parse_ledger

PUBLIC = ("manifest.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv", "policy.json")
PRIVATE = ("truth.json", "provenance.json", "generation.json")


def write_files(files: dict[str, str], out_dir: str | Path) -> Path:
    """Записывает ``files`` (относительный путь -> текст) в ``out_dir``."""
    root = Path(out_dir)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def read_files(episode_dir: str | Path, private: bool = True) -> dict[str, str]:
    """Читает каталог эпизода в словарь относительный путь -> текст."""
    root = Path(episode_dir)
    names = [f"public/{n}" for n in PUBLIC] + ([f"private/{n}" for n in PRIVATE] if private else [])
    return {n: (root / n).read_text(encoding="utf-8") for n in names if (root / n).exists()}


def parse_public(files: dict[str, str]) -> dict:
    """Разбирает шесть открытых файлов в структуры Python."""
    return {"manifest": json.loads(files["public/manifest.json"]),
            "policy": json.loads(files["public/policy.json"]),
            "ledger": parse_ledger(files["public/ledger.csv"]),
            "invoices": parse_jsonl(files["public/invoices.jsonl"]),
            "payments": parse_jsonl(files["public/payments.jsonl"]),
            "fx": parse_fx(files["public/fx.csv"])}


def public_ids(public: dict) -> set[str]:
    """Все ID записей, которые может получить агент: row_id, doc_id и fx-ID."""
    ids = {r["row_id"] for r in public["ledger"]}
    ids.update(i["doc_id"] for i in public["invoices"])
    ids.update(p["doc_id"] for p in public["payments"])
    ids.update(f"fx:{r['date']}:{r['source_currency']}:{r['target_currency']}" for r in public["fx"])
    return ids
