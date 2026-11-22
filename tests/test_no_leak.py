"""Нет закрытых материалов в observations, ошибках, траекториях и открытых файлах."""
import base64
import json
from pathlib import Path

from conftest import ROOT
from finaudit.env.core import FinAuditEnv
from finaudit.leakscan import scan_episode_dir, scan_observation, scan_trajectory_file
from finaudit.runner import POLICIES, run_episode_eval, run_episode_train
from finaudit.util.leak import scan_text

BAD_ACTIONS = [{"action": "x"}, {"action": "get_record", "table": "ledger", "id": "../private/truth.json"},
               {"action": "get_document", "doc_id": "/etc/passwd"}, {"action": "calculator", "expression": "open(1)"},
               {"action": "list_records", "table": "ledger", "cursor": "e30"}, "garbage", None,
               {"action": "get_record", "table": "truth", "id": "x"}]


def test_observations_and_errors_clean(err_dir):
    env = FinAuditEnv()
    obs, info = env.reset(0, {"episode_dir": str(err_dir)})
    assert scan_observation(obs, first=True) == []
    assert "seed" not in json.dumps(info) and str(err_dir) not in json.dumps(obs)
    for a in BAD_ACTIONS:
        o, *_ = env.step(a)
        assert scan_observation(o) == [] and str(err_dir) not in json.dumps(o), a
    cursor = None
    for _ in range(60):
        o, *_ = env.step({"action": "list_records", "table": "ledger", "cursor": cursor})
        assert scan_observation(o) == []
        cursor = o["result"]["next_cursor"]
        if cursor is None:
            break
        decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        assert set(decoded) == {"t", "o"}


def test_trajectories_clean(err_dir, clean_dir, tmp_path):
    traj = tmp_path / "t.jsonl"
    for d in (err_dir, clean_dir):
        for name in POLICIES:
            run_episode_train(d, name, traj, policy_seed=1)
    assert scan_trajectory_file(traj) == []
    issue_ids = [i["issue_id"] for i in json.loads((err_dir / "private/truth.json").read_text())["issues"]]
    text = traj.read_text()
    assert not any(i in text for i in issue_ids) and "truth" not in text.lower()


def test_eval_trajectories_clean(err_dir, tmp_path):
    run_episode_eval(err_dir, "reconciler", tmp_path, policy_seed=1)
    assert scan_trajectory_file(tmp_path / "trajectories.jsonl") == []


def test_public_files_clean(err_dir, clean_dir):
    assert scan_episode_dir(err_dir) == [] and scan_episode_dir(clean_dir) == []


def test_shipped_dataset_and_trajectories_clean():
    for split in ("train", "dev"):
        root = ROOT / "episodes" / split
        for ep in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
            assert scan_episode_dir(ep) == [], ep
    traj = ROOT / "trajectories" / "trajectories.jsonl"
    if traj.exists():
        assert scan_trajectory_file(traj) == []


def test_scanner_catches_leaks():
    assert scan_text('{"description":"duplicate of INV-1"}')
    assert scan_text("/home/user/private/truth.json")
    assert scan_observation({"ok": True, "result": {"x": "iss-BCDFGH"}, "error": None, "steps_left": 1})
    assert scan_observation({"ok": True, "result": {"x": "PERIOD_CUTOFF"}, "error": None, "steps_left": 1})
