"""flag_all: читает первую страницу счетов и платежей, помечает каждый документ x каждый тип."""
from __future__ import annotations

from finaudit.policies.base import finding, run_stdio

TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")


class FlagAllPolicy:
    """Структурно валидный, но неразборчивый ответ (до 30 выводов)."""

    name = "flag_all"

    def reset(self, observation: dict) -> None:
        """Запоминает ID эпизода."""
        self.episode_id = observation["result"]["manifest"]["episode_id"]
        self.phase = 0
        self.docs: list[dict] = []

    def act(self, observation: dict) -> dict:
        """Два шага чтения списков, затем submit."""
        if self.phase > 0 and observation.get("ok"):
            self.docs.extend(observation["result"]["records"])
        self.phase += 1
        if self.phase == 1:
            return {"action": "list_records", "table": "invoices", "cursor": None, "limit": 50}
        if self.phase == 2:
            return {"action": "list_records", "table": "payments", "cursor": None, "limit": 50}
        out = []
        for doc in self.docs:
            ident = doc.get("invoice_id") or doc.get("payment_id")
            amount = abs(doc.get("total_minor", doc.get("amount_minor", 0)))
            for typ in TYPES:
                if len(out) < 30:
                    out.append(finding(typ, [ident], amount, doc["currency"], [doc["doc_id"]]))
        return {"action": "submit", "findings": {"episode_id": self.episode_id, "findings": out}}


if __name__ == "__main__":
    raise SystemExit(run_stdio(FlagAllPolicy()))
