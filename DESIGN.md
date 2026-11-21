# DESIGN — FinAudit RL environment

## 1. Task and boundaries
The deliverable is an *environment*: a generator of synthetic month-end books with hidden errors, a JSON
`reset/step` contract with five narrow actions, and a grader. Out of scope by design: training, UI, LLM agents.
Everything runs offline on Python 3.11 + `tzdata`.

## 2. World and generation
Generation runs in four passes from one RNG seeded by `sha256(seed | config hash | ENV_VERSION | attempt)`:
(1) **hidden history** — company, base currency (KZT/USD/EUR), 1–3 foreign currencies with a daily rate random
walk (6 decimals, never flat day-to-day), a time zone from six (incl. negative and DST zones), 6–30
counterparties, receivable and payable invoices, payments, refunds; (2) **clean books** from `policy.json`
(AR/REVENUE, EXPENSE/AP, BANK at the payment-date rate, AR/AP allocation at the invoice-date rate, the
difference on FX_GAIN_LOSS, padding journal pairs) followed by `check_invariants` (Σdr = Σcr, one-sided rows,
every amount equals the policy conversion, every payment fully allocated, everything inside the period);
(3) **error injection** — each injector makes one causal change, logs it (`table, id, field, before → after`)
and returns the issue with its amount and evidence sets; (4) **render** — shuffled rows, opaque vowel-free ids
(`INV-7F3K2Q`), public/private split. `verify_episode` then re-derives every discrepancy with an independent
`reference_audit` that reads only public files; any mismatch with `truth.json` (either direction), missing
evidence, out-of-range size or leaked word rejects the attempt and the next attempt is drawn deterministically.
Verify also replays the provenance change log backwards and checks the **pre-error equalities** on the recovered
books (balance, one-sided rows, every in-period document booked, reference auditor finds nothing). Every evidence
set is self-sufficient: e.g. a duplicate needs both documents *and* both bookings, a partially booked foreign
payment needs the invoice-date fx row to recompute the amount.

## 3. Errors, interactions, distractors
Four independently configurable types — duplicate invoice (copy ±0–3 days, booked), payment allocation (part or
all parked on SUSPENSE, or the payment not booked), FX conversion (UTC date, ±1–3 days or inverse rate), period
cut-off (next-month invoice booked inside the period) — on both the receivable and payable side, ≤ 12 per
episode. Interactions: **I1** FX + partial allocation of one late-evening foreign payment on the last day
(FX applied first, both amounts computed after both changes, order kept in provenance); **I2** a duplicate whose
single payment is booked half to the copy. Allocation amounts are in payment currency, so injectors choose
splits whose base value converts back exactly; truth is therefore exactly what an auditor recomputes.
Distractors (≥ 3 kinds in every episode, also in clean ones) are built to break naive rules: split payments,
multi-invoice payments, overpayment + negative refund, weekly identical amounts, near-midnight documents written
in `+00:00`, unbooked next-month invoices, FX gain/loss lines, 1-unit rounding residue.

## 4. Contract and isolation
Fixed observation shape, closed error-code list, 100 steps including submit, 50-row pages with stable opaque
cursors, a calculator built on `ast` + `Decimal`, copies of records in every result (an in-process agent cannot
mutate the store). In eval mode the reward is always 0 and only `steps_used` is returned; the env-server (also
the grader) and the agent are separate processes linked by JSON lines through the runner, run as users
`grader`/`agent` in Docker, with `private/` and run directories at mode 700. The oracle is grader-only. A leak
scanner checks every observation, error message, trajectory and public file for issue ids, the words
truth/provenance/private/seed, error-type names, hint words and absolute paths.

## 5. Matcher and tolerances
Implements the organisers' exact conventions (docs/CHECKS.md). Structural validation on the raw lists (any defect
→ −1); strings (type, currency, ids) compared exactly, affected/evidence ids as sets, an unknown type string is an
unmatched finding (FP); admissible pairs need type, exact affected-id set, currency fixed per type, amount within
the published per-type tolerance τ (`policy.json → amount_tolerance_minor`, 0 for every type, missing → 0) and
existing evidence ids covering one full evidence set. Then a maximum bipartite matching with the published
tie-break (issues by `issue_id` code points, smallest finding index). The TP count is the same in every maximum
matching, so ambiguity cannot change the metrics; repeated findings become FP. Reward =
`clip(2·F1 − 1 − 0.002·steps, −1, 1)`, computed with `Fraction` and returned without rounding.

