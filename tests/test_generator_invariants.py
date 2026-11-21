"""Clean-book invariants and verify on 1000 seeds (small size for speed)."""
import json

from conftest import SMALL
from finaudit import ENV_VERSION
from finaudit.generator.books import check_invariants
from finaudit.generator.generate import build_clean, generate_episode, normalize_config
from finaudit.generator.inject import NoCandidate
from finaudit.generator.verify import verify_files
from finaudit.util.rng import make_rng

N_SEEDS = 1000


def test_clean_books_invariants_1000_seeds():
    cfg = normalize_config(SMALL)
    checked = 0
    for seed in range(N_SEEDS):
        try:
            w, plan, ids, rows = build_clean(make_rng(seed, cfg, ENV_VERSION, 0), cfg)
        except NoCandidate:
            continue
        assert check_invariants(w, rows) == [], seed
        assert sum(r["debit_minor"] for r in rows) == sum(r["credit_minor"] for r in rows)
        assert all(isinstance(r["debit_minor"], int) and isinstance(r["credit_minor"], int) for r in rows)
        checked += 1
    assert checked >= 0.99 * N_SEEDS


def test_verify_passes_1000_seeds():
    attempts = []
    for seed in range(N_SEEDS):
        ep = generate_episode(seed, SMALL)
        assert verify_files(ep.files) == [], seed
        attempts.append(json.loads(ep.files["private/generation.json"])["attempt"])
    assert max(attempts) < 20
    assert attempts.count(0) >= 0.95 * N_SEEDS


def test_sizes_and_formats_default_config():
    for seed in range(15):
        ep = generate_episode(seed)
        m = json.loads(ep.files["public/manifest.json"])
        truth = json.loads(ep.files["private/truth.json"])
        assert 200 <= m["counts"]["ledger"] <= 2000 and 20 <= m["counts"]["documents"] <= 200
        assert 0 <= len(truth["issues"]) <= 12
        fx_line = ep.files["public/fx.csv"].splitlines()[1].split(",")
        assert len(fx_line[3].split(".")[1]) == 6
        inv = json.loads(ep.files["public/invoices.jsonl"].splitlines()[0])
        assert isinstance(inv["total_minor"], int) and inv["issued_at"][-6] in "+-"
