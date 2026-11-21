`docker build -t finaudit . && docker run --rm --network none --cpus 2 --memory 4g finaudit make check`

> **Для жюри (RU):** памятка на русском — [`docs/JURY.md`](docs/JURY.md): запуск, адаптер, рецепты D01–D20,
> правила пересчёта и переименования ID. Windows PowerShell 5.1 не знает `&&` — выполните две команды по очереди:
> `docker build -t finaudit .`, затем `docker run --rm --network none --cpus 2 --memory 4g finaudit make check`.

# FinAudit RL environment

A reproducible, offline reinforcement-learning environment for an **AI financial auditor**. It generates
synthetic companies (one company × one calendar month) with hidden bookkeeping errors, exposes them through a
Gymnasium-style JSON contract (`reset` / `step`) with narrow investigation tools, and grades the auditor's
findings with a public, deterministic matcher and reward. We ship the environment, not an agent: four fixed
baseline policies are included only to show that the environment is neither trivial nor unsolvable.

All data is fictional (names assembled from syllables, no real companies, banks, IBANs, cards or people).
Runtime = Python 3.11 standard library + `tzdata==2024.2`; tests need only `pytest==8.3.3`. No network, GPU
or paid API is used. The pinned wheels are vendored in `vendor/wheels/`, so `docker build` needs no network
once the base image `python:3.11-slim` is on the machine (`docker pull python:3.11-slim` once, or
`docker load -i <saved image tar>`; verified digest in the `Dockerfile` header). Run the image as root (the default):
the grader-owned `private/` directories are unreadable for other users on purpose, so a `--user` run fails the
shipped-data leak test with `PermissionError`.

## Quick start

| Command | What it does |
|---|---|
| `make check` | full test suite (287 tests, ≈45–65 s in total; the 60 s limit is per episode) + smoke run: 2 fresh episodes, verify, 4 policies, leak scan |
| `make docker-check` | builds the image and runs `make check` with `--network none --cpus 2 --memory 4g` |
| `make episodes` | regenerates the shipped dataset `episodes/{train,dev}` (10 + 10, verified) |
| `make trajectories` | 4 policies × 10 train episodes → `trajectories/trajectories.jsonl` |
| `make jury` | simulated closed check: 20 new episodes × 4 policies in eval mode, 20 paired, 20 replays |
| `make report` | rebuilds `REPORT.md` from `runs/jury/summary.json` |
| `make demo` | terminal walk-through on an I1 episode |

Without GNU make every target is `python3.11 -m finaudit.tasks <target>` (the Docker image ships `make` as
a shim to exactly this). One episode by hand:
`python3.11 -m finaudit.generator.generate --seed 7 --config configs/default.json --out /tmp/eps`.

```python
from finaudit.env.core import FinAuditEnv
env = FinAuditEnv()
obs, info = env.reset(seed=7, config={"mode": "train"})          # or config={"episode_dir": "episodes/train/ep-…"}
obs, reward, terminated, truncated, info = env.step({"action": "list_records", "table": "ledger"})
```

## Contract

* `reset(seed, config) -> (observation, info)` — full state reset. `config["episode_dir"]` loads a stored
  episode, otherwise the episode is generated from `(seed, config, ENV_VERSION)`. `config["mode"]` is
  `train` (default) or `eval`.
* `step(action) -> (observation, reward, terminated, truncated, info)`; every value is JSON-serialisable.
* Observation, always: `{"ok": bool, "result": any|null, "error": {"code","message"}|null, "steps_left": int}`.
  The first one carries the task text, `manifest`, `policy`, table names, the four finding types and limits.

| Action | Arguments | Result |
|---|---|---|
| `list_records` | `table` ∈ ledger/invoices/payments/fx, `cursor` (opaque, null = start), `limit` 1..50 | `{"table","records","next_cursor"}` in file order |
| `get_record` | `table`, `id` (row_id / doc_id / `fx:YYYY-MM-DD:SRC:TGT`) | `{"table","record"}` |
| `get_document` | `doc_id` of an invoice or payment | `{"doc_type","document"}` |
| `calculator` | `expression`: numbers, `+ - * /`, unary minus, parentheses, ≤ 200 chars (ast + Decimal, 28 digits) | `{"value": "…"}` |
| `submit` | `findings` = `{"episode_id", "findings": [...]}` | episode ends |

Error codes (closed list): `UNKNOWN_ACTION, BAD_ARGS, UNKNOWN_TABLE, NOT_FOUND, BAD_CURSOR, LIMIT_TOO_LARGE,
BAD_EXPRESSION, EPISODE_DONE, INVALID_FINDINGS`; messages ≤ 120 chars, no paths, no tracebacks, no hints.
Every step, including a failing one, costs 1 of 100 steps (submit included). `submit` → `terminated=true`;
100 steps without submit or 60 s wall clock (enforced by the runner) → `truncated=true` and the empty answer is
graded. Any step after the end returns `EPISODE_DONE`, costs nothing, reward 0, flags unchanged; a second submit
is never graded. Reward is 0.0 on every non-terminal step.

