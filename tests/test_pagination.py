import pytest

from finaudit.env.store import encode_cursor


def _walk(env, table, limit=50):
    seen, cursor, pages = [], None, 0
    while True:
        obs, *_ = env.step({"action": "list_records", "table": table, "cursor": cursor, "limit": limit})
        assert obs["ok"], obs
        recs = obs["result"]["records"]
        assert len(recs) <= 50
        seen.extend(recs)
        pages += 1
        cursor = obs["result"]["next_cursor"]
        if cursor is None:
            return seen, pages


@pytest.mark.parametrize("table,key", [("invoices", "doc_id"), ("payments", "doc_id"), ("fx", "fx_id")])
def test_full_walk_no_gaps_no_repeats(env_err, table, key):
    seen, _ = _walk(env_err, table)
    ids = [r[key] for r in seen]
    assert len(ids) == len(set(ids)) == env_err.first_obs["result"]["manifest"]["counts"][table]


def test_ledger_walk_in_file_order(env_err):
    seen, pages = _walk(env_err, "ledger", limit=50)
    assert [r["row_id"] for r in seen] == [r["row_id"] for r in env_err.store.tables["ledger"]]
    assert pages == -(-len(seen) // 50)


def test_small_limit(env_err):
    seen, _ = _walk(env_err, "invoices", limit=7)
    assert len(seen) == env_err.first_obs["result"]["manifest"]["counts"]["invoices"]


def test_cursor_stable(env_err):
    a, *_ = env_err.step({"action": "list_records", "table": "ledger"})
    cur = a["result"]["next_cursor"]
    b, *_ = env_err.step({"action": "list_records", "table": "ledger", "cursor": cur})
    c, *_ = env_err.step({"action": "list_records", "table": "ledger", "cursor": cur})
    assert b["result"] == c["result"] and b["result"]["records"][0] != a["result"]["records"][0]


@pytest.mark.parametrize("cursor", ["zzz", "", "eyJ4IjoxfQ", encode_cursor("invoices", 1),
                                    encode_cursor("ledger", 10 ** 6), encode_cursor("ledger", -1)])
def test_bad_cursor(env_err, cursor):
    obs, *_ = env_err.step({"action": "list_records", "table": "ledger", "cursor": cursor})
    assert not obs["ok"] and obs["error"]["code"] == "BAD_CURSOR"


@pytest.mark.parametrize("limit,code", [(51, "LIMIT_TOO_LARGE"), (1000, "LIMIT_TOO_LARGE"), (0, "BAD_ARGS"),
                                        (-1, "BAD_ARGS"), ("5", "BAD_ARGS"), (True, "BAD_ARGS"), (5.0, "BAD_ARGS")])
def test_limits(env_err, limit, code):
    obs, *_ = env_err.step({"action": "list_records", "table": "ledger", "limit": limit})
    assert obs["error"]["code"] == code
