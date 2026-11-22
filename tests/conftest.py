"""Общие фикстуры pytest."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SMALL = {"size": {"ledger": [200, 320], "documents": [20, 60]},
         "errors": {t: {"count": [0, 1]} for t in
                    ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")},
         "interactions": {"I1": [0, 1], "I2": [0, 1]}}


def in_docker() -> bool:
    """True внутри Docker-образа проекта при запуске от root."""
    return os.environ.get("FINAUDIT_DOCKER") == "1" and hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.fixture
def small_config() -> dict:
    """Небольшой config для быстрых тестов."""
    import copy
    return copy.deepcopy(SMALL)


def burn(env, n: int) -> None:
    """Тратит ``n`` шагов безвредными вызовами калькулятора."""
    for _ in range(n):
        env.step({"action": "calculator", "expression": "1+1"})


@pytest.fixture(scope="session")
def episodes_root(tmp_path_factory) -> Path:
    """Несколько небольших эпизодов, записываемых на диск один раз за сессию."""
    from finaudit.generator.generate import generate_to_dir
    root = tmp_path_factory.mktemp("episodes")
    generate_to_dir(7, {**SMALL, "interactions": {"I1": 1, "I2": 1}}, root / "err")
    generate_to_dir(8, {**SMALL, "clean": True}, root / "clean")
    return root


def _only_child(path: Path) -> Path:
    return next(p for p in path.iterdir() if p.is_dir())


@pytest.fixture(scope="session")
def err_dir(episodes_root) -> Path:
    """Каталог эпизода с ошибками (включая I1 и I2)."""
    return _only_child(episodes_root / "err")


@pytest.fixture(scope="session")
def clean_dir(episodes_root) -> Path:
    """Каталог чистого эпизода (без ошибок)."""
    return _only_child(episodes_root / "clean")


@pytest.fixture
def env_err(err_dir):
    """Среда в режиме train после reset на эпизоде с ошибками."""
    from finaudit.env.core import FinAuditEnv
    env = FinAuditEnv()
    obs, _ = env.reset(0, {"episode_dir": str(err_dir), "mode": "train"})
    env.first_obs = obs
    return env


@pytest.fixture
def env_clean(clean_dir):
    """Среда в режиме train после reset на чистом эпизоде."""
    from finaudit.env.core import FinAuditEnv
    env = FinAuditEnv()
    obs, _ = env.reset(0, {"episode_dir": str(clean_dir), "mode": "train"})
    env.first_obs = obs
    return env
