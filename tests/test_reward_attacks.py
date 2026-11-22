"""12 обязательных проверок устойчивости награды с точными числами."""
import copy

import pytest

from conftest import SMALL, burn
from finaudit.env.core import FinAuditEnv
from finaudit.policies.flag_all import FlagAllPolicy
from finaudit.policies.oracle import OraclePolicy


def submit(env, findings):
    return env.step({"action": "submit", "findings": {"episode_id": env.truth["episode_id"], "findings": findings}})


def oracle_findings(env, duplicate=False):
    return OraclePolicy(env.truth, duplicate=duplicate).findings()


def test_oracle_beats_silence(env_err, err_dir):
    burn(env_err, 30)
    _, r_oracle, *_ = submit(env_err, oracle_findings(env_err))
    assert r_oracle == pytest.approx(0.94)
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(err_dir)})
    burn(env, 30)
    _, r_silence, *_ = submit(env, [])
    assert r_silence == -1.0 and r_oracle > r_silence


def test_silence_beats_false_accusation(env_clean, clean_dir):
    k = 12
    burn(env_clean, k)
    _, r_silence, _, _, info = submit(env_clean, [])
    assert r_silence == pytest.approx(1 - 0.002 * k) and info["f1"] == 1.0
    inv = env_clean.store.tables["invoices"][0]
    accusation = [{"type": "PERIOD_CUTOFF", "affected_ids": [inv["invoice_id"]],
                   "claimed_amount_minor": 1, "currency": "KZT", "evidence_ids": [inv["doc_id"]],
                   "explanation": "x"}]
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(clean_dir)})
    _, r_accuse, _, _, info = submit(env, accusation)
    assert r_accuse == -1.0 and info["f1"] == 0.0 and r_silence > r_accuse


def test_duplicates_no_gain(env_err, err_dir):
    _, r_dup, _, _, info = submit(env_err, oracle_findings(env_err, duplicate=True))
    assert info["f1"] == pytest.approx(0.667, abs=1e-3) and info["fp"] == info["tp"]
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(err_dir)})
    _, r_oracle, *_ = submit(env, oracle_findings(env))
    assert r_dup < r_oracle and r_dup == pytest.approx(2 * (2 / 3) - 1, abs=1e-6)


def test_flag_all_is_bad():
    rewards = []
    for seed in range(20):
        env = FinAuditEnv()
        obs, _ = env.reset(1000 + seed, copy.deepcopy(SMALL))
        pol = FlagAllPolicy()
        pol.reset(obs)
        done = False
        while not done:
            obs, r, t, tr, _ = env.step(pol.act(obs))
            done = t or tr
        rewards.append(r)
    assert sum(rewards) / len(rewards) <= -0.5


def test_step_cost_small(err_dir):
    out = []
    for steps in (10, 60):
        env = FinAuditEnv()
        env.reset(0, {"episode_dir": str(err_dir)})
        burn(env, steps)
        out.append(submit(env, oracle_findings(env))[1])
    assert out[0] - out[1] == pytest.approx(0.10, abs=1e-9)


def test_guessed_ids(env_err):
    fs = oracle_findings(env_err)
    fs[0]["evidence_ids"] = fs[0]["evidence_ids"] + ["D-ZZZZZZ"]
    _, _, _, _, info = submit(env_err, fs)
    assert info["fp"] == 1 and info["tp"] == len(fs) - 1


def test_guessed_affected_ids(env_err):
    fs = oracle_findings(env_err)
    fs[0]["affected_ids"] = ["INV-ZZZZZZ"]
    _, _, _, _, info = submit(env_err, fs)
    assert info["fp"] == 1 and info["fn"] == 1


def test_unsupported_evidence(env_err):
    fs = oracle_findings(env_err)
    fs[0]["evidence_ids"] = fs[0]["evidence_ids"][:-1]
    _, _, _, _, info = submit(env_err, fs)
    assert info["fp"] == 1 and info["fn"] == 1


def test_wrong_currency(env_err):
    fs = oracle_findings(env_err)
    fs[0]["currency"] = "GBP" if fs[0]["currency"] != "GBP" else "JPY"
    _, _, _, _, info = submit(env_err, fs)
    assert info["fp"] == 1 and info["fn"] == 1


