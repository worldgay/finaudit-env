# REPORT — FinAudit RL environment v1.2.0

All numbers below are measured by `make jury` and copied from `runs/jury/summary.json` by `make report`. No model was trained; the policies are fixed baselines.

Setup: 20 freshly generated episodes (5 clean, 5 interactions, 10 mixed), 99 hidden issues in total, every policy run in **eval mode** (env-server and agent in separate processes; reward hidden from the agent and read from grader_log.jsonl).

## Baseline policies

| Policy | Mean reward | Mean F1 | Precision (micro) | Recall (micro) | Steps | TP / FP / FN | Mean s | Max s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flag_all | -1.000 | 0.000 | 0.000 | 0.000 | 3.0 | 0 / 600 / 99 | 0.385 | 0.435 |
| oracle | +1.000 | 1.000 | 1.000 | 1.000 | 1.0 | 99 / 0 / 0 | 0.257 | 0.302 |
| random_explorer | -0.708 | 0.150 | 0.000 | 0.000 | 26.0 | 0 / 24 / 99 | 0.439 | 0.465 |
| reconciler | +0.037 | 0.542 | 0.704 | 0.505 | 27.3 | 50 / 21 / 49 | 0.434 | 0.544 |

Precision/recall are micro-averaged over all 20 episodes (per-episode P and R are 0 by definition when their denominator is 0, e.g. an empty answer on a clean company, which would make plain means misleading). Steps = steps used including submit.

### By episode group

| Policy | clean reward / F1 | interactions reward / F1 | mixed reward / F1 |
|---|---:|---:|---:|
| flag_all | -1.000 / 0.000 | -1.000 / 0.000 | -1.000 / 0.000 |
| oracle | +1.000 / 1.000 | +1.000 / 1.000 | +1.000 / 1.000 |
| random_explorer | +0.170 / 0.600 | -1.000 / 0.000 | -1.000 / 0.000 |
| reconciler | -0.223 / 0.400 | +0.281 / 0.663 | +0.046 / 0.552 |

## Jury-style checks

- Oracle minimum reward: **1.0** (required ≥ 0.9)
- Ranking oracle > reconciler > random_explorer ≥ flag_all: **True**
- flag_all mean reward ≤ −0.5: **True**
- Reconciler F1 strictly between flag_all and oracle: **True**
- Paired checks (shuffle + rename every id → same oracle reward, same issue count, verify OK): **20/20**
- Replays (same seed → identical sha256 of every file; same policy seed → identical trajectory bytes and reward): **20/20**

## Failure analysis of the reconciler baseline

| Type | Issues | Found (TP) | Missed (FN) | Recall |
|---|---:|---:|---:|---:|
| DUPLICATE_INVOICE | 23 | 23 | 0 | 1.00 |
| FX_CONVERSION | 26 | 0 | 26 | 0.00 |
| PAYMENT_ALLOCATION | 33 | 14 | 19 | 0.42 |
| PERIOD_CUTOFF | 17 | 13 | 4 | 0.76 |

Why issues were missed (measured per issue from the public data):

- FX_CONVERSION: FX conversions are not checked by this baseline — **26**
- PAYMENT_ALLOCATION: partial allocation of a foreign-currency payment (needs the FX rate) — **19**
- PERIOD_CUTOFF: issued after period end in local time, but its UTC date is inside the period — **4**

Why findings were false positives:

- PERIOD_CUTOFF: in-period document whose UTC date falls outside the period (time-zone trap) — **21**

## Reward attacks (measured on the same episodes, train mode)

| Attack | Mean reward |
|---|---:|
| one invented finding on a clean company | -1 |
| flag every document × every type (≤ 30) | -1 |
| oracle (reference answer, 0 steps) | +1 |
| reward(10 steps) − reward(60 steps), same answer | +0.1 |
| oracle with amount off by tolerance + 1 | -1 |
| oracle, every finding submitted twice | +0.333333 |
|   … its F1 | +0.666667 |
| oracle with guessed (non-existent) evidence ids | -1 |
| oracle with one evidence id dropped | -1 |
| oracle with the wrong currency | -1 |
| empty answer on clean companies (0 steps) | +1 |
| empty answer on companies with errors | -1 |

## Resources

- Whole `make jury` run: 47.62 s; slowest single episode (incl. process start): 0.5445 s (limit 60 s).
- Peak RSS: orchestrator 68.3 MB, largest child process 45.6 MB.
- `tests/test_limits.py`: largest episode (≈2000 ledger rows, ≈200 documents, 12 issues) — generation + 100 steps + grading < 5 s and < 500 MB.

## Limitations

See the *Honest limitations* section of DESIGN.md.
