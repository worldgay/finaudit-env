"""Distractors: >= 3 kinds everywhere, never flagged by the reference auditor."""
import collections
import json

from conftest import SMALL
from finaudit.generator.distractors import KINDS
from finaudit.generator.episode_io import parse_public
from finaudit.generator.generate import generate_episode
from finaudit.generator.reference_audit import reference_audit
from finaudit.util.timeutil import local_date, parse_date


def test_min_three_kinds_and_clean_audit_empty():
    seen = collections.Counter()
    for seed in range(120):
        for cfg in (SMALL, {**SMALL, "clean": True}):
            ep = generate_episode(seed, cfg)
            kinds = json.loads(ep.files["private/provenance.json"])["distractors"]
            assert len(kinds) >= 3 and set(kinds) <= set(KINDS), seed
            seen.update(kinds)
            if cfg.get("clean"):
                assert json.loads(ep.files["private/truth.json"])["issues"] == []
                assert reference_audit(parse_public(ep.files)) == []
    assert set(seen) == set(KINDS), seen


def test_boundary_and_next_month_are_correct():
    hits = 0
    for seed in range(40):
        ep = generate_episode(seed, {**SMALL, "clean": True})
        pub = parse_public(ep.files)
        m = pub["manifest"]
        start, end = parse_date(m["period_start"]), parse_date(m["period_end"])
        booked = {r["invoice_id"] for r in pub["ledger"] if r["invoice_id"] and r["payment_id"] is None}
        for inv in pub["invoices"]:
            local = local_date(inv["issued_at"], m["timezone"])
            literal = parse_date(inv["issued_at"][:10])
            if start <= local <= end and not start <= literal <= end:
                hits += 1
                assert inv["invoice_id"] in booked
            if local > end:
                assert inv["invoice_id"] not in booked
    assert hits >= 10


def test_recurring_same_amount_not_duplicate():
    for seed in range(20):
        pub = parse_public(generate_episode(seed, {**SMALL, "clean": True}).files)
        groups = collections.Counter((i["entity_id"], i["total_minor"]) for i in pub["invoices"])
        assert max(groups.values()) >= 3  # weekly series present
        assert not [f for f in reference_audit(pub) if f["type"] == "DUPLICATE_INVOICE"]
