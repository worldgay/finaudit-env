"""`make jury`: симуляция закрытой проверки жюри.

20 новых эпизодов (configs/jury.json: 5 чистых, 5 с I1+I2, 10 смешанных) x 4 политики в режиме eval
(изолированные процессы), 20 парных проверок (transform: награда oracle сохраняется, ошибки сопоставляются 1:1,
verify), 20 повторов (тот же seed -> тот же sha256 каждого файла; те же действия -> те же байты траектории и
награда), измерения атак, ресурсы. Результат: runs/jury/summary.json
"""
from __future__ import annotations

import copy
import json
import resource
import shutil
import statistics
import sys
import time
from pathlib import Path

from finaudit import ENV_VERSION
from finaudit.analysis import analyse, merge
from finaudit.attacks import measure_attacks
from finaudit.generator.episode_io import read_files
from finaudit.generator.generate import generate_episode, generate_to_dir, load_config
from finaudit.generator.transform import transform
from finaudit.generator.verify import verify_episode
from finaudit.runner import POLICIES, ROOT, run_episode_eval, run_episode_train
from finaudit.util.canon import dumps, sha256_bytes, sha256_text, write_json


def _merge_cfg(base: dict, overrides: dict) -> dict:
    cfg = copy.deepcopy(base)
    for k, v in overrides.items():
        cfg[k] = {**cfg[k], **v} if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
    return cfg


def _episodes(spec: dict, out: Path) -> list[dict]:
    eps = []
    for group in spec["groups"]:
        cfg = _merge_cfg(load_config(ROOT / group["config"]), group["overrides"])
        for seed in group["seeds"]:
            d = generate_to_dir(seed, cfg, out)
            eps.append({"group": group["name"], "seed": seed, "config": cfg, "dir": d})
    return eps


def _last_findings(traj_path: Path, eid: str, policy: str) -> list[dict]:
    recs = [json.loads(x) for x in traj_path.read_text().splitlines()]
    acts = [r["action"] for r in recs if r["episode_id"] == eid and r["policy"] == policy
            and isinstance(r["action"], dict) and r["action"].get("action") == "submit"]
    if not acts:
        return []
    f = acts[-1].get("findings")
    return f.get("findings", []) if isinstance(f, dict) and isinstance(f.get("findings"), list) else []


def _policy_stats(rows: list[dict], eps: list[dict]) -> dict:
    groups = sorted({e["group"] for e in eps})
    mean = lambda xs: round(statistics.mean(xs), 4)
    out = {"mean_reward": mean([r["reward"] for r in rows]), "mean_f1": mean([r["f1"] for r in rows]),
           "mean_precision": mean([r["precision"] for r in rows]), "mean_recall": mean([r["recall"] for r in rows]),
           "mean_steps": mean([r["steps_used"] for r in rows]), "min_reward": min(r["reward"] for r in rows),
           "mean_seconds": mean([r["seconds"] for r in rows]), "max_seconds": max(r["seconds"] for r in rows),
           "valid": sum(r["valid"] for r in rows), "truncated": sum(r["truncated"] for r in rows),
           "tp": sum(r["tp"] for r in rows), "fp": sum(r["fp"] for r in rows), "fn": sum(r["fn"] for r in rows)}
    tp, fp, fn = out["tp"], out["fp"], out["fn"]
    out["micro_precision"] = round(tp / (tp + fp), 4) if tp + fp else 0.0
    out["micro_recall"] = round(tp / (tp + fn), 4) if tp + fn else 0.0
    out["by_group"] = {g: {"mean_reward": mean([r["reward"] for r, e in zip(rows, eps) if e["group"] == g]),
                           "mean_f1": mean([r["f1"] for r, e in zip(rows, eps) if e["group"] == g])}
                       for g in groups}
    return out


def _paired(eps: list[dict], out: Path, perm_base: int) -> dict:
    details, passed = [], 0
    for k, e in enumerate(eps):
        t_dir = transform(e["dir"], perm_base + k, out / "episodes")
        problems = verify_episode(t_dir)
        a = run_episode_eval(e["dir"], "oracle", out / "eval", allow_oracle=True)
        b = run_episode_eval(t_dir, "oracle", out / "eval", allow_oracle=True)
        ra, rb = run_episode_train(e["dir"], "reconciler"), run_episode_train(t_dir, "reconciler")
        ok = not problems and a["reward"] == b["reward"] and a["tp"] == b["tp"] and a["n_issues"] == b["n_issues"]
        passed += ok
        details.append({"episode": e["dir"].name, "transformed": t_dir.name, "oracle": [a["reward"], b["reward"]],
                        "reconciler_f1": [ra["f1"], rb["f1"]], "verify_problems": len(problems), "ok": ok})
    return {"passed": passed, "total": len(eps), "details": details}