The jury connects through `judge_adapter.py` (generate_episode / make_env / score_episode, `{"name", "args"}`
actions, closed mode = eval mode with reward 0 and no diagnostics, 60 s wall clock per episode). It is a pure
translation layer over `FinAuditEnv` and the grader; `tests/test_judge_adapter.py` runs contract block C01–C20.

## 6. What the tests check (287 tests, `make check`)
Contract and every error branch; the jury adapter against contract block C01–C20; the organisers' matcher/reward
block 1–20 and examples M01–M12 with exact numbers (`tests/test_jury_matcher.py`); calculator attacks; pagination completeness and cursor stability; matcher
normalisation, tolerance edges and maximum matching; the 12 reward attacks with exact numbers; clean-book
invariants and verify on 1000 seeds; each error type alone (amount, currency, reachable evidence, both sides,
all variants); I1/I2; distractors never flagged; verify catches nine kinds of corrupted truth; transform keeps the
oracle reward and leaves no old id; byte-identical regeneration (also across `PYTHONHASHSEED`); trajectory
replay; eval isolation (a process running as `agent` gets `Permission denied` on `private/`); policy ranking;
the largest episode in < 5 s and < 500 MB; every base currency × time zone; lenient config forms; broken
provenance is detected; hostile cursors, agent lines and stalled pipes give bounded errors (`tests/test_hostile_input.py`).

## 7. Numbers (`REPORT.md`, 20 fresh episodes, 99 issues, eval mode)
Mean reward / F1: oracle **+1.000 / 1.000**, reconciler **+0.037 / 0.542**, random_explorer **−0.708 / 0.150**,
flag_all **−1.000 / 0.000**. Paired checks 20/20, replays 20/20, slowest episode 0.54 s incl. process start
(limit 60 s). The reconciler finds all 23 duplicates but misses every FX error (26; it has no rates), 19 of 33
allocation errors (foreign-currency partial allocations), 4 cut-offs that look in-period in UTC, and produces 21
false cut-offs on in-period documents whose UTC date is outside the period — exactly the traps the environment was
designed to contain. With a fixed policy seed the random explorer never finds an error; its mean F1 of 0.150 comes
only from clean companies where it happens to submit nothing. These numbers are regenerated by `make jury` +
`make report`; `REPORT.md` is the source of truth.

## 8. Honest limitations
* The data is synthetic and the error catalogue is closed (four types, two interactions); a high reward does
  **not** show fitness for real-world auditing, only for this specification.
* By the general formula, an empty answer after a timeout on a clean company scores 0.8 (1 − 0.2); we keep the
  formula unchanged and document the property.
* Payments are always in the invoice currency (no cross-currency settlement); partial-payment amounts are
  defined through one published rounded inverse conversion (`policy.json → payment_allocation_amount`). The
  tolerance is 0, so an agent that inverts the rate another way (e.g. rounds the other direction) loses the
  finding — checked by `test_tolerance_edges` and the `oracle_amount_off_tol_plus_1` attack (−1.0 in REPORT.md).
* The 60 s wall-clock limit is checked at the next `step` call (`judge_adapter.py`); a policy that never returns
  is stopped by the caller (our runner kills the agent process; the jury stops its own run).
* An agent that has the generator code could brute-force the seed if the seed space were small; jury seeds are
  64-bit and the seed never appears in public files or observations.
* The reconciler is a deliberately naive baseline; no model was trained and no learning claim is made.
* Inside `PAYMENT_ALLOCATION` the variant (partially allocated / parked on SUSPENSE / not posted) is drawn per
  seed and is not a config key; provenance shows which one an episode got (`docs/JURY.md`). Distractor kinds are
  always on (≥ 3 per episode), so clean companies D01–D05 differ by seed and time zone, not by a switch.
