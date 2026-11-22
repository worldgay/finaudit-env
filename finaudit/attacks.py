"""Reward attacks measured on real episodes (train mode, exact numbers for REPORT.txt)."""
from __future__ import annotations

import copy
import statistics
from pathlib import Path

from finaudit.env.core import FinAuditEnv
from finaudit.policies.oracle import OraclePolicy
from finaudit.runner import run_episode_train


def _submit(episode_dir: Path, findings: list[dict], burn: int = 0) -> tuple[float, float]:
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(episode_dir)})
    for _ in range(burn):
        env.step({"action": "calculator", "expression": "1+1"})
    _, reward, _, _, info = env.step({"action": "submit", "findings": {"episode_id": env.truth["episode_id"],
                                                                         "findings": findings}})
    return reward, info["f1"]


def _oracle(episode_dir: Path) -> tuple[list[dict], dict]:
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(episode_dir)})
    return OraclePolicy(env.truth).findings(), env.truth


def _mutated(findings: list[dict], how: str) -> list[dict]:
    out = copy.deepcopy(findings)
    for f in out:
        if how == "guessed_evidence":
            f["evidence_ids"] = [e[:-1] + ("B" if e[-1] != "B" else "C") for e in f["evidence_ids"]]
        elif how == "partial_evidence":
            f["evidence_ids"] = f["evidence_ids"][:-1]
        elif how == "wrong_currency":
            f["currency"] = "GBP" if f["currency"] != "GBP" else "JPY"
        elif how == "amount_off_tol_plus_1":
            f["claimed_amount_minor"] += 1  # published tolerance is 0 for every type
    return out


def measure_attacks(dirs: list[Path]) -> dict:
    """Mean reward of each attack over the episodes it applies to."""
    acc: dict[str, list[float]] = {}

    def add(key: str, value: float) -> None:
        """Record one measurement."""
        acc.setdefault(key, []).append(value)

    for d in dirs:
        findings, truth = _oracle(d)
        clean = not truth["issues"]
        add("silence_clean" if clean else "silence_with_errors", _submit(d, [])[0])
        add("flag_all", run_episode_train(d, "flag_all")["reward"])
        if clean:
            fake = {"type": "PERIOD_CUTOFF", "affected_ids": ["INV-000000"], "claimed_amount_minor": 1,
                    "currency": "KZT", "evidence_ids": [], "explanation": ""}
            add("false_accusation_clean", _submit(d, [fake])[0])
            continue
        add("oracle", _submit(d, findings)[0])
        reward, f1 = _submit(d, findings + findings)
        add("oracle_each_finding_twice", reward)
        add("oracle_each_finding_twice_f1", f1)
        for how in ("guessed_evidence", "partial_evidence", "wrong_currency", "amount_off_tol_plus_1"):
            add(f"oracle_{how}", _submit(d, _mutated(findings, how))[0])
        add("oracle_10_minus_60_steps", _submit(d, findings, 10)[0] - _submit(d, findings, 60)[0])
    return {k: round(statistics.mean(v), 6) for k, v in sorted(acc.items())}
