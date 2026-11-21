import json

import pytest

from conftest import burn
from finaudit.env.core import FinAuditEnv
from finaudit.util.validate import errors, load_schema

OBS = load_schema("observation")


def _ok(obs):
    assert not errors(obs, OBS), errors(obs, OBS)
    json.dumps(obs)


def test_reset_shape(err_dir):
    env = FinAuditEnv()
    out = env.reset(0, {"episode_dir": str(err_dir)})
    assert isinstance(out, tuple) and len(out) == 2
    obs, info = out
    _ok(obs)
    json.dumps(info)
    assert obs["ok"] and obs["steps_left"] == 100 and obs["error"] is None
    res = obs["result"]
    assert set(res) == {"task", "manifest", "policy", "tables", "finding_types", "limits"}
    assert res["limits"] == {"max_steps": 100, "page_size": 50, "max_findings": 30, "max_evidence": 10,
                             "max_explanation": 1000}
    assert not errors(res["manifest"], load_schema("manifest"))


def test_step_shape_and_cost(env_err):
    out = env_err.step({"action": "calculator", "expression": "2*3"})
    assert isinstance(out, tuple) and len(out) == 5
    obs, reward, term, trunc, info = out
    _ok(obs)
    json.dumps(info)
    assert obs["result"] == {"value": "6"} and reward == 0.0 and not term and not trunc
    assert obs["steps_left"] == 99
    obs, *_ = env_err.step({"action": "nope"})
    assert obs["steps_left"] == 98 and obs["error"]["code"] == "UNKNOWN_ACTION"


@pytest.mark.parametrize("action,code", [
    ({"action": "nope"}, "UNKNOWN_ACTION"),
    ({"table": "ledger"}, "UNKNOWN_ACTION"),
    ({"action": 5}, "UNKNOWN_ACTION"),
    ("list_records", "BAD_ARGS"),
    (None, "BAD_ARGS"),
    ([1, 2], "BAD_ARGS"),
    ({"action": "list_records"}, "BAD_ARGS"),
    ({"action": "list_records", "table": "ledger", "extra": 1}, "BAD_ARGS"),
    ({"action": "get_record", "table": "ledger"}, "BAD_ARGS"),
    ({"action": "get_record", "table": "ledger", "id": 5}, "BAD_ARGS"),
    ({"action": "list_records", "table": "truth"}, "UNKNOWN_TABLE"),
    ({"action": "list_records", "table": 3}, "BAD_ARGS"),
    ({"action": "get_record", "table": "private", "id": "x"}, "UNKNOWN_TABLE"),
    ({"action": "get_record", "table": "ledger", "id": "L-NOPE00"}, "NOT_FOUND"),
    ({"action": "get_document", "doc_id": "D-NOPE00"}, "NOT_FOUND"),
    ({"action": "get_record", "table": "fx", "id": "fx:1999-01-01:USD:KZT"}, "NOT_FOUND"),
    ({"action": "list_records", "table": "ledger", "cursor": "bad"}, "BAD_CURSOR"),
    ({"action": "list_records", "table": "ledger", "limit": 51}, "LIMIT_TOO_LARGE"),
    ({"action": "calculator", "expression": "2**3"}, "BAD_EXPRESSION"),
    ({"action": "calculator"}, "BAD_ARGS"),
    ({"action": "submit"}, "BAD_ARGS"),
])
def test_error_codes(env_err, action, code):
    obs, reward, term, trunc, info = env_err.step(action)
    _ok(obs)
    assert obs["ok"] is False and obs["result"] is None and obs["error"]["code"] == code
    assert len(obs["error"]["message"]) <= 120 and "/" not in obs["error"]["message"]
    assert reward == 0.0 and not term and not trunc and obs["steps_left"] == 99


def test_get_record_and_document(env_err):
    led = env_err.store.tables["ledger"][0]
    obs, *_ = env_err.step({"action": "get_record", "table": "ledger", "id": led["row_id"]})
    assert obs["result"]["record"] == led
    inv = env_err.store.tables["invoices"][0]
    obs, *_ = env_err.step({"action": "get_document", "doc_id": inv["doc_id"]})
    assert obs["result"] == {"doc_type": "invoice", "document": inv}
    fx = env_err.store.tables["fx"][0]
    obs, *_ = env_err.step({"action": "get_record", "table": "fx", "id": fx["fx_id"]})
    assert obs["result"]["record"]["rate"] == fx["rate"]


def test_agent_cannot_mutate_store(env_err):
    obs, *_ = env_err.step({"action": "list_records", "table": "ledger", "limit": 1})
    obs["result"]["records"][0]["debit_minor"] = -999
    assert env_err.store.tables["ledger"][0]["debit_minor"] != -999


def test_submit_terminates(env_err):
    obs, reward, term, trunc, info = env_err.step(
        {"action": "submit", "findings": {"episode_id": env_err.truth["episode_id"], "findings": []}})
    _ok(obs)
    assert term and not trunc and obs["ok"] and obs["steps_left"] == 99
    assert set(info) == {"precision", "recall", "f1", "tp", "fp", "fn", "inspection_steps"}


def test_hundred_steps_truncate(env_err):
    burn(env_err, 99)
    obs, reward, term, trunc, info = env_err.step({"action": "calculator", "expression": "1"})
    assert trunc and not term and obs["steps_left"] == 0
    assert info["inspection_steps"] == 100 and info["tp"] == 0
    assert reward == -1.0  # errors exist, empty answer


def test_submit_on_step_100_counts(env_clean):
    burn(env_clean, 99)
    obs, reward, term, trunc, info = env_clean.step(
        {"action": "submit", "findings": {"episode_id": env_clean.truth["episode_id"], "findings": []}})
    assert term and not trunc and info["inspection_steps"] == 99 and reward == pytest.approx(1 - 0.198)


