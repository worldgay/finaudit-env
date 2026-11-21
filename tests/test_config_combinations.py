"""New parameter combinations (as a closed check would use): every base currency x time zone."""
import json

import pytest

from finaudit.env.core import FinAuditEnv
from finaudit.generator.generate import generate_episode, normalize_config
from finaudit.generator.verify import verify_files
from finaudit.generator.world import TZ_POOL
from finaudit.policies.oracle import OraclePolicy

SMALL = {"size": {"ledger": [200, 400], "documents": [20, 70]}}


@pytest.mark.parametrize("base", ["KZT", "USD", "EUR", "GBP", "JPY"])
@pytest.mark.parametrize("tz", TZ_POOL)
def test_every_base_and_zone(base, tz):
    for seed, extra in ((1, {}), (2, {"clean": True}), (3, {"interactions": {"I1": 1, "I2": 1}})):
        ep = generate_episode(seed, {**SMALL, "base_currency": base, "timezone": tz, **extra})
        assert verify_files(ep.files) == []
        m = json.loads(ep.files["public/manifest.json"])
        assert m["base_currency"] == base and m["timezone"] == tz


def test_single_foreign_currency_and_jpy_amounts():
    for seed in range(5):
        ep = generate_episode(seed, {**SMALL, "base_currency": "JPY", "foreign_currencies": ["KZT"]})
        assert verify_files(ep.files) == []


def test_lenient_config_forms():
    cfg = normalize_config({"errors": {"FX_CONVERSION": 2, "PERIOD_CUTOFF": {"count": [1, 1], "rate": 0.5}},
                            "seed": 9, "episode_dir": None, "max_steps": 100, "description": "jury"})
    assert cfg["errors"]["FX_CONVERSION"] == {"count": 2} and cfg["errors"]["PERIOD_CUTOFF"] == {"count": [1, 1]}
    assert "seed" not in cfg and "max_steps" not in cfg
    with pytest.raises(ValueError):
        normalize_config({"errors": {"FX_CONVERSION": -1}})
    with pytest.raises(ValueError):
        normalize_config({"base_currency": "XXX"})


def test_reset_seed_none_and_max_errors():
    env = FinAuditEnv()
    a, _ = env.reset(None, SMALL)
    b, _ = FinAuditEnv().reset(0, SMALL)
    assert a == b
    env.reset(5, {"errors": {t: 3 for t in ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION",
                                            "PERIOD_CUTOFF")}, "interactions": {"I1": 1, "I2": 1}})
    assert len(env.truth["issues"]) == 12
    _, reward, *_ = env.step(OraclePolicy(env.truth).act({}))
    assert reward == 1.0
