"""I1 and I2: two causally linked issues each, amounts after both changes, order in provenance."""
import json

from conftest import SMALL
from finaudit.generator.episode_io import parse_public
from finaudit.generator.generate import generate_episode
from finaudit.util.timeutil import local_date, parse_ts, zone

NONE = {t: {"count": 0} for t in ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")}


def _load(seed, interactions):
    ep = generate_episode(seed, {**SMALL, "errors": NONE, "interactions": interactions})
    return (json.loads(ep.files["private/truth.json"]), json.loads(ep.files["private/provenance.json"]),
            parse_public(ep.files))


def test_i1():
    for seed in range(25):
        truth, prov, pub = _load(seed, {"I1": 1, "I2": 0})
        assert sorted(i["type"] for i in truth["issues"]) == ["FX_CONVERSION", "PAYMENT_ALLOCATION"]
        assert {i["scenario"] for i in truth["issues"]} == {"I1"}
        fx = next(i for i in truth["issues"] if i["type"] == "FX_CONVERSION")
        alloc = next(i for i in truth["issues"] if i["type"] == "PAYMENT_ALLOCATION")
        pid = fx["affected_ids"][0]
        assert pid.startswith("PAY-") and pid in alloc["affected_ids"]
        pay = next(p for p in pub["payments"] if p["payment_id"] == pid)
        m = pub["manifest"]
        local = parse_ts(pay["timestamp"]).astimezone(zone(m["timezone"]))
        assert local.date().isoformat() == m["period_end"] and local.hour >= 21
        assert pay["currency"] != m["base_currency"] and alloc["currency"] == pay["currency"]
        order = {p["issue_id"]: p["order"] for p in prov["injections"]}
        assert order[fx["issue_id"]] < order[alloc["issue_id"]]
        rows = [r for r in pub["ledger"] if r["payment_id"] == pid]
        assert set(alloc["evidence_sets"][0]) >= {r["row_id"] for r in rows}  # evidence after both changes


def test_i2():
    for seed in range(25):
        truth, prov, pub = _load(seed, {"I1": 0, "I2": 1})
        assert sorted(i["type"] for i in truth["issues"]) == ["DUPLICATE_INVOICE", "PAYMENT_ALLOCATION"]
        dup = next(i for i in truth["issues"] if i["type"] == "DUPLICATE_INVOICE")
        alloc = next(i for i in truth["issues"] if i["type"] == "PAYMENT_ALLOCATION")
        pid = next(a for a in alloc["affected_ids"] if a.startswith("PAY-"))
        orig = next(a for a in alloc["affected_ids"] if a.startswith("INV-"))
        copy_id = next(a for a in dup["affected_ids"] if a != orig)
        assert orig in dup["affected_ids"]
        pay = next(p for p in pub["payments"] if p["payment_id"] == pid)
        assert [r["invoice_id"] for r in pay["invoice_refs"]] == [orig]
        booked_to = {r["invoice_id"] for r in pub["ledger"] if r["payment_id"] == pid and r["account"] == "AR"}
        assert booked_to == {orig, copy_id}
        half = pay["amount_minor"] // 2
        assert abs(alloc["expected_amount_minor"] - half) <= max(2, pay["amount_minor"] // 5)
        order = {p["issue_id"]: p["order"] for p in prov["injections"]}
        assert order[dup["issue_id"]] < order[alloc["issue_id"]]


def test_both_with_other_errors():
    for seed in range(15):
        ep = generate_episode(seed, {**SMALL, "interactions": {"I1": 1, "I2": 1}})
        truth = json.loads(ep.files["private/truth.json"])
        scen = [i["scenario"] for i in truth["issues"]]
        assert scen.count("I1") == 2 and scen.count("I2") == 2 and len(truth["issues"]) <= 12
