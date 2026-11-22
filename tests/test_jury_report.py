"""jury / analysis / attacks / report / demo on a tiny spec."""
import json

from finaudit.attacks import measure_attacks
from finaudit.jury import run_jury
from finaudit.report import build

SIZE = {"size": {"ledger": [200, 400], "documents": [20, 60]}}


def test_attacks_exact(err_dir, clean_dir):
    a = measure_attacks([err_dir, clean_dir])
    assert a["oracle"] == 1.0 and a["silence_clean"] == 1.0 and a["silence_with_errors"] == -1.0
    assert a["oracle_each_finding_twice"] == 0.333333 and a["oracle_each_finding_twice_f1"] == 0.666667
    assert a["oracle_10_minus_60_steps"] == 0.1 and a["flag_all"] == -1.0 and a["false_accusation_clean"] == -1.0
    for k in ("guessed_evidence", "partial_evidence", "wrong_currency", "amount_off_tol_plus_1"):
        assert a[f"oracle_{k}"] == -1.0


def test_mini_jury_and_report(tmp_path):
    spec = {"config_version": "1.0", "perm_seed_base": 1, "policy_seed": 2, "groups": [
        {"name": "clean", "config": "configs/clean.json", "overrides": SIZE, "seeds": [11]},
        {"name": "interactions", "config": "configs/default.json",
         "overrides": {**SIZE, "interactions": {"I1": 1, "I2": 1}}, "seeds": [12]}]}
    path = tmp_path / "jury.json"
    path.write_text(json.dumps(spec))
    s = run_jury(path, tmp_path / "out")
    assert s["n_episodes"] == 2 and s["paired"]["passed"] == 2 and s["replay"]["passed"] == 2
    assert s["policies"]["oracle"]["min_reward"] == 1.0
    assert (tmp_path / "out" / "summary.json").exists()
    fails = s["reconciler_failures"]
    assert sum(fails.get("tp", {}).values()) + sum(fails.get("fn", {}).values()) == s["issues_total"]
    md = build(s)
    assert "| oracle | +1.000 | 1.000 |" in md and "Парные проверки" in md and "2/2" in md


def test_demo_runs(capsys):
    from finaudit.demo import main
    assert main() == 0
    out = capsys.readouterr().out
    assert '"f1":1.0' in out and "identical sha256 of all files: True" in out
