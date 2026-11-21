"""`make report`: build REPORT.md from runs/jury/summary.json (measured numbers only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTACK_LABELS = {
    "oracle": "oracle (reference answer, 0 steps)",
    "oracle_each_finding_twice": "oracle, every finding submitted twice",
    "oracle_each_finding_twice_f1": "  … its F1",
    "oracle_guessed_evidence": "oracle with guessed (non-existent) evidence ids",
    "oracle_partial_evidence": "oracle with one evidence id dropped",
    "oracle_wrong_currency": "oracle with the wrong currency",
    "oracle_amount_off_tol_plus_1": "oracle with amount off by tolerance + 1",
    "oracle_10_minus_60_steps": "reward(10 steps) − reward(60 steps), same answer",
    "flag_all": "flag every document × every type (≤ 30)",
    "silence_clean": "empty answer on clean companies (0 steps)",
    "silence_with_errors": "empty answer on companies with errors",
    "false_accusation_clean": "one invented finding on a clean company",
}


def _policy_table(s: dict) -> list[str]:
    out = ["| Policy | Mean reward | Mean F1 | Precision (micro) | Recall (micro) | Steps | TP / FP / FN | Mean s | Max s |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, p in s["policies"].items():
        out.append(f"| {name} | {p['mean_reward']:+.3f} | {p['mean_f1']:.3f} | {p['micro_precision']:.3f} | "
                   f"{p['micro_recall']:.3f} | {p['mean_steps']:.1f} | {p['tp']} / {p['fp']} / {p['fn']} | "
                   f"{p['mean_seconds']:.3f} | {p['max_seconds']:.3f} |")
    return out


def _group_table(s: dict) -> list[str]:
    groups = list(next(iter(s["policies"].values()))["by_group"])
    out = ["| Policy | " + " | ".join(f"{g} reward / F1" for g in groups) + " |",
           "|---|" + "---:|" * len(groups)]
    for name, p in s["policies"].items():
        cells = [f"{p['by_group'][g]['mean_reward']:+.3f} / {p['by_group'][g]['mean_f1']:.3f}" for g in groups]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return out


def _failure_section(s: dict) -> list[str]:
    f = s["reconciler_failures"]
    out = ["| Type | Issues | Found (TP) | Missed (FN) | Recall |", "|---|---:|---:|---:|---:|"]
    for typ, n in f.get("issues", {}).items():
        tp = f.get("tp", {}).get(typ, 0)
        out.append(f"| {typ} | {n} | {tp} | {f.get('fn', {}).get(typ, 0)} | {tp / n:.2f} |")
    out += ["", "Why issues were missed (measured per issue from the public data):", ""]
    out += [f"- {k} — **{v}**" for k, v in f.get("fn_reason", {}).items()]
    out += ["", "Why findings were false positives:", ""]
    out += [f"- {k} — **{v}**" for k, v in f.get("fp_reason", {}).items()] or ["- none"]
    return out


def build(summary: dict) -> str:
    """Render the report markdown."""
    s = summary
    c, r = s["checks"], s["resources"]
    lines = ["# REPORT — FinAudit RL environment v" + s["env_version"], "",
             "All numbers below are measured by `make jury` and copied from `runs/jury/summary.json` by "
             "`make report`. No model was trained; the policies are fixed baselines.", "",
             f"Setup: {s['n_episodes']} freshly generated episodes ({', '.join(f'{v} {k}' for k, v in s['groups'].items())}), "
             f"{s['issues_total']} hidden issues in total, every policy run in **eval mode** (env-server and agent "
             "in separate processes; reward hidden from the agent and read from grader_log.jsonl).", "",
             "## Baseline policies", ""] + _policy_table(s) + [
                 "", "Precision/recall are micro-averaged over all 20 episodes (per-episode P and R are 0 by "
                 "definition when their denominator is 0, e.g. an empty answer on a clean company, which would make "
                 "plain means misleading). Steps = steps used including submit.",
                 "", "### By episode group", ""] + _group_table(s)
    lines += ["", "## Jury-style checks", "",
              f"- Oracle minimum reward: **{c['oracle_min_reward']}** (required ≥ 0.9)",
              f"- Ranking oracle > reconciler > random_explorer ≥ flag_all: **{c['ranking_ok']}**",
              f"- flag_all mean reward ≤ −0.5: **{c['flag_all_mean_le_-0.5']}**",
              f"- Reconciler F1 strictly between flag_all and oracle: **{c['reconciler_f1_strictly_between']}**",
              f"- Paired checks (shuffle + rename every id → same oracle reward, same issue count, verify OK): "
              f"**{s['paired']['passed']}/{s['paired']['total']}**",
              f"- Replays (same seed → identical sha256 of every file; same policy seed → identical trajectory "
              f"bytes and reward): **{s['replay']['passed']}/{s['replay']['total']}**", "",
              "## Failure analysis of the reconciler baseline", ""] + _failure_section(s)
    lines += ["", "## Reward attacks (measured on the same episodes, train mode)", "",
              "| Attack | Mean reward |", "|---|---:|"]
    lines += [f"| {ATTACK_LABELS.get(k, k)} | {v:+.6g} |" for k, v in s["attacks"].items()]
    lines += ["", "## Resources", "",
              f"- Whole `make jury` run: {r['total_seconds']} s; slowest single episode (incl. process start): "
              f"{r['max_episode_seconds']} s (limit 60 s).",
              f"- Peak RSS: orchestrator {r['peak_rss_mb_self']} MB, largest child process {r['peak_rss_mb_children']} MB.",
              "- `tests/test_limits.py`: largest episode (≈2000 ledger rows, ≈200 documents, 12 issues) — generation "
              "+ 100 steps + grading < 5 s and < 500 MB.", "",
              "## Limitations", "", "See the *Honest limitations* section of DESIGN.md.", ""]
    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    summary = json.loads((ROOT / "runs" / "jury" / "summary.json").read_text(encoding="utf-8"))
    (ROOT / "REPORT.md").write_text(build(summary), encoding="utf-8")
    sys.stdout.write("report: REPORT.md written\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