* **train**: the terminal step returns the terminal reward and `info = {precision, recall, f1, tp, fp, fn,
  inspection_steps}`.
* **eval**: reward is always 0.0 and `info = {"steps_used": n}`; the grade goes only to `grader_log.jsonl`.
  `python -m finaudit.runner run --mode eval …` starts the env-server (`finaudit.env.server`, JSON lines) and
  the agent (`python -m finaudit.policies.<name>`) as separate processes; as root in Docker they run as users
  `grader` and `agent`, `private/` and run directories are `grader`-owned with mode 700, the agent works in an
  empty directory and only ever receives observations.

## Data formats (`public/` of an episode)

`manifest.json` (ids, company, base currency, period, time zone, counts, currency exponents), `ledger.csv`
(`row_id,timestamp,account,debit_minor,credit_minor,currency,entity_id,invoice_id,payment_id`), `invoices.jsonl`,
`payments.jsonl`, `fx.csv` (`date,source_currency,target_currency,rate`, one row per day from period_start−7 to
period_end+7 per foreign currency) and `policy.json` (the booking rules). `private/` holds `truth.json`,
`provenance.json`, `generation.json` and is never shown to an agent. JSON Schemas: `finaudit/schemas/`.

Independent check of any episode: `python3.11 -m finaudit.generator.verify episodes/dev/ep-…` — structure,
sha256, `reference_audit(public) == truth` in both directions, evidence ids reachable, no leaks, and the
**pre-error equalities**: `provenance.json` logs every injected change (`table, id, field, before, after`);
replaying it backwards (`finaudit/generator/revert.py`) gives books that balance, book every in-period document,
and in which the reference auditor finds nothing.

* Money: integer minor units (`total_minor: 1250000` = 12 500.00); exponents in the manifest (JPY = 0).
* Time: ISO-8601 with offset; offsets deliberately vary (local or `+00:00`) while the instant is correct.
* Rates: decimal strings with 6 places. Missing references: explicit `null`; in CSV an **empty cell is null**.
* Ledger amounts are in base currency; exactly one of debit/credit is > 0. Accounts: AR, AP, REVENUE, EXPENSE,
  BANK, SUSPENSE, FX_GAIN_LOSS. Journal pairs without document references pad the ledger (bank charges etc.).
* Schema extensions (nothing mandatory renamed or removed): `invoices[].direction` ∈ `receivable|payable`;
  `payments[].direction` ∈ `incoming|outgoing` (incoming = customer side; a refund is an incoming payment with a
  negative amount and a negative ref); fx records returned by the tools carry an extra `fx_id`.
* Booking policy: rate date = local calendar date of the document in `manifest.timezone`;
  `base = round_half_even(amount / 10^exp_src × rate × 10^exp_base)`; BANK at the payment-date rate, AR/AP
  allocation lines at the invoice-date rate, the difference on FX_GAIN_LOSS. Limitation: a payment is always in
  its invoice's currency (no cross-currency settlement).

## Hidden error types

| type | affected_ids | amount & currency | sufficient evidence (any one set) |
|---|---|---|---|
| `DUPLICATE_INVOICE` | both invoice_ids | total of the copy, invoice currency | both doc_ids + both AR/AP ledger rows |
| `PAYMENT_ALLOCATION` | invoice_id + payment_id | unallocated part, payment currency | payment doc + invoice doc + every ledger row of the payment (+ the `fx:` row of the invoice date when a foreign payment is partly booked) |
| `FX_CONVERSION` | invoice_id or payment_id | \|booked − policy\| of the AR/AP (invoice) or BANK (payment) row, base currency | document + `fx:` row of the correct date + the affected row |
| `PERIOD_CUTOFF` | invoice_id | booked AR/AP amount, base currency | invoice doc + its AR/AP row |

An allocation `(payment, invoice_ref)` is **complete** (no finding) iff the signed AR/AP amount posted for it equals
`fx_conversion(invoice_ref.amount_minor, rate of the invoice date)` (identity for a base-currency payment). Only
otherwise unallocated part = ref amount − `round_half_even(posted_base / rate(invoice date))` in payment minor
units. Apply this order when re-computing independently: the inverse conversion alone does not round-trip and
would report spurious 1-unit gaps on correct books (`finaudit/generator/reference_audit.py`, `_payment_checks`).
Two interaction scenarios add two linked issues each: **I1** — a foreign customer payment late on the last
day, BANK booked at the UTC-date (or next-day) rate, then partially parked on SUSPENSE; **I2** — a duplicated
invoice whose single payment is booked 50/50 to original and copy. Every episode also contains ≥ 3 kinds of
correct distractors (split payments, one payment for several invoices, overpayment + refund, weekly repeated
amounts, documents near midnight whose UTC date is outside the period, next-month invoices that are not
booked, FX gain/loss lines, 1-unit rounding residues). Clean companies (`configs/clean.json`) have no errors.

