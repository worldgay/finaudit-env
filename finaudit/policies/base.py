"""Интерфейс политики и цикл агента через stdin/stdout, используемый в режиме eval."""
from __future__ import annotations

import json
import sys
from typing import Protocol

from finaudit.util.canon import dumps


class Policy(Protocol):
    """Политика видит только observations и возвращает действия."""

    name: str

    def reset(self, observation: dict) -> None:
        """Получает первое observation эпизода."""

    def act(self, observation: dict) -> dict:
        """Возвращает следующее действие."""


def empty_submit(episode_id: str) -> dict:
    """Действие submit без выводов."""
    return {"action": "submit", "findings": {"episode_id": episode_id, "findings": []}}


def finding(typ: str, affected: list[str], amount: int, currency: str, evidence: list[str],
            explanation: str = "") -> dict:
    """Собирает словарь одного вывода."""
    return {"type": typ, "affected_ids": sorted(set(affected)), "claimed_amount_minor": int(amount),
            "currency": currency, "evidence_ids": sorted(set(evidence))[:10],
            "explanation": explanation[:1000]}


def run_stdio(policy: Policy) -> int:
    """Цикл процесса агента: читает одно observation на строку, пишет одно действие на строку."""
    first = True
    for line in sys.stdin:
        obs = json.loads(line)
        if first:
            policy.reset(obs)
            first = False
        sys.stdout.write(dumps(policy.act(obs)) + "\n")
        sys.stdout.flush()
    return 0
