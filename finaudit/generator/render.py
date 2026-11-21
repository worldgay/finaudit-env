"""Shuffle and render the public and private files of an episode (in memory)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from finaudit import ENV_VERSION, SCHEMA_VERSION
from finaudit.generator.inject import Ctx
from finaudit.util.canon import config_hash, data_config, dumps, sha256_text
from finaudit.util.ids import episode_id
from finaudit.util.money import CURRENCY_EXPONENT
from finaudit.util.records import FX_COLUMNS, LEDGER_COLUMNS, render_csv, render_jsonl

PUBLIC_FILES = ("manifest.json", "ledger.csv", "invoices.jsonl", "payments.jsonl", "fx.csv", "policy.json")

POLICY = {
    "fx_rate_date": "local calendar date of the document timestamp in manifest.timezone",
    "fx_conversion": "base_minor = round_half_even(amount_minor / 10^exp_src * rate * 10^exp_base)",
    "period_boundary": ("a document belongs to the period if its local date (manifest.timezone) "
                        "is within [period_start, period_end] inclusive"),
    "rounding": "ROUND_HALF_EVEN to the minor unit of the target currency",
    "ledger_currency": "base_currency",
    "fx_difference_account": "FX_GAIN_LOSS",
    "suspense_account": "SUSPENSE",
    "finding_currency_by_type": {
        "DUPLICATE_INVOICE": "invoice currency",
        "PAYMENT_ALLOCATION": "payment currency",
        "FX_CONVERSION": "base currency",
        "PERIOD_CUTOFF": "base currency",
    },
    "payment_allocation_amount": (
        "unallocated_minor = invoice_ref.amount_minor - allocated_minor; for a foreign payment "
        "allocated_minor = round_half_even(allocated_base_minor / rate * 10^exp_src / 10^exp_base) "
        "with the rate of the invoice's fx_rate_date"),
    "amount_tolerance_minor": {"DUPLICATE_INVOICE": 0, "PAYMENT_ALLOCATION": 0, "FX_CONVERSION": 0,
                               "PERIOD_CUTOFF": 0},
}

INVOICE_KEYS = ("doc_id", "invoice_id", "entity_id", "direction", "issued_at", "due_at", "currency",
                "total_minor", "line_items")


@dataclass(frozen=True)
class Episode:
    """In-memory episode: relative path -> file text."""

    episode_id: str
    files: dict[str, str]


def _fx_rows(ctx: Ctx) -> list[dict]:
    w = ctx.w
    keys = sorted(ctx.w.fx)
    return [{"date": d, "source_currency": c, "target_currency": w.base, "rate": w.fx[(d, c)]}
            for d, c in keys]


def _manifest(ctx: Ctx, eid: str, n_ledger: int, n_fx: int) -> dict:
    w = ctx.w
    n_inv, n_pay = len(w.invoices), len(w.payments)
    return {"schema_version": SCHEMA_VERSION, "env_version": ENV_VERSION, "episode_id": eid,
            "company_name": w.company_name, "base_currency": w.base,
            "period_start": w.period_start.isoformat(), "period_end": w.period_end.isoformat(),
            "timezone": w.tz,
            "counts": {"ledger": n_ledger, "invoices": n_inv, "payments": n_pay, "fx": n_fx,
                       "documents": n_inv + n_pay},
            "currency_exponents": dict(CURRENCY_EXPONENT), "rounding": "ROUND_HALF_EVEN"}


def _provenance(ctx: Ctx, eid: str, plan: dict) -> dict:
    w = ctx.w
    return {"episode_id": eid, "plan": plan, "distractors": sorted(set(w.distractors)),
            "world": {"company_name": w.company_name, "base": w.base, "foreign": w.foreign,
                      "timezone": w.tz, "period_start": w.period_start.isoformat(),
                      "entities": w.entities},
            "injections": [p.to_dict() for p in ctx.provenance]}


def render_episode(ctx: Ctx, rng: random.Random, plan: dict, seed: int, cfg: dict,
                   attempt: int) -> Episode:
    """Shuffle row order and produce all public and private files."""
    eid = episode_id(rng)
    ledger = list(ctx.rows)
    rng.shuffle(ledger)
    invoices = [{k: inv[k] for k in INVOICE_KEYS} for inv in ctx.w.invoices]
    rng.shuffle(invoices)
    payments = list(ctx.w.payments)
    rng.shuffle(payments)
    fx = _fx_rows(ctx)
    public = {
        "manifest.json": dumps(_manifest(ctx, eid, len(ledger), len(fx))) + "\n",
        "ledger.csv": render_csv(LEDGER_COLUMNS, ledger),
        "invoices.jsonl": render_jsonl(invoices),
        "payments.jsonl": render_jsonl(payments),
        "fx.csv": render_csv(FX_COLUMNS, fx),
        "policy.json": dumps(POLICY) + "\n",
    }
    issues = sorted((i.to_dict() for i in ctx.issues), key=lambda i: i["issue_id"])
    generation = {"seed": seed, "config": data_config(cfg), "config_hash": config_hash(cfg),
                  "env_version": ENV_VERSION, "attempt": attempt,
                  "public_sha256": {k: sha256_text(v) for k, v in public.items()}}
    files = {f"public/{k}": v for k, v in public.items()}
    files["private/truth.json"] = dumps({"episode_id": eid, "issues": issues}) + "\n"
    files["private/provenance.json"] = dumps(_provenance(ctx, eid, plan)) + "\n"
    files["private/generation.json"] = dumps(generation) + "\n"
    return Episode(eid, files)
