"""Each error type on its own: exactly one issue, right amount/currency, reachable evidence."""
import collections
import json

import pytest

from conftest import SMALL
from finaudit.env.core import FinAuditEnv
from finaudit.generator.episode_io import parse_public
from finaudit.generator.generate import generate_episode
from finaudit.generator.reference_audit import reference_audit

TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")


def only(typ: str) -> dict:
    cfg = {**SMALL, "errors": {t: {"count": 1 if t == typ else 0} for t in TYPES},
           "interactions": {"I1": 0, "I2": 0}}
    return cfg


def fetch(env: FinAuditEnv, ident: str) -> bool:
    if ident.startswith("fx:"):
        obs, *_ = env.step({"action": "get_record", "table": "fx", "id": ident})
    elif ident.startswith("L-"):
        obs, *_ = env.step({"action": "get_record", "table": "ledger", "id": ident})
    else:
        obs, *_ = env.step({"action": "get_document", "doc_id": ident})
    return obs["ok"]


@pytest.mark.parametrize("typ", TYPES)
def test_single_type(typ):
    variants = collections.Counter()
    for seed in range(40):
        ep = generate_episode(seed, only(typ))
        truth = json.loads(ep.files["private/truth.json"])
        pub = parse_public(ep.files)
        assert [i["type"] for i in truth["issues"]] == [typ], seed
        issue = truth["issues"][0]
        found = reference_audit(pub)
        assert len(found) == 1 and found[0]["expected_amount_minor"] == issue["expected_amount_minor"]
        base = pub["manifest"]["base_currency"]
        docs = {d[k]: d for d in pub["invoices"] for k in ("invoice_id",)}
        docs.update({d["payment_id"]: d for d in pub["payments"]})
        if typ == "DUPLICATE_INVOICE":
            assert issue["currency"] == docs[issue["affected_ids"][0]]["currency"]
            assert issue["expected_amount_minor"] == docs[issue["affected_ids"][0]]["total_minor"]
        elif typ == "PAYMENT_ALLOCATION":
            pid = next(a for a in issue["affected_ids"] if a.startswith("PAY-"))
            assert issue["currency"] == docs[pid]["currency"] and issue["expected_amount_minor"] > 0
        else:
            assert issue["currency"] == base and issue["expected_amount_minor"] > 0
        assert issue["affected_ids"] == sorted(issue["affected_ids"])
        prov = json.loads(ep.files["private/provenance.json"])["injections"][0]
        variants[_variant(prov)] += 1
        variants[_side(pub, issue)] += 1
        if seed < 5:
            from finaudit.generator.episode_io import write_files
            import tempfile
            d = write_files(ep.files, tempfile.mkdtemp())
            env = FinAuditEnv()
            env.reset(0, {"episode_dir": str(d)})
            assert all(fetch(env, i) for ev in issue["evidence_sets"] for i in ev)
    _expect_variants(typ, variants)


def _variant(prov: dict) -> str:
    fields = {(c["table"], c["field"]) for c in prov["changes"]}
    if prov["injector"] == "payment_allocation":
        if any(c["field"] == "*" and c["after"] is None for c in prov["changes"]):
            return "alloc-c"
        if ("ledger", "account") in fields:
            return "alloc-b"
        return "alloc-a"
    return prov["injector"]


def _side(pub: dict, issue: dict) -> str:
    inv = {i["invoice_id"]: i for i in pub["invoices"]}
    first = next((a for a in issue["affected_ids"] if a in inv), None)
    return f"side-{inv[first]['direction']}" if first else "side-payment"


def _expect_variants(typ: str, variants: collections.Counter) -> None:
    if typ == "PAYMENT_ALLOCATION":
        assert variants["alloc-a"] and variants["alloc-b"] and variants["alloc-c"], variants
    if typ in ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "PERIOD_CUTOFF"):
        assert variants["side-receivable"] and variants["side-payable"], variants


def test_types_toggle_independently():
    cfg = {**SMALL, "errors": {t: {"count": 0} for t in TYPES}, "interactions": {"I1": 0, "I2": 0}}
    for seed in range(10):
        truth = json.loads(generate_episode(seed, cfg).files["private/truth.json"])
        assert truth["issues"] == []
    cfg["errors"]["FX_CONVERSION"] = {"count": 2}
    cfg["errors"]["PERIOD_CUTOFF"] = {"count": 2}
    for seed in range(10):
        truth = json.loads(generate_episode(seed, cfg).files["private/truth.json"])
        assert sorted(i["type"] for i in truth["issues"]) == ["FX_CONVERSION"] * 2 + ["PERIOD_CUTOFF"] * 2


def test_fx_variants_cover_utc_shift_inverse():
    seen = set()
    for seed in range(60):
        ep = generate_episode(seed, only("FX_CONVERSION"))
        pub = parse_public(ep.files)
        issue = json.loads(ep.files["private/truth.json"])["issues"][0]
        seen.add("payment" if issue["affected_ids"][0].startswith("PAY-") else "invoice")
        amount = issue["expected_amount_minor"]
        row_id = next(e for e in issue["evidence_sets"][0] if e.startswith("L-"))
        row = next(r for r in pub["ledger"] if r["row_id"] == row_id)
        seen.add("huge" if amount > (row["debit_minor"] + row["credit_minor"]) // 2 else "small")
    assert {"payment", "invoice", "huge", "small"} <= seen
