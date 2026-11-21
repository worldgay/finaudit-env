import json

import pytest

from finaudit.generator.episode_io import read_files
from finaudit.generator.transform import transform, transform_files
from finaudit.generator.verify import verify_episode, verify_files
from finaudit.runner import run_episode_train


def test_transform_preserves_oracle_and_verifies(err_dir, tmp_path):
    new_dir = transform(err_dir, 99, tmp_path)
    assert verify_episode(new_dir) == []
    a = run_episode_train(err_dir, "oracle")
    b = run_episode_train(new_dir, "oracle")
    assert a["reward"] == b["reward"] == 1.0 and a["tp"] == b["tp"]


def test_no_old_id_survives(err_dir):
    files = read_files(err_dir)
    new, mapping = transform_files(files, 5)
    public_text = "".join(v for k, v in new.items() if k.startswith("public/")) + new["private/truth.json"] \
        + new["private/provenance.json"]
    old_truth = json.loads(files["private/truth.json"])
    assert all(old not in public_text for old in mapping)
    assert all(i["issue_id"] not in public_text for i in old_truth["issues"])
    assert len(set(mapping.values())) == len(mapping)


def test_issues_map_one_to_one(err_dir):
    files = read_files(err_dir)
    new, mapping = transform_files(files, 6)
    old = json.loads(files["private/truth.json"])["issues"]
    fresh = json.loads(new["private/truth.json"])["issues"]
    key = lambda i: (i["type"], i["expected_amount_minor"], i["currency"], tuple(i["affected_ids"]))
    remapped = sorted((i["type"], i["expected_amount_minor"], i["currency"],
                       tuple(sorted(mapping[a] for a in i["affected_ids"]))) for i in old)
    assert remapped == sorted(key(i) for i in fresh)


def test_order_changes_and_is_deterministic(err_dir):
    files = read_files(err_dir)
    a, _ = transform_files(files, 7)
    b, _ = transform_files(files, 7)
    c, _ = transform_files(files, 8)
    assert a == b and a != c and verify_files(c) == []
    assert a["public/fx.csv"] != files["public/fx.csv"]


@pytest.mark.parametrize("perm_seed", range(5))
def test_clean_transform(clean_dir, tmp_path, perm_seed):
    new_dir = transform(clean_dir, perm_seed, tmp_path)
    assert verify_episode(new_dir) == []
    assert json.loads((new_dir / "private" / "truth.json").read_text())["issues"] == []
