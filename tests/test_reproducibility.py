import os
import subprocess
import sys

from conftest import ROOT, SMALL
from finaudit.env.core import FinAuditEnv
from finaudit.generator.generate import generate_episode
from finaudit.runner import run_episode_train
from finaudit.util.canon import sha256_text


def _hashes(files):
    return {k: sha256_text(v) for k, v in files.items()}


def test_same_seed_same_bytes():
    for seed in (1, 2, 3, 2 ** 63 + 11):
        assert _hashes(generate_episode(seed, SMALL).files) == _hashes(generate_episode(seed, SMALL).files)


def test_different_seed_or_config_differs():
    a = generate_episode(1, SMALL).files
    assert a != generate_episode(2, SMALL).files
    assert a != generate_episode(1, {**SMALL, "clean": True}).files


def test_mode_and_description_do_not_change_data():
    a = generate_episode(4, {**SMALL, "mode": "train"}).files
    b = generate_episode(4, {**SMALL, "mode": "eval", "description": "x"}).files
    assert a == b


def test_independent_of_hash_seed():
    code = ("import sys;sys.path.insert(0,%r);from finaudit.generator.generate import generate_episode;"
            "from finaudit.util.canon import dumps,sha256_text;"
            "print(sha256_text(dumps(generate_episode(77).files)))") % str(ROOT)
    outs = set()
    for hs in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hs}
        outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                check=True).stdout.strip())
    assert len(outs) == 1


def test_same_actions_same_trajectory(err_dir, tmp_path):
    for name in ("random_explorer", "reconciler", "flag_all", "oracle"):
        a, b = tmp_path / f"{name}-a.jsonl", tmp_path / f"{name}-b.jsonl"
        ra = run_episode_train(err_dir, name, a, policy_seed=3)
        rb = run_episode_train(err_dir, name, b, policy_seed=3)
        assert a.read_bytes() == b.read_bytes()
        assert ra["reward"] == rb["reward"]


def test_reset_isolates(err_dir, clean_dir):
    env = FinAuditEnv()
    seq = [{"action": "list_records", "table": "ledger"}, {"action": "calculator", "expression": "2/3"}]
    env.reset(0, {"episode_dir": str(err_dir)})
    first = [env.step(a) for a in seq]
    env.reset(0, {"episode_dir": str(clean_dir)})
    env.step({"action": "list_records", "table": "fx"})
    env.reset(0, {"episode_dir": str(err_dir)})
    again = [env.step(a) for a in seq]
    fresh = FinAuditEnv()
    fresh.reset(0, {"episode_dir": str(err_dir)})
    assert first == again == [fresh.step(a) for a in seq]
