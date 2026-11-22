"""Конвейер генерации эпизода и CLI.

python -m finaudit.generator.generate --seed N --config configs/train.json --out DIR
"""
from __future__ import annotations

import argparse
import random
import copy
import json
import sys
from pathlib import Path

from finaudit import ENV_VERSION
from finaudit.generator.books import build_books, check_invariants
from finaudit.generator.distractors import (add_boundary, add_multi, add_next_month, add_refund,
                                            add_split, add_weekly, detect_natural)
from finaudit.generator.episode_io import write_files
from finaudit.generator.inject import Ctx, NoCandidate, run_injections
from finaudit.generator.render import Episode, render_episode
from finaudit.generator.scenario import add_plain, add_slots, doc_need, issue_count, plan_errors
from finaudit.generator.verify import verify_files
from finaudit.generator.world import new_world
from finaudit.util.ids import IdFactory
from finaudit.util.rng import make_rng
from finaudit.util.validate import errors, load_schema

MAX_ATTEMPTS = 20

DEFAULT_CONFIG: dict = {
    "config_version": "1.0",
    "mode": "train",
    "size": {"ledger": [200, 2000], "documents": [20, 200]},
    "base_currency": None,
    "foreign_currencies": ["USD", "EUR", "GBP", "JPY"],
    "timezone": None,
    "errors": {t: {"count": [0, 2]} for t in
               ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")},
    "interactions": {"I1": [0, 1], "I2": [0, 1]},
    "clean": False,
    "distractors": {"min_kinds": 3},
}


class GenerationError(RuntimeError):
    """Нет валидного эпизода после MAX_ATTEMPTS детерминированных попыток."""


def normalize_config(config: dict | None) -> dict:
    """Накладывает (частичный) config на значения по умолчанию и проверяет его по config.schema.json."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (config or {}).items():
        if key == "errors":
            for typ, spec in value.items():
                # сокращение {"TYPE": 2} или {"TYPE": [0, 2]}; неизвестные внутренние ключи (например, "rate") игнорируются
                count = spec.get("count") if isinstance(spec, dict) else spec
                cfg["errors"][typ] = {"count": count}
        elif key in ("size", "interactions", "distractors") and isinstance(value, dict):
            cfg[key] = {**cfg[key], **value}
        elif key in DEFAULT_CONFIG or key == "description":
            cfg[key] = value
        # любой другой ключ (episode_dir, seed, метаданные прогона, ...) на данные не влияет
    cfg["distractors"] = {k: v for k, v in cfg["distractors"].items() if k == "min_kinds"}
    problems = errors(cfg, load_schema("config"))
    if problems:
        raise ValueError(f"bad config: {problems[:3]}")
    return cfg


def build_clean(rng: random.Random, cfg: dict) -> tuple:
    """Проходы 1-2: скрытый мир и чистые книги. Возвращает (world, plan, ids, rows)."""
    ids = IdFactory(rng)
    w = new_world(rng, cfg, ids)
    plan = plan_errors(rng, cfg)
    add_split(w, rng, ids)
    add_multi(w, rng, ids)
    add_refund(w, rng, ids)
    add_weekly(w, rng, ids)
    add_boundary(w, rng, ids)
    add_next_month(w, rng, ids, rng.randint(1, 4) + plan["PERIOD_CUTOFF"])
    add_slots(w, rng, ids, plan)
    lo, hi = cfg["size"]["documents"]
    copies = plan["DUPLICATE_INVOICE"] + plan["I2"]
    floor = max(lo, len(w.invoices) + len(w.payments) + doc_need(plan) + copies)
    if floor > hi:
        raise NoCandidate("documents range too small for the error plan")
    add_plain(w, rng, ids, plan, rng.randint(floor, hi) - copies)
    grow = 3 * issue_count(plan)
    shrink = 5 * (plan["PAYMENT_ALLOCATION"] + plan["I1"] + plan["I2"])
    rows = build_books(w, rng, ids, cfg["size"]["ledger"], grow, shrink)
    return w, plan, ids, rows


def _build(rng: random.Random, cfg: dict, seed: int, attempt: int) -> Episode:
    w, plan, ids, rows = build_clean(rng, cfg)
    broken = check_invariants(w, rows)
    if broken:
        raise RuntimeError(f"clean-book invariants violated: {broken[:5]}")
    detect_natural(w, rows)
    if len(set(w.distractors)) < cfg["distractors"]["min_kinds"]:
        raise NoCandidate("distractors")
    ctx = Ctx(w, rows, ids, rng)
    run_injections(ctx, plan)
    return render_episode(ctx, rng, plan, seed, cfg, attempt)


def generate_episode(seed: int, config: dict | None = None) -> Episode:
    """Детерминированно генерирует проверенный эпизод из (seed, config, ENV_VERSION)."""
    cfg = normalize_config(config)
    last: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        rng = make_rng(seed, cfg, ENV_VERSION, attempt)
        try:
            ep = _build(rng, cfg, seed, attempt)
        except NoCandidate as exc:
            last = [str(exc)]
            continue
        last = verify_files(ep.files)
        if not last:
            return ep
    raise GenerationError(f"seed {seed}: no valid episode after {MAX_ATTEMPTS} attempts: {last[:3]}")


def generate_to_dir(seed: int, config: dict | None, out_root: str | Path) -> Path:
    """Генерирует и записывает ``<out_root>/<episode_id>/{public,private}``; возвращает каталог эпизода."""
    ep = generate_episode(seed, config)
    return write_files(ep.files, Path(out_root) / ep.episode_id)


def load_config(path: str | Path) -> dict:
    """Читает JSON-файл конфигурации."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    ap = argparse.ArgumentParser(description="Генерация одного эпизода FinAudit")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    cfg = load_config(args.config) if args.config else None
    out = generate_to_dir(args.seed, cfg, args.out)
    sys.stdout.write(f"{out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
