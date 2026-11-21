"""Policy interface and the stdin/stdout agent loop used in eval mode."""
from __future__ import annotations

import json
import sys
from typing import Protocol

from finaudit.util.canon import dumps


class Policy(Protocol):
    """A policy sees only observations and returns actions."""

    name: str

    def reset(self, observation: dict) -> None:
        """Receive the first observation of an episode."""

    def act(self, observation: dict) -> dict:
        """Return the next action."""


def empty_submit(episode_id: str) -> dict:
    """A submit action with no findings."""
    return {"action": "submit", "findings": {"episode_id": episode_id, "findings": []}}


def finding(typ: str, affected: list[str], amount: int, currency: str, evidence: list[str],
            explanation: str = "") -> dict:
    """Build one finding dict."""
    return {"type": typ, "affected_ids": sorted(set(affected)), "claimed_amount_minor": int(amount),
            "currency": currency, "evidence_ids": sorted(set(evidence))[:10],
            "explanation": explanation[:1000]}


def run_stdio(policy: Policy) -> int:
    """Agent process loop: read one observation per line, write one action per line."""
    first = True
    for line in sys.stdin:
        obs = json.loads(line)
        if first:
            policy.reset(obs)
            first = False
        sys.stdout.write(dumps(policy.act(obs)) + "\n")
        sys.stdout.flush()
    return 0
