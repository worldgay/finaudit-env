"""Eval-mode isolation: separate processes, no reward to the agent, private files unreadable."""
import json
import subprocess
import sys

import pytest

from conftest import ROOT, in_docker
from finaudit.runner import isolation_users, run_episode_eval


def test_eval_gives_agent_no_reward(err_dir, tmp_path):
    res = run_episode_eval(err_dir, "reconciler", tmp_path, policy_seed=0)
    lines = [json.loads(x) for x in (tmp_path / "trajectories.jsonl").read_text().splitlines()]
    for rec in lines:
        assert rec["reward"] == 0.0 and rec["mode"] == "eval"
        assert set(rec["observation"]) == {"ok", "result", "error", "steps_left"}
    assert lines[-1]["terminated"] or lines[-1]["truncated"]
    log = [json.loads(x) for x in (tmp_path / "grader_log.jsonl").read_text().splitlines()]
    assert log[-1]["policy"] == "reconciler" and "f1" in log[-1] and res["f1"] == log[-1]["f1"]


def test_eval_matches_train(err_dir, tmp_path):
    from finaudit.runner import run_episode_train
    for name in ("reconciler", "flag_all", "random_explorer"):
        ev = run_episode_eval(err_dir, name, tmp_path / name, policy_seed=4)
        tr = run_episode_train(err_dir, name, policy_seed=4)
        assert ev["reward"] == tr["reward"] and ev["f1"] == tr["f1"], name


def test_oracle_requires_flag(err_dir, tmp_path):
    with pytest.raises(PermissionError):
        run_episode_eval(err_dir, "oracle", tmp_path)
    res = run_episode_eval(err_dir, "oracle", tmp_path, allow_oracle=True)
    assert res["reward"] == 1.0 and res["grader_only"]


def test_agent_timeout_truncates(err_dir, tmp_path, monkeypatch):
    import finaudit.runner as runner
    monkeypatch.setattr(runner, "_spawn_agent", lambda *a, **k: subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        bufsize=0))
    res = runner.run_episode_eval(err_dir, "reconciler", tmp_path, max_seconds=1.0)
    assert res["truncated"] and res["tp"] == 0


@pytest.mark.docker
@pytest.mark.skipif(not in_docker(), reason="needs the Docker image (root + users grader/agent)")
def test_agent_user_cannot_read_private(err_dir, tmp_path):
    from finaudit.runner import secure_dir
    grader, agent = isolation_users()
    assert grader == "grader" and agent == "agent"
    secure_dir(err_dir / "private", "grader")
    target = err_dir / "private" / "truth.json"
    probe = f"open({str(target)!r}).read()"
    proc = subprocess.run([sys.executable, "-c", probe], user="agent", capture_output=True, text=True,
                          cwd="/tmp", env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)})
    assert proc.returncode != 0 and "Permission denied" in proc.stderr
    shipped = sorted((ROOT / "episodes").glob("*/*/private/truth.json"))
    if shipped:
        proc = subprocess.run([sys.executable, "-c", f"open({str(shipped[0])!r}).read()"], user="agent",
                              capture_output=True, text=True, cwd="/tmp", env={"PATH": "/usr/bin:/bin"})
        assert proc.returncode != 0
    res = run_episode_eval(err_dir, "reconciler", tmp_path / "run", policy_seed=0)
    assert res["valid"]
