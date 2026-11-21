"""verify catches deliberately broken truth / public data."""
import json

import pytest

from conftest import SMALL
from finaudit.generator.generate import generate_episode
from finaudit.generator.verify import verify_files
from finaudit.util.canon import dumps


@pytest.fixture(scope="module")
def files():
    ep = generate_episode(3, {**SMALL, "interactions": {"I1": 1, "I2": 1}})
    assert verify_files(ep.files) == []
    return ep.files


def _with_truth(files, mutate):
    out = dict(files)
    truth = json.loads(files["private/truth.json"])
    mutate(truth)
    out["private/truth.json"] = dumps(truth)
    return out


@pytest.mark.parametrize("mutate", [
    lambda t: t["issues"][0].__setitem__("expected_amount_minor", t["issues"][0]["expected_amount_minor"] + 1),
    lambda t: t["issues"][0].__setitem__("affected_ids", ["INV-ZZZZZZ"]),
    lambda t: t["issues"][0].__setitem__("currency", "GBP" if t["issues"][0]["currency"] != "GBP" else "JPY"),
    lambda t: t["issues"][0].__setitem__("type", "PERIOD_CUTOFF" if t["issues"][0]["type"] != "PERIOD_CUTOFF" else "FX_CONVERSION"),
    lambda t: t["issues"][0]["evidence_sets"][0].__setitem__(0, "D-ZZZZZZ"),
    lambda t: t["issues"][0].__setitem__("evidence_sets", []),
    lambda t: t["issues"].pop(),
    lambda t: t["issues"].append(dict(t["issues"][0], issue_id="iss-ZZZZZZ")),
    lambda t: t.__setitem__("episode_id", "ep-000000000000"),
])
def test_broken_truth_detected(files, mutate):
    assert verify_files(_with_truth(files, mutate))


def test_broken_public_detected(files):
    out = dict(files)
    lines = files["public/ledger.csv"].splitlines()
    cols = lines[1].split(",")
    cols[3] = str(int(cols[3] or 0) + 7) if cols[3] != "0" else cols[3]
    cols[4] = str(int(cols[4]) + 7) if cols[3] == "0" else cols[4]
    lines[1] = ",".join(cols)
    out["public/ledger.csv"] = "\n".join(lines) + "\n"
    problems = verify_files(out)
    assert any("sha mismatch" in p for p in problems) and any("unbalanced" in p for p in problems)


def test_leaky_description_detected(files):
    out = dict(files)
    out["public/invoices.jsonl"] = files["public/invoices.jsonl"].replace("Consulting", "Duplicate", 1) \
        if "Consulting" in files["public/invoices.jsonl"] else files["public/invoices.jsonl"].replace(
            '"description":"', '"description":"error ', 1)
    assert any(p.startswith("leak") for p in verify_files(out))


def _with_prov(files, mutate):
    out = dict(files)
    prov = json.loads(files["private/provenance.json"])
    mutate(prov)
    out["private/provenance.json"] = dumps(prov)
    return out


def _first_field_change(p):
    return next(c for e in p["injections"] for c in e["changes"] if c["field"] in ("debit_minor", "credit_minor"))


@pytest.mark.parametrize("mutate", [
    lambda p: p["injections"].pop(0),
    lambda p: p.__setitem__("injections", []),
    lambda p: _first_field_change(p).__setitem__("before", _first_field_change(p)["before"] + 5),
])
def test_broken_provenance_detected(files, mutate):
    assert verify_files(_with_prov(files, mutate))


def test_revert_gives_clean_books(files):
    from finaudit.generator.episode_io import parse_public
    from finaudit.generator.reference_audit import reference_audit
    from finaudit.generator.revert import pre_error_problems, revert
    pub = parse_public(files)
    prov = json.loads(files["private/provenance.json"])
    assert reference_audit(pub) and pre_error_problems(pub, prov) == []
    assert reference_audit(revert(pub, prov)) == []
