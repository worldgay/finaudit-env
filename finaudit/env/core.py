"""FinAuditEnv: Gymnasium-style reset/step over one audit episode (JSON in, JSON out)."""
from __future__ import annotations

import json
from pathlib import Path

from finaudit import ENV_VERSION
from finaudit.env.errors import EnvError
from finaudit.env.store import Store
from finaudit.env.tools import HANDLERS, PAGE_SIZE, check_keys
from finaudit.generator.episode_io import parse_public, read_files
from finaudit.grader.grader import GradeResult, empty_findings, grade
from finaudit.grader.matcher import tolerances
from finaudit.grader.validate_findings import (FINDING_TYPES, MAX_EVIDENCE, MAX_EXPLANATION,
                                               MAX_FINDINGS)
from finaudit.util.canon import dumps

MAX_STEPS = 100
TASK_TEXT = (
    "You are auditing one company for one calendar month. The ledger (base currency, integer minor "
    "units), invoices, payments and daily FX rates are available through the tools. Find bookkeeping "
    "discrepancies of the listed finding types and submit them once with action 'submit'. Each finding "
    "names the affected invoice_id/payment_id values, the amount in minor units in the currency fixed "
    "for its type (see policy.finding_currency_by_type), and evidence_ids: record ids (ledger row_id, "
    "document doc_id, fx id 'fx:DATE:SRC:TGT') that together prove it. Every step costs 0.002 reward; "
    "you have 100 steps including submit."
)


def _obs(result: object = None, error: EnvError | None = None, steps_left: int = 0) -> dict:
    return {"ok": error is None, "result": result,
            "error": None if error is None else {"code": error.code, "message": error.message},
            "steps_left": steps_left}


class FinAuditEnv:
    """One environment instance; ``reset`` fully replaces all episode state."""

    def __init__(self, grader_log: str | Path | None = None) -> None:
        self.grader_log = Path(grader_log) if grader_log else None
        self.policy_name = "unknown"
        self._loaded = False

    # ------------------------------------------------------------------ lifecycle
    def reset(self, seed: int | None = 0, config: dict | None = None) -> tuple[dict, dict]:
        """Start an episode from ``config['episode_dir']`` or generate one from (seed, config).

        ``seed=None`` means seed 0 (the environment never draws entropy from the OS).
        """
        config = dict(config or {})
        seed = 0 if seed is None else int(seed)
        self.mode = config.get("mode", "train")
        if self.mode not in ("train", "eval"):
            raise ValueError("mode must be train or eval")
        if config.get("episode_dir"):
            files = read_files(config["episode_dir"])
        else:
            from finaudit.generator.generate import generate_episode
            files = generate_episode(seed, config).files
        public = parse_public(files)
        self.truth = json.loads(files["private/truth.json"])
        self.manifest = public["manifest"]
        self.policy_doc = public["policy"]
        self.tol = tolerances(self.policy_doc)
        self.store = Store(public)
        self.steps_used = 0
        self.done = False
        self.flags = (False, False)
        self.last_grade: GradeResult | None = None
        self._loaded = True
        result = {"task": TASK_TEXT, "manifest": self.manifest, "policy": self.policy_doc,
                  "tables": ["ledger", "invoices", "payments", "fx"],
                  "finding_types": list(FINDING_TYPES),
                  "limits": {"max_steps": MAX_STEPS, "page_size": PAGE_SIZE,
                             "max_findings": MAX_FINDINGS, "max_evidence": MAX_EVIDENCE,
                             "max_explanation": MAX_EXPLANATION}}
        return json.loads(dumps(_obs(result, steps_left=MAX_STEPS))), {"env_version": ENV_VERSION}

    @property
    def steps_left(self) -> int:
        """Remaining step budget."""
        return MAX_STEPS - self.steps_used

    # ------------------------------------------------------------------ step
    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        """Apply one action; every call before the end consumes one step."""
        if not self._loaded:
            raise RuntimeError("call reset() first")
        if self.done:
            err = EnvError("EPISODE_DONE", "episode has finished")
            return _obs(error=err, steps_left=self.steps_left), 0.0, *self.flags, self._info(None)
        self.steps_used += 1
        try:
            if not isinstance(action, dict):
                raise EnvError("BAD_ARGS", "action must be a JSON object")
            name = check_keys(action)
            if name == "submit":
                return self._submit(action["findings"])
            obs = _obs(HANDLERS[name](self.store, action), steps_left=self.steps_left)
        except EnvError as err:
            obs = _obs(error=err, steps_left=self.steps_left)
        if self.steps_used >= MAX_STEPS:
            return self._finish(obs, empty_findings(self.truth["episode_id"]), truncated=True)
        return obs, 0.0, False, False, self._info(None)

    def force_truncate(self) -> tuple[dict, float, bool, bool, dict]:
        """Wall-clock limit reached (called by the runner): grade the empty answer."""
        if self.done:
            err = EnvError("EPISODE_DONE", "episode has finished")
            return _obs(error=err, steps_left=self.steps_left), 0.0, *self.flags, self._info(None)
        obs = _obs(error=EnvError("EPISODE_DONE", "time limit reached"), steps_left=self.steps_left)
        return self._finish(obs, empty_findings(self.truth["episode_id"]), truncated=True)

    # ------------------------------------------------------------------ internals
    def _submit(self, findings: object) -> tuple[dict, float, bool, bool, dict]:
        inspection = self.steps_used - 1
        result = grade(self.truth, findings, self.store.ids, inspection, self.tol)
        if not result.valid:
            msg = result.reason if self.mode == "train" else "findings structure rejected"
            obs = _obs(error=EnvError("INVALID_FINDINGS", f"findings rejected: {msg}"),
                       steps_left=self.steps_left)
        else:
            n = len(findings["findings"])  # type: ignore[index]
            obs = _obs({"submitted": True, "n_findings": n}, steps_left=self.steps_left)
        return self._finish(obs, None, truncated=False, result=result)

    def _finish(self, obs: dict, findings: dict | None, truncated: bool,
                result: GradeResult | None = None) -> tuple[dict, float, bool, bool, dict]:
        if result is None:
            result = grade(self.truth, findings, self.store.ids, self.steps_used, self.tol)
        self.done = True
        self.flags = (not truncated, truncated)
        self.last_grade = result
        self._log(result, truncated)
        reward = result.reward if self.mode == "train" else 0.0
        return obs, reward, self.flags[0], self.flags[1], self._info(result)

    def _info(self, result: GradeResult | None) -> dict:
        if self.mode == "eval" or result is None:
            return {"steps_used": self.steps_used}
        return result.agent_info()

    def _log(self, result: GradeResult, truncated: bool) -> None:
        if self.grader_log is None:
            return
        rec = {"episode_id": self.truth["episode_id"], "policy": self.policy_name, "mode": self.mode,
               "truncated": truncated, "steps_used": self.steps_used, "env_version": ENV_VERSION,
               "n_issues": len(self.truth["issues"]), **result.to_dict()}
        self.grader_log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.grader_log, "a", encoding="utf-8") as fh:
            fh.write(dumps(rec) + "\n")
