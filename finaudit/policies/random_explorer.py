"""random_explorer: K ~ U[5, 60] случайных допустимых действий, затем 0-3 случайных (валидных) вывода."""
from __future__ import annotations

import argparse
import random

from finaudit.policies.base import finding, run_stdio

TABLES = ("ledger", "invoices", "payments", "fx")
TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")


class RandomExplorerPolicy:
    """Исследует случайно со своим ГПСЧ с seed; никогда не читает закрытые данные."""

    name = "random_explorer"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def reset(self, observation: dict) -> None:
        """Начинает новый эпизод."""
        res = observation["result"]
        self.episode_id = res["manifest"]["episode_id"]
        self.base = res["manifest"]["base_currency"]
        self.budget = self.rng.randint(5, 60)
        self.steps = 0
        self.record_ids: dict[str, list[str]] = {t: [] for t in TABLES}
        self.cursors: dict[str, list[str]] = {t: [] for t in TABLES}
        self.doc_ids: list[str] = []
        self.refs: list[str] = []
        self.amounts: list[int] = []
        self.currencies: list[str] = [self.base]

    def _absorb_record(self, table: str, rec: dict) -> None:
        key = {"ledger": "row_id", "invoices": "doc_id", "payments": "doc_id", "fx": "fx_id"}[table]
        self.record_ids[table].append(rec[key])
        if table in ("invoices", "payments"):
            self.doc_ids.append(rec["doc_id"])
            self.currencies.append(rec["currency"])
        for k in ("invoice_id", "payment_id"):
            if rec.get(k):
                self.refs.append(rec[k])
        for k in ("total_minor", "amount_minor", "debit_minor", "credit_minor"):
            if isinstance(rec.get(k), int) and rec[k] > 0:
                self.amounts.append(rec[k])

    def _absorb(self, obs: dict) -> None:
        res = obs.get("result") if obs.get("ok") else None
        if not isinstance(res, dict):
            return
        if "records" in res:
            for rec in res["records"]:
                self._absorb_record(res["table"], rec)
            if res.get("next_cursor"):
                self.cursors[res["table"]].append(res["next_cursor"])
        elif "record" in res:
            self._absorb_record(res["table"], res["record"])

    def _random_action(self) -> dict:
        r = self.rng
        kind = r.choice(["list", "list", "get", "doc", "calc"])
        table = r.choice(TABLES)
        if kind == "get" and self.record_ids[table]:
            return {"action": "get_record", "table": table, "id": r.choice(self.record_ids[table])}
        if kind == "doc" and self.doc_ids:
            return {"action": "get_document", "doc_id": r.choice(self.doc_ids)}
        if kind == "calc":
            return {"action": "calculator", "expression": f"{r.randint(1, 10 ** 6)} * {r.randint(1, 999)} / 100"}
        cursor = r.choice(self.cursors[table]) if self.cursors[table] and r.random() < 0.6 else None
        return {"action": "list_records", "table": table, "cursor": cursor, "limit": 50}

    def _submit(self) -> dict:
        r = self.rng
        out = []
        evidence_pool = [i for ids in self.record_ids.values() for i in ids]
        for _ in range(r.randint(0, 3)):
            affected = r.sample(self.refs, min(len(self.refs), r.randint(1, 2))) or ["INV-000000"]
            amount = r.choice(self.amounts) if self.amounts else 0
            evidence = r.sample(evidence_pool, min(len(evidence_pool), r.randint(1, 3)))
            out.append(finding(r.choice(TYPES), affected, amount, r.choice(self.currencies), evidence))
        return {"action": "submit", "findings": {"episode_id": self.episode_id, "findings": out}}

    def act(self, observation: dict) -> dict:
        """Случайное исследование, затем submit."""
        if self.steps > 0:
            self._absorb(observation)
        self.steps += 1
        if self.steps > self.budget or observation.get("steps_left", 100) <= 1:
            return self._submit()
        return self._random_action()


def main() -> int:
    """Точка входа процесса агента."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    return run_stdio(RandomExplorerPolicy(ap.parse_args().seed))


if __name__ == "__main__":
    raise SystemExit(main())
