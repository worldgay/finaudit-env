"""`make episodes`: генерирует сдаваемый набор (10 train + 10 dev) по configs/dataset.json."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from finaudit.generator.generate import generate_to_dir, load_config
from finaudit.generator.verify import verify_episode

ROOT = Path(__file__).resolve().parent.parent


def build_dataset(spec_path: Path = ROOT / "configs" / "dataset.json", out: Path = ROOT / "episodes") -> list[str]:
    """(Пере)генерирует каждый сплит; возвращает список имён 'split/episode_id'."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    made = []
    for split, info in spec["sets"].items():
        target = out / split
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for seed in info["seeds"]:
            cfg_file = info["special"].get(str(seed), info["config"])
            ep_dir = generate_to_dir(seed, load_config(ROOT / cfg_file), target)
            problems = verify_episode(ep_dir)
            if problems:
                raise RuntimeError(f"{ep_dir}: {problems[:3]}")
            made.append(f"{split}/{ep_dir.name}")
    return made


def main() -> int:
    """Точка входа CLI."""
    made = build_dataset()
    sys.stdout.write(f"episodes: {len(made)} записано и проверено\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
