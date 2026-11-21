"""Run policies against the environment.

train: in-process (fast).  eval: three processes talking JSON lines -
  runner (this process) <-> env-server (user `grader`)  and  runner <-> agent (user `agent`).
The agent only ever receives observations; reward/metrics go to grader_log.jsonl.

python -m finaudit.runner trajectories
python -m finaudit.runner run --episode DIR --policy NAME [--mode eval] [--allow-oracle]
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from finaudit import ENV_VERSION
from finaudit.env.core import FinAuditEnv
from finaudit.generator.episode_io import read_files
from finaudit.policies.base import Policy
from finaudit.policies.flag_all import FlagAllPolicy
from finaudit.policies.oracle import OraclePolicy
from finaudit.policies.random_explorer import RandomExplorerPolicy
from finaudit.policies.reconciler import ReconcilerPolicy
from finaudit.util.canon import dumps

ROOT = Path(__file__).resolve().parent.parent
POLICIES = ("random_explorer", "reconciler", "flag_all", "oracle")
MAX_SECONDS = 60.0
MAX_LINE = 1_000_000  # bytes accepted per agent action line


def make_policy(name: str, policy_seed: int = 0, truth: dict | None = None) -> Policy:
    """Instantiate a policy by name (oracle needs truth: grader-only)."""
    if name == "oracle":
        if truth is None:
            raise ValueError("oracle is grader-only and needs truth")
        return OraclePolicy(truth)
    return {"random_explorer": lambda: RandomExplorerPolicy(policy_seed), "reconciler": ReconcilerPolicy,
            "flag_all": FlagAllPolicy}[name]()


def _traj(episode_id: str, step: int, action, obs: dict, reward: float, term: bool, trunc: bool,
          policy: str, mode: str) -> dict:
    return {"episode_id": episode_id, "step": step, "action": action, "observation": obs,
            "reward": reward, "terminated": term, "truncated": trunc, "policy": policy,
            "env_version": ENV_VERSION, "mode": mode}


def _append(path: Path | None, records: list[dict]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(dumps(rec) + "\n")


def run_episode_train(episode_dir: str | Path, policy_name: str, traj_path: str | Path | None = None,
                      policy_seed: int = 0, max_seconds: float = MAX_SECONDS,
                      grader_log: str | Path | None = None) -> dict:
    """Run one policy in-process in train mode; returns a result summary."""
    started = time.monotonic()
    env = FinAuditEnv(grader_log=grader_log)
    env.policy_name = policy_name
    obs, _ = env.reset(0, {"episode_dir": str(episode_dir), "mode": "train"})
    eid = env.truth["episode_id"]
    truth = json.loads(read_files(episode_dir)["private/truth.json"]) if policy_name == "oracle" else None
    policy = make_policy(policy_name, policy_seed, truth)
    policy.reset(obs)
    records = [_traj(eid, 0, None, obs, 0.0, False, False, policy_name, "train")]
    done, step, reward = False, 0, 0.0
    while not done:
        if time.monotonic() - started > max_seconds:
            obs, reward, term, trunc, info = env.force_truncate()
            records.append(_traj(eid, step + 1, None, obs, reward, term, trunc, policy_name, "train"))
            break
        action = policy.act(obs)
        obs, reward, term, trunc, info = env.step(action)
        step += 1
        records.append(_traj(eid, step, action, obs, reward, term, trunc, policy_name, "train"))
        done = term or trunc
    _append(Path(traj_path) if traj_path else None, records)
    g = env.last_grade
    return {"episode_id": eid, "policy": policy_name, "reward": g.reward, "f1": g.f1, "precision": g.precision,
            "recall": g.recall, "tp": g.tp, "fp": g.fp, "fn": g.fn, "steps": env.steps_used,
            "valid": g.valid, "truncated": env.flags[1], "seconds": round(time.monotonic() - started, 4),
            "matches": [list(m) for m in g.matches]}


# ---------------------------------------------------------------------- eval (isolated processes)
def isolation_users() -> tuple[str | None, str | None]:
    """('grader', 'agent') when running as root with both users present, else (None, None)."""
    if os.geteuid() != 0:
        return None, None
    try:
        pwd.getpwnam("grader")
        pwd.getpwnam("agent")
    except KeyError:
        return None, None
    return "grader", "agent"


def _env_vars(home: str) -> dict:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": str(ROOT), "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1", "HOME": home, "LANG": "C.UTF-8"}


def secure_dir(path: Path, owner: str | None) -> None:
    """chown -R owner and chmod 700 (no-op without isolation users)."""
    if owner is None:
        return
    for p in [path, *path.rglob("*")]:
        shutil.chown(p, owner, owner)
        p.chmod(0o700 if p.is_dir() else 0o600)


def _read_line(proc: subprocess.Popen, deadline: float) -> str | None:
    """One line from an agent's stdout, or None on timeout/EOF."""
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not sel.select(timeout=remaining):
            return None
        line = proc.stdout.readline(MAX_LINE)
        return line.decode("utf-8", "replace") if line else None
    finally:
        sel.close()