## Matcher and reward (`finaudit/grader/`)

Follows the organisers' exact matcher conventions (`docs/CHECKS.md`, tests `tests/test_jury_matcher.py`).

1. Structure (checked on the raw lists, before any de-duplication): exact keys, `episode_id` matches,
   ≤ 30 findings, string `type`, 1..10 string `affected_ids`, `claimed_amount_minor` JSON integer ≥ 0
   (bool/float/string rejected), string `currency`, ≤ 10 string `evidence_ids`, `explanation` ≤ 1000 Unicode
   code points. Any violation → reward −1 (`INVALID_FINDINGS`), metrics null in `score_episode`.
2. Normalisation: none for strings — `type`, `currency` and every id are compared exactly (case and spaces
   count). `affected_ids` and `evidence_ids` are sets. An unknown type string is a valid but unmatched finding (FP).
3. A pair (finding, issue) is admissible iff type equal, affected-id sets equal, currency equal,
   `|claimed − expected| ≤ τ(type)`, every evidence id exists in the public records, and the evidence contains a
   complete admissible set (extra existing ids are fine). `explanation` never affects the score.
   Evidence ids are the canonical record ids only: ledger `row_id`, document `doc_id`, `fx:DATE:SRC:TGT`.
   The aliases that `get_record` also accepts (`invoice_id`, `payment_id`, fx id without `fx:`) are not evidence ids.
4. τ is a fixed non-negative integer per type published in `policy.json → amount_tolerance_minor`
   (missing → 0). Shipped value: **0 for all four types** — every expected amount follows exactly from the
   formulas in `policy.json` (`fx_conversion`, `payment_allocation_amount`, ROUND_HALF_EVEN).
5. Maximum bipartite matching; ties broken as in the definitions: issues in Unicode order of `issue_id`, each
   taking the smallest finding index that keeps the matching maximum. Repeats stay separate FP.
6. `F1 = 2TP/(2TP+FP+FN)` (both empty → 1; truth empty, answer not → 0);
   `reward = clip(2·F1 − 1 − 0.002·inspection_steps, −1, 1)` computed with `Fraction`, no rounding;
   inspection_steps = all steps before submit (errors included); submit counts toward the 100-action limit only.

## Jury adapter (`judge_adapter.py`)

The single connection point from the check definitions. Working directory: `/app` in the image; nothing else
to install. Example: `docker run --rm --network none finaudit python -c "import judge_adapter as j; print(j.make_env())"`.

| Entry point | Behaviour |
|---|---|
| `generate_episode(seed, config, output_dir)` | team generator → `output_dir/public/{manifest.json, ledger.csv, invoices.jsonl, payments.jsonl, fx.csv, policy.json}` and `output_dir/private/{truth.json, provenance.json, generation.json}`; `config` is a team config (`configs/*.json`) or `{"team_config": {...}}` |
| `make_env()` → `reset(seed, config)` | `config = {"mode": "closed" \| "train", "episode_dir": ..., "team_config": {...}}`; with `episode_dir` exactly that episode is loaded (no regeneration, no id change); first observation `{"task", "manifest", "policy", "remaining_steps": 100}` |
| `step({"name": ..., "args": {...}})` | names `list_records(table, cursor, limit)`, `get_record(table, id)`, `get_document(doc_id)`, `calculator(expression)`, `submit(findings)`; observation `{"result", "error": null \| {"code", "message"}, "remaining_steps"}` |
| results | `list_records` → `{"records", "next_cursor"}`; `get_record`/`get_document` → the record/document object; `calculator` → decimal string (`"0.3"` for `0.1+0.2`); `submit` → `{"accepted": true}` or an `INVALID_FINDINGS` error, never a correctness signal |
| closed mode | every reward 0 (also at the end), `info` = `{"steps_used"}` only; the true reward is kept by the grader |
| limits | 100 actions incl. submit; 100 inspection actions → `truncated`, empty findings; 60 s from `reset` (policy time included) → `truncated`, empty findings |
| `score_episode(episode_dir, findings, inspection_steps)` | `{"tp", "fp", "fn", "precision", "recall", "f1", "return"}`; invalid structure → `return = -1`, other fields null, reason on stderr (grader log) |

