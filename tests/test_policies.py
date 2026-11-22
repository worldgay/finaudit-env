"""Все 4 политики корректно завершаются на 20 эпизодах; ранжирование oracle > reconciler > random >= flag_all."""
import statistics

import pytest

from finaudit.generator.generate import generate_to_dir
from finaudit.runner import POLICIES, run_episode_train

CFG = {"size": {"ledger": [200, 900], "documents": [20, 120]}}


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    root = tmp_path_factory.mktemp("pol")
    dirs = [generate_to_dir(3000 + s, {**CFG, "clean": s < 5}, root) for s in range(20)]
    return {name: [run_episode_train(d, name, policy_seed=s) for s, d in enumerate(dirs)] for name in POLICIES}


def test_all_finish_validly(results):
    for name, rows in results.items():
        assert len(rows) == 20
        assert all(r["valid"] and r["steps"] <= 100 for r in rows), name
        assert all(not r["truncated"] for r in rows), name


def test_ranking(results):
    mean = {n: statistics.mean(r["reward"] for r in rows) for n, rows in results.items()}
    f1 = {n: statistics.mean(r["f1"] for r in rows) for n, rows in results.items()}
    assert mean["oracle"] > mean["reconciler"] > mean["random_explorer"] >= mean["flag_all"], mean
    assert f1["flag_all"] < f1["reconciler"] < f1["oracle"], f1
    assert all(r["reward"] >= 0.9 for r in results["oracle"])
    assert mean["flag_all"] <= -0.5
