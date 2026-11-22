"""Измеренный разбор сбоев прогона политики (используется jury.py / REPORT.txt)."""
from __future__ import annotations

import collections
import json
from datetime import date, timezone
from pathlib import Path

from finaudit.generator.episode_io import parse_public, read_files
from finaudit.grader.matcher import normalize
from finaudit.util.timeutil import local_date, parse_date, parse_ts


def _utc(ts: str) -> date:
    return parse_ts(ts).astimezone(timezone.utc).date()


def _fn_reason(issue: dict, pub: dict) -> str:
    m = pub["manifest"]
    inv = {i["invoice_id"]: i for i in pub["invoices"]}
    pay = {p["payment_id"]: p for p in pub["payments"]}
    start, end = parse_date(m["period_start"]), parse_date(m["period_end"])
    typ = issue["type"]
    if typ == "FX_CONVERSION":
        return "FX conversions are not checked by this baseline"
    if typ == "PERIOD_CUTOFF":
        doc = inv[issue["affected_ids"][0]]
        if start <= _utc(doc["issued_at"]) <= end:
            return "issued after period end in local time, but its UTC date is inside the period"
        return "other"
    if typ == "DUPLICATE_INVOICE":
        a, b = (inv[i] for i in issue["affected_ids"])
        if abs((_utc(a["issued_at"]) - _utc(b["issued_at"])).days) > 3:
            return "copies more than 3 UTC days apart"
        return "other"
    p = pay[next(i for i in issue["affected_ids"] if i in pay)]
    if p["currency"] != m["base_currency"]:
        return "partial allocation of a foreign-currency payment (needs the FX rate)"
    return "other"


def _fp_reason(f: dict, pub: dict) -> str:
    m = pub["manifest"]
    inv = {i["invoice_id"]: i for i in pub["invoices"]}
    start, end = parse_date(m["period_start"]), parse_date(m["period_end"])
    if f["type"] == "PERIOD_CUTOFF" and f["affected_ids"][0] in inv:
        doc = inv[f["affected_ids"][0]]
        if start <= local_date(doc["issued_at"], m["timezone"]) <= end:
            return "in-period document whose UTC date falls outside the period (time-zone trap)"
    if f["type"] == "PAYMENT_ALLOCATION":
        return "allocation flagged without a real gap (split / partial view)"
    return "other"


def analyse(episode_dir: str | Path, findings: list[dict], matches: list[list]) -> dict:
    """Классифицирует ложноотрицательные и ложноположительные выводы одной оценённой отправки."""
    files = read_files(episode_dir)
    pub = parse_public(files)
    truth = json.loads(files["private/truth.json"])
    matched_issues = {m[1] for m in matches}
    matched_findings = {m[0] for m in matches}
    out = {"fn": collections.Counter(), "fn_reason": collections.Counter(),
           "fp": collections.Counter(), "fp_reason": collections.Counter(),
           "tp": collections.Counter(), "issues": collections.Counter()}
    for issue in truth["issues"]:
        out["issues"][issue["type"]] += 1
        if issue["issue_id"] in matched_issues:
            out["tp"][issue["type"]] += 1
        else:
            out["fn"][issue["type"]] += 1
            out["fn_reason"][f"{issue['type']}: {_fn_reason(issue, pub)}"] += 1
    for k, f in enumerate(findings):
        if k not in matched_findings:
            n = normalize(f)
            norm = {"type": n.type, "affected_ids": list(n.affected_ids)}
            out["fp"][n.type] += 1
            out["fp_reason"][f"{n.type}: {_fp_reason(norm, pub)}"] += 1
    return out


def merge(parts: list[dict]) -> dict:
    """Суммирует несколько результатов analyse() в обычные словари."""
    total: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for part in parts:
        for key, counter in part.items():
            total[key].update(counter)
    return {k: dict(sorted(v.items())) for k, v in sorted(total.items())}
