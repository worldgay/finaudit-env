"""judge_adapter.py - the organisers' single connection point (docs/CHECKS.md, "Единый способ подключения").

A thin translation layer over the existing environment; it changes no task semantics:

* ``generate_episode(seed, config, output_dir)`` writes ``output_dir/public/*`` (manifest.json,
  ledger.csv, invoices.jsonl, payments.jsonl, fx.csv, policy.json) and ``output_dir/private/*``
  (truth.json, provenance.json, generation.json) with the team generator.
* ``make_env()`` returns an object with ``reset(seed, config)`` / ``step(action)``.
  ``config = {"mode": "closed" | "train", "episode_dir": ..., "team_config": {...}}``;
  actions are ``{"name": <action>, "args": {...}}``.
* ``score_episode(episode_dir, findings, inspection_steps)`` is the closed grader call.

Observations: first ``{"task", "manifest", "policy", "remaining_steps"}``, then
``{"result", "error", "remaining_steps"}``. Results: list_records -> ``{"records", "next_cursor"}``;
get_record / get_document -> the record / document object; calculator -> decimal string;
submit -> ``{"accepted": true}`` (or an INVALID_FINDINGS error, never a correctness signal).
In closed mode every reward is 0 and ``info`` only holds ``steps_used``.
"""
from __future__ import annotations

import json
import sys
import time

from finaudit.env.core import FinAuditEnv
from finaudit.env.store import Store
from finaudit.generator.episode_io import parse_public, read_files, write_files
from finaudit.generator.generate import generate_episode as _generate
from finaudit.grader.grader import grade
from finaudit.grader.matcher import tolerances

TIME_LIMIT_SECONDS = 60.0
TABLES = ("ledger", "invoices", "payments", "fx")


def _team_config(config: dict | None) -> dict:
    config = dict(config or {})
    return dict(config.get("team_config") or {}) if "team_config" in config else config


def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Generate one verified episode for (seed, team config) directly into ``output_dir``."""
    cfg = _team_config(config)
    cfg.pop("mode", None)
    write_files(_generate(int(seed), cfg).files, output_dir)


def _error(err: dict | None) -> dict | None:
    return None if err is None else {"code": err["code"], "message": err["message"]}


class JudgeEnv:
    """reset/step in the organisers' envelope around one ``FinAuditEnv``."""

    def __init__(self, time_limit: float = TIME_LIMIT_SECONDS) -> None:
        self.time_limit = time_limit
        self.env = FinAuditEnv()
        self.started = 0.0

    def reset(self, seed: int | None = 0, config: dict | None = None) -> tuple[dict, dict]:
        """``mode`` closed -> the environment's eval mode (reward 0, no diagnostics)."""
        config = dict(config or {})
        mode = config.get("mode", "train")
        if mode not in ("closed", "train"):
            raise ValueError("mode must be 'closed' or 'train'")
        inner = _team_config(config)
        inner["mode"] = "eval" if mode == "closed" else "train"
        if config.get("episode_dir"):
            inner["episode_dir"] = str(config["episode_dir"])
        obs, _ = self.env.reset(seed, inner)
        self.started = time.monotonic()
        res = obs["result"]
        first = {"task": res["task"], "manifest": res["manifest"], "policy": res["policy"],
                 "remaining_steps": obs["steps_left"]}
        return first, {}

    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        """One action ``{"name": ..., "args": {...}}``; every call before the end costs a step."""
        if not self.env.done and time.monotonic() - self.started > self.time_limit:
            obs, reward, term, trunc, info = self.env.force_truncate()
            return self._obs(None, obs), reward, term, trunc, info
        name, inner = None, {"action": None}
        if isinstance(action, dict) and set(action) <= {"name", "args"} and isinstance(action.get("name"), str):
            args = action.get("args", {})
            name = action["name"]
            inner = {**args, "action": name} if isinstance(args, dict) and "action" not in args \
                else {"action": name, "_bad_args": True}
        obs, reward, term, trunc, info = self.env.step(inner)
        return self._obs(name, obs), reward, term, trunc, info

    @staticmethod
    def _obs(name: str | None, obs: dict) -> dict:
        res = obs["result"]
        if res is not None:
            if name == "list_records":
                res = {"records": res["records"], "next_cursor": res["next_cursor"]}
            elif name == "get_record":
                res = res["record"]
            elif name == "get_document":
                res = res["document"]
            elif name == "calculator":
                res = res["value"]
            elif name == "submit":
                res = {"accepted": True}
        return {"result": res, "error": _error(obs["error"]), "remaining_steps": obs["steps_left"]}


def make_env() -> JudgeEnv:
    """A fresh environment object (the jury calls reset before every episode)."""
    return JudgeEnv()


def score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict:
    """Grade ``findings`` against the episode truth; invalid structure -> return -1, metrics null."""
    files = read_files(episode_dir)
    public = parse_public(files)
    truth = json.loads(files["private/truth.json"])
    res = grade(truth, findings, Store(public).ids, int(inspection_steps), tolerances(public["policy"]))
    if not res.valid:
        sys.stderr.write(f"grader: {truth['episode_id']}: findings rejected: {res.reason}\n")
        return {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None,
                "return": -1.0}
    return {"tp": res.tp, "fp": res.fp, "fn": res.fn, "precision": res.precision, "recall": res.recall,
            "f1": res.f1, "return": res.reward}