def test_episode_done_after_end(env_err):
    burn(env_err, 3)
    sub = {"action": "submit", "findings": {"episode_id": env_err.truth["episode_id"], "findings": []}}
    _, r1, t1, tr1, _ = env_err.step(sub)
    for act in (sub, {"action": "calculator", "expression": "1"}, {"action": "nope"}):
        obs, r, t, tr, info = env_err.step(act)
        assert obs["error"]["code"] == "EPISODE_DONE" and r == 0.0 and (t, tr) == (t1, tr1)
        assert obs["steps_left"] == 96 and info == {"steps_used": 4}


def test_eval_mode_hides_reward(err_dir, tmp_path):
    env = FinAuditEnv(grader_log=tmp_path / "g.jsonl")
    env.reset(0, {"episode_dir": str(err_dir), "mode": "eval"})
    from finaudit.policies.oracle import OraclePolicy
    obs, reward, term, trunc, info = env.step(OraclePolicy(env.truth).act({}))
    assert reward == 0.0 and info == {"steps_used": 1} and term
    assert obs["result"] == {"submitted": True, "n_findings": len(env.truth["issues"])}
    log = [json.loads(x) for x in (tmp_path / "g.jsonl").read_text().splitlines()]
    assert log[0]["reward"] == 1.0 and log[0]["f1"] == 1.0


def test_eval_mode_every_step_zero(err_dir):
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(err_dir), "mode": "eval"})
    for _ in range(100):
        obs, reward, term, trunc, info = env.step({"action": "list_records", "table": "fx"})
        assert reward == 0.0 and set(info) == {"steps_used"}
    assert trunc


def test_eval_invalid_findings_message_is_generic(err_dir):
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(err_dir), "mode": "eval"})
    obs, reward, term, *_ = env.step({"action": "submit", "findings": {"x": 1}})
    assert obs["error"]["code"] == "INVALID_FINDINGS" and reward == 0.0 and term
    assert obs["error"]["message"] == "findings rejected: findings structure rejected"


def test_reset_isolates_state(env_err, clean_dir):
    burn(env_err, 5)
    env_err.step({"action": "submit", "findings": {"episode_id": "x", "findings": []}})
    obs, _ = env_err.reset(0, {"episode_dir": str(clean_dir)})
    assert obs["steps_left"] == 100 and not env_err.done and env_err.truth["issues"] == []
    obs, *_ = env_err.step({"action": "calculator", "expression": "1"})
    assert obs["steps_left"] == 99


def test_force_truncate(env_clean):
    burn(env_clean, 10)
    obs, reward, term, trunc, info = env_clean.force_truncate()
    assert trunc and not term and info["inspection_steps"] == 10 and reward == pytest.approx(0.98)


def test_generated_reset_without_episode_dir():
    env = FinAuditEnv()
    obs, info = env.reset(42, {"size": {"ledger": [200, 300], "documents": [20, 50]}})
    assert obs["result"]["manifest"]["counts"]["ledger"] >= 200 and info == {"env_version": "1.2.0"}


def test_action_schema_accepts_examples():
    schema = load_schema("action")
    for a in ({"action": "list_records", "table": "ledger", "cursor": None, "limit": 50},
              {"action": "get_record", "table": "ledger", "id": "L-8K2M1Q"},
              {"action": "get_document", "doc_id": "D-4H7P0Z"},
              {"action": "calculator", "expression": "(1250000 * 512.3482) / 100"},
              {"action": "submit", "findings": {"episode_id": "ep-1", "findings": []}}):
        assert not errors(a, schema), a
    assert errors({"action": "list_records", "table": "ledger", "limit": 51}, schema)


def test_get_record_aliases(env_err):
    inv = env_err.store.tables["invoices"][0]
    fx = env_err.store.tables["fx"][0]
    a, *_ = env_err.step({"action": "get_record", "table": "invoices", "id": inv["invoice_id"]})
    b, *_ = env_err.step({"action": "get_record", "table": "fx", "id": fx["fx_id"][3:]})
    assert a["result"]["record"] == inv and b["result"]["record"]["fx_id"] == fx["fx_id"]


FUZZ = [{"action": "list_records", "table": t, "cursor": c, "limit": l}
        for t in ("ledger", "fx", "nope", 1) for c in (None, 5) for l in (1, 50, 51, 0)] + [
    {"action": "get_record", "table": "ledger", "id": i} for i in ("", "L-1", 7, "x" * 65)] + [
    {"action": "get_document", "doc_id": "D-1", "x": 1}, {"action": "calculator", "expression": 3},
    {"action": "calculator", "expression": "1+1"}, {"action": "LIST_RECORDS", "table": "ledger"}]
STRUCTURAL = {"UNKNOWN_ACTION", "BAD_ARGS", "UNKNOWN_TABLE", "LIMIT_TOO_LARGE"}


def test_schema_and_env_agree(env_err):
    schema = load_schema("action")
    for a in FUZZ:
        obs, *_ = env_err.step(a)
        structural_error = (not obs["ok"]) and obs["error"]["code"] in STRUCTURAL
        assert structural_error == bool(errors(a, schema)), a


def test_train_invalid_structure_logged(err_dir, tmp_path):
    from finaudit.env.core import FinAuditEnv as Env
    env = Env(grader_log=tmp_path / "g.jsonl")
    env.reset(0, {"episode_dir": str(err_dir), "mode": "train"})
    obs, reward, term, *_ = env.step({"action": "submit", "findings": {"episode_id": "nope", "findings": []}})
    log = json.loads((tmp_path / "g.jsonl").read_text().splitlines()[-1])
    assert reward == -1.0 and term and log["valid"] is False and log["reason"] == "episode_id mismatch"
