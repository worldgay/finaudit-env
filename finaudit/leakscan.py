"""Leak scanner over observations, trajectories and public episode files.

python -m finaudit.leakscan [--episodes DIR ...] [--trajectories FILE ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from finaudit.generator.episode_io import PUBLIC
from finaudit.util.canon import dumps
from finaudit.util.leak import scan_text

ISSUE_ID = re.compile(r"iss-[0-9A-Z]{6}")


def scan_observation(obs: object, first: bool = False) -> list[str]:
    """Forbidden tokens inside one observation.

    The first observation legitimately lists the four finding types and the policy;
    for it only the manifest is scanned.
    """
    if not isinstance(obs, dict):
        return ["observation is not an object"]
    hits: list[str] = []
    if first:
        res = obs.get("result") or {}
        payloads = [res.get("manifest")]
    else:
        payloads = [obs.get("result")]
    if obs.get("error"):
        payloads.append(obs["error"].get("message"))
    for payload in payloads:
        text = dumps(payload)
        hits += scan_text(text)
        hits += ISSUE_ID.findall(text)
    return hits


def scan_trajectory_file(path: str | Path) -> list[str]:
    """Scan every observation stored in a trajectories.jsonl file."""
    problems = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        rec = json.loads(line)
        first = rec["step"] == 0
        hits = scan_observation(rec["observation"], first=first)
        if hits:
            problems.append(f"{path}:{n}: {sorted(set(hits))[:5]}")
    return problems


def scan_episode_dir(episode_dir: str | Path) -> list[str]:
    """Scan the public files of an episode (issue ids from truth are extra tokens)."""
    root = Path(episode_dir)
    truth_path = root / "private" / "truth.json"
    extra: tuple[str, ...] = ()
    if truth_path.exists():
        extra = tuple(i["issue_id"] for i in json.loads(truth_path.read_text())["issues"])
    problems = []
    for name in PUBLIC:
        if name == "policy.json":
            continue
        hits = scan_text((root / "public" / name).read_text(encoding="utf-8"), extra)
        if hits:
            problems.append(f"{root.name}/public/{name}: {hits[:5]}")
    leftovers = sorted(p.name for p in (root / "public").iterdir() if p.name not in PUBLIC)
    if leftovers:
        problems.append(f"{root.name}/public has extra files {leftovers}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI: exit 1 when anything leaks."""
    ap = argparse.ArgumentParser(description="Scan for leaks of private grader data")
    ap.add_argument("--episodes", nargs="*", default=[])
    ap.add_argument("--trajectories", nargs="*", default=[])
    args = ap.parse_args(argv)
    problems: list[str] = []
    for root in args.episodes:
        for ep in sorted(p for p in Path(root).iterdir() if (p / "public").is_dir()):
            problems += scan_episode_dir(ep)
    for traj in args.trajectories:
        problems += scan_trajectory_file(traj)
    for p in problems:
        sys.stdout.write(f"LEAK {p}\n")
    sys.stdout.write(f"leakscan: {len(problems)} problems\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
