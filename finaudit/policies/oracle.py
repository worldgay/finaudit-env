"""Oracle (только для оценщика): читает truth и отправляет каждую ошибку с её первым набором доказательств."""
from __future__ import annotations

from finaudit.policies.base import finding

GRADER_ONLY = True


class OraclePolicy:
    """Верхняя граница; никогда не должен работать как процесс агента (ему нужен truth.json)."""

    name = "oracle"

    def __init__(self, truth: dict, duplicate: bool = False) -> None:
        self.truth = truth
        self.duplicate = duplicate

    def reset(self, observation: dict) -> None:
        """Готовить нечего."""

    def findings(self) -> list[dict]:
        """Один вывод на ошибку truth (два при ``duplicate``)."""
        out = [finding(i["type"], i["affected_ids"], i["expected_amount_minor"], i["currency"],
                       i["evidence_sets"][0], "reference answer") for i in self.truth["issues"]]
        return out + out if self.duplicate else out

    def act(self, observation: dict) -> dict:
        """Отправляет сразу."""
        return {"action": "submit",
                "findings": {"episode_id": self.truth["episode_id"], "findings": self.findings()}}
