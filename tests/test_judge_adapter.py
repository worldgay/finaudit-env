"""judge_adapter.py против контрактного блока организаторов C01-C20 (docs/CHECKS.txt)."""
import json
import time
from pathlib import Path

import pytest

import judge_adapter as ja
from conftest import SMALL
from finaudit.policies.oracle import OraclePolicy

SEED_C, SEED_E = 8, 7


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("judge")
    ja.generate_episode(SEED_C, {**SMALL, "clean": True}, str(root / "C"))
    ja.generate_episode(SEED_E, {**SMALL, "interactions": {"I1": 1, "I2": 1}}, str(root / "E"))
    return {"C": root / "C", "E": root / "E"}


def truth(d):
    return json.loads((Path(d) / "private" / "truth.json").read_text(encoding="utf-8"))


def opened(d, mode="closed"):
    env = ja.make_env()
    obs, info = env.reset(0, {"mode": mode, "episode_dir": str(d)})
    return env, obs, info


def act(env, name, **args):
    return env.step({"name": name, "args": args})


def first_row(env, table="ledger"):
    return act(env, "list_records", table=table, cursor=None, limit=1)[0]["result"]["records"][0]


def test_generate_layout_and_determinism(dirs, tmp_path):
    names = sorted(p.relative_to(dirs["E"]).as_posix() for p in dirs["E"].rglob("*") if p.is_file())
    assert names == ["private/generation.json", "private/provenance.json", "private/truth.json",
                     "public/fx.csv", "public/invoices.jsonl", "public/ledger.csv", "public/manifest.json",
                     "public/payments.jsonl", "public/policy.json"]
    ja.generate_episode(SEED_E, {"team_config": {**SMALL, "interactions": {"I1": 1, "I2": 1}}}, str(tmp_path))
    for n in names:
        assert (tmp_path / n).read_bytes() == (dirs["E"] / n).read_bytes(), n


def test_c01_c02_reset(dirs):
    env, obs, info = opened(dirs["C"])
    json.dumps([obs, info])
    assert set(obs) == {"task", "manifest", "policy", "remaining_steps"} and obs["remaining_steps"] == 100
    text = json.dumps([obs, info])
    assert "truth" not in text and "seed" not in text and "issue_id" not in text


def test_c03_manifest_matches_data(dirs):
    env, obs, _ = opened(dirs["C"])
    m = obs["manifest"]
    for key in ("schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone",
                "counts", "rounding"):
        assert key in m, key
    for table in ja.TABLES:
        n, cursor = 0, None
        while True:
            res = act(env, "list_records", table=table, cursor=cursor, limit=50)[0]["result"]
            n += len(res["records"])
            cursor = res["next_cursor"]
            if cursor is None:
                break
        assert n == m["counts"][table], table


def test_c04_step_tuple(dirs):
    env, *_ = opened(dirs["C"])
    obs, reward, term, trunc, info = act(env, "list_records", table="ledger", cursor=None, limit=50)
    json.dumps([obs, reward, info])
    assert isinstance(term, bool) and isinstance(trunc, bool) and reward == 0
    assert set(obs) == {"result", "error", "remaining_steps"} and obs["remaining_steps"] == 99
    assert set(obs["result"]) == {"records", "next_cursor"} and obs["error"] is None


def test_c05_c06_pagination(dirs):
    env, obs, _ = opened(dirs["E"])
    total = obs["manifest"]["counts"]["ledger"]
    assert total >= 101
    seen, cursor, cursors = [], None, []
    while True:
        res = act(env, "list_records", table="ledger", cursor=cursor, limit=50)[0]["result"]
        assert len(res["records"]) <= 50
        seen += [r["row_id"] for r in res["records"]]
        cursor = res["next_cursor"]
        if cursor is None:
            break
        cursors.append(cursor)
    assert len(seen) == len(set(seen)) == total
    a = act(env, "list_records", table="ledger", cursor=cursors[0], limit=50)[0]["result"]
    b = act(env, "list_records", table="ledger", cursor=cursors[0], limit=50)[0]["result"]
    assert a == b


def test_c07_c08_record_and_document(dirs):
    env, *_ = opened(dirs["C"])
    row = first_row(env)
    assert act(env, "get_record", table="ledger", id=row["row_id"])[0]["result"] == row
    inv = first_row(env, "invoices")
    doc = act(env, "get_document", doc_id=inv["doc_id"])[0]["result"]
    assert doc == inv


def test_c09_c10_calculator(dirs):
    env, *_ = opened(dirs["C"])
    assert act(env, "calculator", expression="0.1+0.2")[0]["result"] == "0.3"
    obs = act(env, "calculator", expression="open('/etc/passwd').read()")[0]
    assert obs["result"] is None and obs["error"]["code"] == "BAD_EXPRESSION"