Tables: `ledger` (id `row_id`), `invoices` and `payments` (id `doc_id`; `invoice_id`/`payment_id` also
accepted), `fx` (id `fx:DATE:SRC:TGT`). Error types (case §02 → our `type`): invoice duplicates →
`DUPLICATE_INVOICE`; missing/partial payment allocation → `PAYMENT_ALLOCATION`; wrong conversion date or rate →
`FX_CONVERSION`; wrong reporting period → `PERIOD_CUTOFF`. Interaction scenarios: `I1`, `I2` (see above).
Error codes: `UNKNOWN_ACTION`, `BAD_ARGS`, `UNKNOWN_TABLE`, `NOT_FOUND`, `BAD_CURSOR`, `LIMIT_TOO_LARGE`,
`BAD_EXPRESSION`, `EPISODE_DONE`, `INVALID_FINDINGS`. For paired checks the jury edits a copy of the episode
directory (ids in public files, truth and provenance); nothing in the loader depends on file hashes or id format.
Keep renamed ids unique across all namespaces (`get_record` resolves `doc_id` before the `invoice_id` /
`payment_id` alias); the full list of id-bearing fields is in `docs/JURY.md`. `generation.json` hashes and the
team verifier's id patterns are expected to fail on such edited copies; loading and grading do not use them.
The 60 s limit is checked on each `step`; a policy that never calls `step` again is stopped by the caller.
Run only the jury blocks: `docker run --rm --network none finaudit python -m pytest -q tests/test_judge_adapter.py
tests/test_jury_matcher.py tests/test_hostile_input.py`.

## Measured failures (found → cause → fix → re-check)

A pre-submission audit drove the environment through `judge_adapter.py` and the eval runner with hostile input.
Each failure below was reproduced, fixed, and is re-checked by `tests/test_hostile_input.py` (the tests fail on
v1.2.0 and pass now).

| Measured failure (v1.2.0) | Cause | Fix |
|---|---|---|
| A cursor of `"["` × 1 100 (base64) made `step` raise `RecursionError` into the caller | `decode_cursor` did not catch `RecursionError` | caught → `BAD_CURSOR`; any unexpected handler exception → bounded `BAD_ARGS`, step still counted |
| An agent writing `{` without newline, or flooding actions without reading, hung the eval runner past 60 s (killed at 120 s) | blocking `readline` / `stdin.write` on pipes | raw non-blocking reads/writes with the episode deadline → `truncated`, empty findings |
| An agent line `"["` × 100 000 or a 5 000-digit integer aborted the episode without a grade | only `JSONDecodeError` was caught | `ValueError`/`RecursionError` → treated as an invalid action (bounded error) |
| `reset` on a copy without `private/truth.json` → `KeyError`; `step` before `reset` → `AttributeError` | missing guards | closed mode loads with an empty truth (grading is `score_episode`); clear `RuntimeError` / `FileNotFoundError` |

## Baseline policies (`finaudit/policies/`)

`oracle` (grader-only, reads truth, needs `--allow-oracle`), `reconciler` (naive sweep: duplicates, cut-off by
UTC date, allocation without FX rates, no FX checks — it falls into the traps on purpose), `random_explorer`
(5–60 random valid actions, 0–3 random findings), `flag_all` (every document × every type). Results:
`REPORT.md`.

## Configs

`configs/*.json` (all with `config_version`). Missing keys take defaults — including omitted error types
(`count [0, 2]`) and interactions (`[0, 1]`), so a single-type episode needs the other types set to 0 explicitly
(ready recipes for D01–D20 in `docs/JURY.md`); `errors.<TYPE>` accepts `{"count": n}`,
`{"count": [a, b]}` or the shorthand `n` / `[a, b]`; keys that do not describe data (`mode`, `episode_dir`, `seed`,
`description`, …) are ignored for generation. Base currency: any of KZT, USD, EUR, GBP, JPY (random among the first
three when null); time zone: any of the six in `world.TZ_POOL`. `reset(seed=None)` means seed 0.

## Reproducibility

One `random.Random` per episode seeded from `sha256(seed | canonical config hash | ENV_VERSION | attempt)`; no
clock, `hash()` or set iteration in generation; canonical JSON everywhere; the time-zone database is pinned to
the `tzdata` package. `transform(episode, perm_seed)` shuffles every table and renames every id — the oracle
reward is unchanged (20/20 in `make jury`). Seeds must be secret and high-entropy (e.g. 64-bit): the generator is
public, so a small or sequential seed (like the shipped 1001–1010) can be found by brute force from the public
data in well under 60 s. The shipped train/dev seeds are public on purpose.

Release v1.2.1 = v1.2.0 data and rules (`ENV_VERSION` and every episode byte stay 1.2.0) plus the robustness
fixes listed under "Measured failures" and the jury memo `docs/JURY.md`.

License: MIT.
