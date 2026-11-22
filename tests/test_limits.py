"""Самый большой эпизод: генерация + 100 шагов + оценка < 5 с, память < 500 МБ."""
import resource
import time

from finaudit.env.core import FinAuditEnv

MAX_CFG = {"size": {"ledger": [1900, 2000], "documents": [195, 200]},
           "errors": {t: {"count": 2} for t in ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION",
                                                "PERIOD_CUTOFF")},
           "interactions": {"I1": 1, "I2": 1}}


def test_max_episode_fast_and_small():
    start = time.monotonic()
    env = FinAuditEnv()
    obs, _ = env.reset(123, MAX_CFG)
    m = obs["result"]["manifest"]["counts"]
    assert m["ledger"] >= 1850 and m["documents"] >= 190 and len(env.truth["issues"]) == 12
    cursor = None
    for _ in range(99):
        obs, *_ = env.step({"action": "list_records", "table": "ledger", "cursor": cursor})
        cursor = obs["result"]["next_cursor"] if obs["ok"] else None
    from finaudit.policies.oracle import OraclePolicy
    obs, reward, term, *_ = env.step(OraclePolicy(env.truth).act(obs))
    assert term and reward > 0.7
    assert time.monotonic() - start < 5.0
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 500 * 1024
