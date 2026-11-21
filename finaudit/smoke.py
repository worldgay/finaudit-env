"""Smoke stage of `make check`: generate 2 episodes in a temp dir, verify them,
run every available policy on them and scan all observations / files for leaks."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from finaudit.generator.episode_io import read_files
from finaudit.generator.generate import generate_to_dir
from finaudit.generator.verify import verify_episode
from finaudit.leakscan import scan_episode_dir, scan_trajectory_file

SMOKE_CONFIG = {"size": {"ledger": [200, 600], "documents": [20, 80]},
                "interactions": {"I1": 1, "I2": 1}}


def main() -> int:
    """Run the smoke checks; non-zero exit on any problem."""
    from finaudit.runner import POLICIES, run_episode_train
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dirs = [generate_to_dir(11, SMOKE_CONFIG, root / "eps"),
                generate_to_dir(12, {**SMOKE_CONFIG, "clean": True}, root / "eps")]
        traj = root / "trajectories.jsonl"
        for d in dirs:
            problems += [f"verify {d.name}: {p}" for p in verify_episode(d)]
            problems += scan_episode_dir(d)
            truth = json.loads(read_files(d)["private/truth.json"])
            for name in POLICIES:
                res = run_episode_train(d, name, traj, policy_seed=1)
                sys.stdout.write(f"smoke: {d.name} issues={len(truth['issues']):2d} {name:15s} "
                                 f"reward={res['reward']:+.3f} f1={res['f1']:.3f} steps={res['steps']}\n")
                if name == "oracle" and res["f1"] != 1.0:
                    problems.append(f"oracle f1 {res['f1']} on {d.name}")
        problems += scan_trajectory_file(traj)
    for p in problems:
        sys.stdout.write(f"smoke FAIL: {p}\n")
    sys.stdout.write(f"smoke: {'OK' if not problems else 'FAILED'}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
