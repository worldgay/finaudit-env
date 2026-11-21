"""Oracle (grader-only): reads truth and submits every issue with its first evidence set."""
from __future__ import annotations

from finaudit.policies.base import finding

GRADER_ONLY = True


class OraclePolicy:
    """Upper bound; must never run as an agent process (it needs truth.json)."""

    name = "oracle"

    def __init__(self, truth: dict, duplicate: bool = False) -> None:
        self.truth = truth
        self.duplicate = duplicate

    def reset(self, observation: dict) -> None:
        """Nothing to prepare."""

    def findings(self) -> list[dict]:
        """One finding per truth issue (twice when ``duplicate``)."""
        out = [finding(i["type"], i["affected_ids"], i["expected_amount_minor"], i["currency"],
                       i["evidence_sets"][0], "reference answer") for i in self.truth["issues"]]
        return out + out if self.duplicate else out

    def act(self, observation: dict) -> dict:
        """Submit immediately."""
        return {"action": "submit",
                "findings": {"episode_id": self.truth["episode_id"], "findings": self.findings()}}
