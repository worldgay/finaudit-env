"""reconciler: a deliberately naive reconciliation baseline.

Reads all invoices and payments, then as much of the ledger as the budget allows, and flags:
* duplicates: same direction/entity/currency/total/line items, issued <= 3 days apart (UTC dates);
* cut-off: invoice whose UTC date is outside the period but is booked (ignores the company time zone);
* allocation: refs vs AR/AP rows of the payment (exact only for base-currency payments, or rows missing).
It never checks FX conversions. Its blind spots are intentional: time zones, FX, split payments.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from finaudit.policies.base import finding, run_stdio
from finaudit.util.canon import dumps

ORDER = ("invoices", "payments", "ledger")


def _utc_day(ts: str) -> date:
    return datetime.fromisoformat(ts).astimezone(timezone.utc).date()


class ReconcilerPolicy:
    """Simple sweep-and-compare auditor."""

    name = "reconciler"

    def reset(self, observation: dict) -> None:
        """Start a new episode."""
        m = observation["result"]["manifest"]
        self.episode_id, self.base = m["episode_id"], m["base_currency"]
        self.start, self.end = date.fromisoformat(m["period_start"]), date.fromisoformat(m["period_end"])
        self.data: dict[str, list[dict]] = {t: [] for t in ORDER}
        self.stage, self.cursor, self.ledger_complete = 0, None, False
        self.started = False

    def _absorb(self, obs: dict) -> None:
        res = obs.get("result") if obs.get("ok") else None
        if not isinstance(res, dict) or "records" not in res:
            return
        self.data[res["table"]].extend(res["records"])
        self.cursor = res["next_cursor"]
        if self.cursor is None:
            if res["table"] == "ledger":
                self.ledger_complete = True
            self.stage += 1

    def act(self, observation: dict) -> dict:
        """List tables in order; submit when done or when one step is left."""
        if self.started:
            self._absorb(observation)
        self.started = True
        if self.stage >= len(ORDER) or observation.get("steps_left", 100) <= 1:
            return {"action": "submit", "findings": {"episode_id": self.episode_id,
                                                     "findings": self.findings()[:30]}}
        return {"action": "list_records", "table": ORDER[self.stage], "cursor": self.cursor, "limit": 50}

    # ------------------------------------------------------------------ analysis
    def _principal(self) -> dict[str, dict]:
        return {r["invoice_id"]: r for r in self.data["ledger"]
                if r["invoice_id"] and r["payment_id"] is None and r["account"] in ("AR", "AP")}

    def findings(self) -> list[dict]:
        """All findings this baseline believes in."""
        principal = self._principal()
        return self._duplicates(principal) + self._cutoff(principal) + self._allocation()

    def _duplicates(self, principal: dict[str, dict]) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for inv in self.data["invoices"]:
            if inv["invoice_id"] in principal:
                key = dumps([inv["direction"], inv["entity_id"], inv["currency"], inv["total_minor"],
                             inv["line_items"]])
                groups.setdefault(key, []).append(inv)
        out = []
        for members in groups.values():
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    if abs((_utc_day(a["issued_at"]) - _utc_day(b["issued_at"])).days) <= 3:
                        ev = [a["doc_id"], b["doc_id"], principal[a["invoice_id"]]["row_id"],
                              principal[b["invoice_id"]]["row_id"]]
                        out.append(finding("DUPLICATE_INVOICE", [a["invoice_id"], b["invoice_id"]],
                                           b["total_minor"], a["currency"], ev,
                                           "same counterparty, amount and lines"))
        return out

    def _cutoff(self, principal: dict[str, dict]) -> list[dict]:
        out = []
        for inv in self.data["invoices"]:
            row = principal.get(inv["invoice_id"])
            day = _utc_day(inv["issued_at"])
            if row and not self.start <= day <= self.end:
                out.append(finding("PERIOD_CUTOFF", [inv["invoice_id"]], row["debit_minor"] + row["credit_minor"],
                                   self.base, [inv["doc_id"], row["row_id"]], "issued outside the period"))
        return out

    def _allocation(self) -> list[dict]:
        docs = {i["invoice_id"]: i["doc_id"] for i in self.data["invoices"]}
        by_pay: dict[str, list[dict]] = {}
        for r in self.data["ledger"]:
            if r["payment_id"]:
                by_pay.setdefault(r["payment_id"], []).append(r)
        out = []
        for pay in self.data["payments"]:
            rows = by_pay.get(pay["payment_id"], [])
            if not rows and not self.ledger_complete:
                continue
            for ref in pay["invoice_refs"]:
                gap = self._gap(pay, ref, rows)
                if gap and ref["invoice_id"] in docs:
                    ev = [pay["doc_id"], docs[ref["invoice_id"]]] + [r["row_id"] for r in rows]
                    out.append(finding("PAYMENT_ALLOCATION", [ref["invoice_id"], pay["payment_id"]], gap,
                                       pay["currency"], ev, "payment not fully allocated"))
        return out

    def _gap(self, pay: dict, ref: dict, rows: list[dict]) -> int:
        incoming = pay["direction"] == "incoming"
        acct = "AR" if incoming else "AP"
        alloc = [r for r in rows if r["invoice_id"] == ref["invoice_id"] and r["account"] == acct]
        if not alloc:
            return abs(ref["amount_minor"])
        if pay["currency"] != self.base:
            return 0  # would need FX rates; this baseline does not look them up
        signed = sum((r["credit_minor"] - r["debit_minor"]) if incoming else (r["debit_minor"] - r["credit_minor"])
                     for r in alloc)
        return abs(ref["amount_minor"] - signed)


if __name__ == "__main__":
    raise SystemExit(run_stdio(ReconcilerPolicy()))