class _Server:
    """Handle to the env-server subprocess."""

    def __init__(self, grader_log: Path, policy_name: str, user: str | None, home: str) -> None:
        cmd = [sys.executable, "-m", "finaudit.env.server", "--grader-log", str(grader_log),
               "--policy-name", policy_name]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     env=_env_vars(home), cwd=home, user=user)

    def call(self, msg: dict) -> dict:
        """Send one command and wait for the reply."""
        self.proc.stdin.write(dumps(msg) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        """Stop the server."""
        try:
            self.proc.stdin.write(dumps({"cmd": "close"}) + "\n")
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.proc.kill()


def _spawn_agent(name: str, seed: int, user: str | None, workdir: str) -> subprocess.Popen:
    cmd = [sys.executable, "-m", f"finaudit.policies.{name}", "--seed", str(seed)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=_env_vars(workdir), cwd=workdir, user=user, bufsize=0)


def _agent_loop(server: _Server, agent, oracle, first: dict, eid: str, name: str,
                deadline: float) -> list[dict]:
    """Relay observations to the agent and actions to the server until the episode ends."""
    obs, step, records = first, 0, []
    while True:
        if oracle is not None:
            action: object = oracle.act(obs)
        else:
            agent.stdin.write((dumps(obs) + "\n").encode("utf-8"))
            agent.stdin.flush()
            line = _read_line(agent, deadline)
            if line is None:
                reply = server.call({"cmd": "timeout"})
                records.append(_traj(eid, step + 1, None, reply["observation"], reply["reward"],
                                     reply["terminated"], reply["truncated"], name, "eval"))
                return records
            try:
                action = json.loads(line)
            except json.JSONDecodeError:
                action = line.strip()[:200]
        reply = server.call({"cmd": "step", "action": action})
        step += 1
        records.append(_traj(eid, step, action, reply["observation"], reply["reward"],
                             reply["terminated"], reply["truncated"], name, "eval"))
        obs = reply["observation"]
        if reply["terminated"] or reply["truncated"]:
            return records


def run_episode_eval(episode_dir: str | Path, policy_name: str, run_dir: str | Path, policy_seed: int = 0,
                     allow_oracle: bool = False, max_seconds: float = MAX_SECONDS) -> dict:
    """Run one policy in eval mode with process (and, as root in Docker, user) isolation.

    The env-server works on a grader-owned private staging copy of the episode (mode 700); the agent
    runs in an empty directory of its own and only ever receives observations.
    """
    if policy_name == "oracle" and not allow_oracle:
        raise PermissionError("oracle is grader-only: pass --allow-oracle")
    started = time.monotonic()
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    grader_user, agent_user = isolation_users()
    stage = Path(tempfile.mkdtemp(prefix="grader-"))
    shutil.copytree(episode_dir, stage / "episode")
    log = stage / "grader_log.jsonl"
    secure_dir(stage, grader_user)
    workdir = tempfile.mkdtemp(prefix="agent-")
    if agent_user:
        shutil.chown(workdir, agent_user, agent_user)
    server = _Server(log, policy_name, grader_user, str(stage))
    agent, oracle = None, None
    try:
        first = server.call({"cmd": "reset", "seed": 0,
                             "config": {"episode_dir": str(stage / "episode"), "mode": "eval"}})
        obs = first["observation"]
        eid = obs["result"]["manifest"]["episode_id"]
        if policy_name == "oracle":  # grader-only: runs inside the orchestrator, never as an agent
            oracle = make_policy("oracle", truth=json.loads(read_files(episode_dir)["private/truth.json"]))
        else:
            agent = _spawn_agent(policy_name, policy_seed, agent_user, workdir)
        records = [_traj(eid, 0, None, obs, 0.0, False, False, policy_name, "eval")]
        records += _agent_loop(server, agent, oracle, obs, eid, policy_name, started + max_seconds)
    finally:
        if agent is not None:
            agent.kill()
            agent.wait()
        server.close()
        shutil.rmtree(workdir, ignore_errors=True)
    graded_text = log.read_text(encoding="utf-8")
    shutil.rmtree(stage, ignore_errors=True)
    with open(run_dir / "grader_log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(graded_text)
    _append(run_dir / "trajectories.jsonl", records)
    secure_dir(run_dir, grader_user)
    mine = [json.loads(x) for x in graded_text.splitlines()][-1]
    mine["seconds"] = round(time.monotonic() - started, 4)
    mine["grader_only"] = policy_name == "oracle"
    return mine


def write_trajectories(out: Path = ROOT / "trajectories" / "trajectories.jsonl",
                       episodes: Path = ROOT / "episodes" / "train") -> list[dict]:
    """4 policies x train episodes in train mode -> trajectories.jsonl."""
    if out.exists():
        out.unlink()
    results = []
    for ep in sorted(p for p in episodes.iterdir() if (p / "public").is_dir()):
        for k, name in enumerate(POLICIES):
            results.append(run_episode_train(ep, name, out, policy_seed=k))
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description="FinAudit policy runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("trajectories")
    run = sub.add_parser("run")
    run.add_argument("--episode", required=True)
    run.add_argument("--policy", required=True, choices=POLICIES)
    run.add_argument("--mode", default="train", choices=("train", "eval"))
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--run-dir", default=str(ROOT / "runs" / "manual"))
    run.add_argument("--allow-oracle", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "trajectories":
        results = write_trajectories()
        sys.stdout.write(f"trajectories: {len(results)} episodes written\n")
        return 0
    if args.mode == "train":
        res = run_episode_train(args.episode, args.policy, Path(args.run_dir) / "trajectories.jsonl", args.seed,
                                grader_log=Path(args.run_dir) / "grader_log.jsonl")
    else:
        res = run_episode_eval(args.episode, args.policy, args.run_dir, args.seed, args.allow_oracle)
    sys.stdout.write(dumps(res) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