def test_tolerance_edges(env_err):
    issue = sorted(env_err.truth["issues"], key=lambda i: -i["expected_amount_minor"])[0]
    tol = env_err.tol[issue["type"]]
    assert env_err.tol == env_err.policy_doc["amount_tolerance_minor"] and tol == 0
    # чистая проверка оценщика на реальной ошибке
    from finaudit.grader.grader import grade
    for delta, tp in ((tol, 1), (-tol, 1), (tol + 1, 0), (-(tol + 1), 0)):
        f = {"type": issue["type"], "affected_ids": issue["affected_ids"],
             "claimed_amount_minor": issue["expected_amount_minor"] + delta, "currency": issue["currency"],
             "evidence_ids": issue["evidence_sets"][0], "explanation": ""}
        res = grade({"episode_id": env_err.truth["episode_id"], "issues": [issue]},
                    {"episode_id": env_err.truth["episode_id"], "findings": [f]}, env_err.store.ids, 0,
                    env_err.tol)
        assert res.tp == tp, delta


def test_resubmit(env_err):
    _, r1, t1, _, info1 = submit(env_err, oracle_findings(env_err))
    obs, r2, t2, tr2, info2 = submit(env_err, [])
    assert obs["error"]["code"] == "EPISODE_DONE" and r2 == 0.0 and t2 and not tr2
    assert env_err.last_grade.reward == r1 == 1.0


MALFORMED = [
    lambda e: [],
    lambda e: {"episode_id": e, "findings": [], "extra": 1},
    lambda e: {"episode_id": e},
    lambda e: {"episode_id": "ep-000000000000", "findings": []},
    lambda e: {"episode_id": e, "findings": {}},
    lambda e: {"episode_id": e, "findings": [GOOD] * 31},
    lambda e: {"episode_id": e, "findings": [{k: v for k, v in GOOD.items() if k != "explanation"}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "note": "x"}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "type": 5}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "affected_ids": []}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "affected_ids": [1]}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "claimed_amount_minor": 10.0}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "claimed_amount_minor": True}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "claimed_amount_minor": -5}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "currency": None}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "evidence_ids": ["D-1"] * 11}]},
    lambda e: {"episode_id": e, "findings": [{**GOOD, "explanation": "x" * 1001}]},
    lambda e: {"episode_id": e, "findings": ["not an object"]},
]
GOOD = {"type": "FX_CONVERSION", "affected_ids": ["INV-1"], "claimed_amount_minor": 1, "currency": "KZT",
        "evidence_ids": [], "explanation": ""}


def test_unknown_type_or_currency_string_is_fp_not_crash(env_err, err_dir):
    fs = oracle_findings(env_err)
    for change in ({"type": "OTHER"}, {"currency": "US"}, {"type": fs[0]["type"].lower()},
                   {"currency": " " + fs[0]["currency"]}):
        env = FinAuditEnv()
        env.reset(0, {"episode_dir": str(err_dir)})
        bad = [{**fs[0], **change}] + fs[1:]
        _, _, term, _, info = submit(env, bad)
        assert term and info["fp"] == 1 and info["fn"] == 1 and info["tp"] == len(fs) - 1, change


@pytest.mark.parametrize("make", MALFORMED)
def test_malformed(err_dir, make):
    assert len(MALFORMED) >= 12
    env = FinAuditEnv()
    env.reset(0, {"episode_dir": str(err_dir)})
    obs, reward, term, trunc, _ = env.step({"action": "submit", "findings": make(env.truth["episode_id"])})
    assert reward == -1.0 and term and obs["error"]["code"] == "INVALID_FINDINGS"


def test_timeout(env_clean):
    burn(env_clean, 99)
    obs, reward, term, trunc, info = env_clean.step({"action": "list_records", "table": "fx"})
    assert trunc and not term and info["inspection_steps"] == 100
    assert reward == pytest.approx(0.8)  # документированное свойство: пустой ответ на чистой компании


def test_oracle_perfect_on_50_seeds():
    for seed in range(50):
        env = FinAuditEnv()
        env.reset(500 + seed, copy.deepcopy(SMALL))
        _, reward, term, _, info = submit(env, oracle_findings(env))
        assert term and info["f1"] == 1.0 and reward == 1.0, seed