def _tree_hash(d: Path) -> dict:
    return {str(p.relative_to(d)): sha256_bytes(p.read_bytes()) for p in sorted(d.rglob("*")) if p.is_file()}


def _replays(eps: list[dict], out: Path, policy_seed: int) -> dict:
    passed, details = 0, []
    for e in eps:
        again = generate_to_dir(e["seed"], e["config"], out / "replay")
        same_files = _tree_hash(again) == _tree_hash(e["dir"])
        same_mem = sha256_text(dumps(generate_episode(e["seed"], e["config"]).files)) == \
            sha256_text(dumps(read_files(e["dir"])))
        t1, t2 = out / "replay" / f"{e['dir'].name}-1.jsonl", out / "replay" / f"{e['dir'].name}-2.jsonl"
        r1 = run_episode_train(e["dir"], "random_explorer", t1, policy_seed)
        r2 = run_episode_train(e["dir"], "random_explorer", t2, policy_seed)
        same_traj = sha256_bytes(t1.read_bytes()) == sha256_bytes(t2.read_bytes()) and r1["reward"] == r2["reward"]
        ok = same_files and same_mem and same_traj
        passed += ok
        details.append({"episode": e["dir"].name, "files_sha256_equal": same_files, "trajectory_sha256_equal": same_traj,
                        "ok": ok})
    return {"passed": passed, "total": len(eps), "details": details}


def run_jury(spec_path: Path = ROOT / "configs" / "jury.json", out: Path = ROOT / "runs" / "jury") -> dict:
    """Запускает полную симуляцию и записывает summary.json."""
    started = time.monotonic()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for sub in ("episodes", "eval", "replay"):
        shutil.rmtree(out / sub, ignore_errors=True)
    eps = _episodes(spec, out / "episodes")
    results: dict[str, list[dict]] = {}
    failures = []
    for name in POLICIES:
        rows = []
        for e in eps:
            res = run_episode_eval(e["dir"], name, out / "eval", spec["policy_seed"], allow_oracle=True)
            rows.append(res)
            if name == "reconciler":
                found = _last_findings(out / "eval" / "trajectories.jsonl", res["episode_id"], name)
                failures.append(analyse(e["dir"], found, res["matches"]))
        results[name] = rows
    stats = {n: _policy_stats(rows, eps) for n, rows in results.items()}
    mean = {n: s["mean_reward"] for n, s in stats.items()}
    summary = {
        "env_version": ENV_VERSION, "n_episodes": len(eps),
        "groups": {g["name"]: len(g["seeds"]) for g in spec["groups"]},
        "issues_total": sum(r["n_issues"] for r in results["oracle"]),
        "policies": stats,
        "checks": {"oracle_min_reward": stats["oracle"]["min_reward"],
                   "ranking": ["oracle", "reconciler", "random_explorer", "flag_all"],
                   "ranking_ok": mean["oracle"] > mean["reconciler"] > mean["random_explorer"] >= mean["flag_all"],
                   "flag_all_mean_le_-0.5": mean["flag_all"] <= -0.5,
                   "reconciler_f1_strictly_between": stats["flag_all"]["mean_f1"] < stats["reconciler"]["mean_f1"]
                   < stats["oracle"]["mean_f1"]},
        "paired": _paired(eps, out, spec["perm_seed_base"]),
        "replay": _replays(eps, out, spec["policy_seed"]),
        "reconciler_failures": merge(failures),
        "attacks": measure_attacks([e["dir"] for e in eps]),
        "resources": {"total_seconds": round(time.monotonic() - started, 2),
                      "peak_rss_mb_self": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                      "peak_rss_mb_children": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
                      "max_episode_seconds": max(s["max_seconds"] for s in stats.values())},
    }
    write_json(out / "summary.json", summary)
    return summary


def main() -> int:
    """Точка входа CLI."""
    s = run_jury()
    for name, st in s["policies"].items():
        sys.stdout.write(f"jury: {name:15s} награда={st['mean_reward']:+.3f} f1={st['mean_f1']:.3f} "
                         f"шагов={st['mean_steps']:.1f}\n")
    sys.stdout.write(f"jury: проверки={s['checks']} парные={s['paired']['passed']}/{s['paired']['total']} "
                     f"повторы={s['replay']['passed']}/{s['replay']['total']} "
                     f"время={s['resources']['total_seconds']} с\n")
    ok = (all(v for k, v in s["checks"].items() if isinstance(v, bool)) and s["checks"]["oracle_min_reward"] >= 0.9
          and s["paired"]["passed"] == s["paired"]["total"] and s["replay"]["passed"] == s["replay"]["total"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