def test_c11_to_c14_bounded_errors(dirs):
    env, *_ = opened(dirs["C"])
    o1 = act(env, "get_record", table="ledger", id="L-ZZZZZZ")[0]
    o2 = act(env, "get_document", doc_id="D-ZZZZZZ")[0]
    o3 = env.step({"name": "drop_table", "args": {}})[0]
    o4 = env.step("not an object")[0]
    o5 = env.step({"name": "calculator", "args": "1+1"})[0]
    assert [o["error"]["code"] for o in (o1, o2, o3, o4, o5)] == \
        ["NOT_FOUND", "NOT_FOUND", "UNKNOWN_ACTION", "UNKNOWN_ACTION", "BAD_ARGS"]
    assert [o["remaining_steps"] for o in (o1, o2, o3, o4, o5)] == [99, 98, 97, 96, 95]
    obs = act(env, "list_records", table="ledger", cursor=None, limit=1)[0]
    assert obs["error"] is None and obs["remaining_steps"] == 94 and len(obs["result"]["records"]) == 1


def test_c15_c19_submit_closed(dirs):
    t = truth(dirs["E"])
    env, *_ = opened(dirs["E"])
    rewards = [act(env, "calculator", expression="2*3")[1] for _ in range(3)]
    findings = {"episode_id": t["episode_id"], "findings": OraclePolicy(t).findings()}
    obs, reward, term, trunc, info = act(env, "submit", findings=findings)
    assert rewards == [0, 0, 0] and reward == 0 and term and not trunc
    assert obs["result"] == {"accepted": True} and set(info) == {"steps_used"}
    assert env.env.last_grade.reward == pytest.approx(1 - 0.002 * 3) and env.env.last_grade.tp == len(t["issues"])
    after = act(env, "submit", findings={"episode_id": t["episode_id"], "findings": []})
    assert after[0]["error"]["code"] == "EPISODE_DONE" and env.env.last_grade.tp == len(t["issues"])


def test_train_mode_returns_terminal_reward(dirs):
    t = truth(dirs["E"])
    env, *_ = opened(dirs["E"], mode="train")
    _, reward, term, *_ = act(env, "submit", findings={"episode_id": t["episode_id"],
                                                       "findings": OraclePolicy(t).findings()})
    assert term and reward == 1.0


def test_invalid_submit_is_bounded(dirs):
    env, *_ = opened(dirs["E"])
    obs, reward, term, *_ = act(env, "submit", findings={"episode_id": "x", "findings": "nope"})
    assert term and reward == 0 and obs["result"] is None and obs["error"]["code"] == "INVALID_FINDINGS"
    assert env.env.last_grade.reward == -1.0


def test_c16_submit_as_action_100(dirs):
    t = truth(dirs["C"])
    env, *_ = opened(dirs["C"])
    for _ in range(99):
        assert not act(env, "calculator", expression="1")[2]
    obs, _, term, trunc, _ = act(env, "submit", findings={"episode_id": t["episode_id"], "findings": []})
    assert obs["result"] == {"accepted": True} and term and not trunc
    assert env.env.last_grade.inspection_steps == 99


def test_c17_hundred_inspections_truncate(dirs):
    env, *_ = opened(dirs["E"])
    for i in range(100):
        obs, _, term, trunc, _ = act(env, "calculator", expression="1")
    assert trunc and not term and env.env.last_grade.tp == 0
    late = act(env, "submit", findings={"episode_id": truth(dirs["E"])["episode_id"], "findings": []})
    assert late[0]["error"]["code"] == "EPISODE_DONE" and env.env.last_grade.tp == 0


def test_c18_time_limit_truncates(dirs):
    env = ja.JudgeEnv(time_limit=0.05)
    env.reset(0, {"mode": "closed", "episode_dir": str(dirs["E"])})
    act(env, "calculator", expression="1")
    time.sleep(0.1)
    obs, reward, term, trunc, _ = act(env, "calculator", expression="1")
    assert trunc and not term and reward == 0 and obs["error"]["code"] == "EPISODE_DONE"
    assert env.env.last_grade.tp == 0 and env.env.last_grade.valid


def test_c20_no_truth_in_any_observation(dirs):
    t = truth(dirs["E"])
    secrets = {i["issue_id"] for i in t["issues"]} | {"truth.json", "provenance", "/app", "private"}
    env, obs, info = opened(dirs["E"])
    seen = [json.dumps([obs, info])]
    for table in ja.TABLES:
        cursor = None
        while True:
            o = act(env, "list_records", table=table, cursor=cursor, limit=50)
            seen.append(json.dumps(o))
            cursor = o[0]["result"]["next_cursor"]
            if cursor is None:
                break
    seen.append(json.dumps(act(env, "get_record", table="../private", id="truth")))
    seen.append(json.dumps(act(env, "get_document", doc_id="../private/truth.json")))
    blob = "\n".join(seen)
    assert not [s for s in secrets if s in blob]


def test_score_episode(dirs):
    t = truth(dirs["E"])
    good = {"episode_id": t["episode_id"], "findings": OraclePolicy(t).findings()}
    res = ja.score_episode(str(dirs["E"]), good, 10)
    assert res == {"tp": len(t["issues"]), "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0,
                   "return": pytest.approx(0.98)}
    bad = ja.score_episode(str(dirs["E"]), {"episode_id": t["episode_id"], "findings": [{}]}, 10)
    assert bad["return"] == -1.0 and all(bad[k] is None for k in ("tp", "fp", "fn", "precision", "recall", "f1"))
    empty_clean = ja.score_episode(str(dirs["C"]), {"episode_id": truth(dirs["C"])["episode_id"], "findings": []}, 0)
    assert empty_clean["f1"] == 1.0 and empty_clean["return"] == 1.0
