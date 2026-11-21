"""Regression tests for failures found by the pre-submission audit (README "Measured failures").

Each test reproduces the measured failure; before the fix it crashed or hung, now it must give a bounded result.
"""
import base64
import json
import shutil
import subprocess
import sys

import pytest

import judge_adapter as ja
from conftest import SMALL
from finaudit.env import core


@pytest.fixture(scope="module")
def ep(tmp_path_factory):
    root = tmp_path_factory.mktemp("hostile")
    ja.generate_episode(8, {**SMALL, "clean": True}, str(root / "C"))
    return root / "C"


def _closed(ep):
    env = ja.make_env()
    env.reset(0, {"mode": "closed", "episode_dir": str(ep)})
    return env


def test_deeply_nested_cursor_is_bad_cursor_not_a_crash(ep):
    # Was: RecursionError escaped JudgeEnv.step into the caller's harness.
    env = _closed(ep)
    cursor = base64.urlsafe_b64encode(b"[" * 100_000).decode().rstrip("=")
    obs, reward, term, trunc, info = env.step({"name": "list_records",
                                               "args": {"table": "ledger", "cursor": cursor, "limit": 5}})
    assert obs["error"]["code"] == "BAD_CURSOR" and obs["remaining_steps"] == 99
    assert (reward, term, trunc) == (0.0, False, False)


def test_unexpected_handler_exception_is_bounded(ep, monkeypatch):
    def boom(store, action):
        raise RecursionError("deep")
    monkeypatch.setitem(core.HANDLERS, "calculator", boom)
    env = _closed(ep)
    obs = env.step({"name": "calculator", "args": {"expression": "1+1"}})[0]
    assert obs["error"]["code"] == "BAD_ARGS" and obs["remaining_steps"] == 99
    assert "deep" not in obs["error"]["message"]


def test_step_before_reset_and_missing_episode_dir(tmp_path):
    with pytest.raises(RuntimeError):
        ja.make_env().step({"name": "calculator", "args": {"expression": "1"}})
    with pytest.raises(FileNotFoundError):
        ja.make_env().reset(0, {"mode": "closed", "episode_dir": str(tmp_path / "nope")})


def test_closed_reset_without_truth(ep, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(ep / "public", copy / "public")
    env = ja.make_env()
    first, _ = env.reset(0, {"mode": "closed", "episode_dir": str(copy)})
    assert first["remaining_steps"] == 100
    with pytest.raises(ValueError):
        ja.make_env().reset(0, {"mode": "train", "episode_dir": str(copy)})


@pytest.mark.parametrize("script", [
    # partial line without newline, then silence: readline() used to block forever
    "import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(30)",
    # flood of actions while never reading stdin: the runner's write used to block forever
    "import sys,time\nfor _ in range(2000): sys.stdout.write('{\"action\":\"list_records\",\"table\":\"ledger\"}\\n')\n"
    "sys.stdout.flush(); time.sleep(30)",
    # deeply nested JSON line: json.loads raised RecursionError and aborted the episode
    "import sys,time; sys.stdout.write('['*100000+'\\n'); sys.stdout.flush(); time.sleep(30)",
])
def test_runner_survives_hostile_agent(err_dir, tmp_path, monkeypatch, script):
    import finaudit.runner as runner
    monkeypatch.setattr(runner, "_spawn_agent", lambda *a, **k: subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0))
    res = runner.run_episode_eval(err_dir, "reconciler", tmp_path, max_seconds=2.0)
    assert res["seconds"] < 10 and "tp" in res  # finished and graded instead of hanging
    lines = (tmp_path / "trajectories.jsonl").read_text().splitlines()
    assert lines and all(json.loads(x)["reward"] == 0.0 for x in lines)
