"""transform(episode_dir, perm_seed, out_dir): shuffle every table and rename every id.

The result is the same accounting problem with different surface form: oracle reward and the
set of issues must be preserved (paired check)."""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

from finaudit.generator.episode_io import parse_public, read_files, write_files
from finaudit.util.canon import dumps, sha256_text
from finaudit.util.ids import IdFactory, episode_id
from finaudit.util.records import FX_COLUMNS, LEDGER_COLUMNS, render_csv, render_jsonl
from finaudit.util.rng import derive_seed

PREFIX = {"row_id": "L", "doc_id": "D", "invoice_id": "INV", "payment_id": "PAY", "entity_id": "E"}
LENGTH = {"E": 4}


def _old_ids(pub: dict) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {k: set() for k in PREFIX}
    for table in ("ledger", "invoices", "payments"):
        for rec in pub[table]:
            for key in PREFIX:
                if rec.get(key):
                    found[key].add(rec[key])
    return {k: sorted(v) for k, v in found.items()}


def _mapping(pub: dict, rng: random.Random) -> dict[str, str]:
    old = _old_ids(pub)
    every = [i for ids in old.values() for i in ids]
    factory = IdFactory(rng, taken=set(every))
    mapping: dict[str, str] = {}
    for key, ids in old.items():
        prefix = PREFIX[key]
        for ident in ids:
            mapping[ident] = factory.new(prefix, LENGTH.get(prefix, 6))
    return mapping


def _remap(rec: dict, mapping: dict[str, str]) -> dict:
    out = copy.deepcopy(rec)
    for key in PREFIX:
        if out.get(key):
            out[key] = mapping[out[key]]
    for ref in out.get("invoice_refs", []):
        ref["invoice_id"] = mapping[ref["invoice_id"]]
    return out


def _remap_json(obj: object, mapping: dict[str, str]) -> object:
    """Replace every string value found in ``mapping`` (dict keys are kept)."""
    if isinstance(obj, str):
        return mapping.get(obj, obj)
    if isinstance(obj, list):
        return [_remap_json(v, mapping) for v in obj]
    if isinstance(obj, dict):
        return {k: _remap_json(v, mapping) for k, v in obj.items()}
    return obj


def _remap_truth(truth: dict, mapping: dict[str, str], eid: str, rng: random.Random) -> dict:
    ids = IdFactory(rng)
    issues = []
    for issue in truth["issues"]:
        new = dict(issue, issue_id=ids.new("iss"))
        mapping[issue["issue_id"]] = new["issue_id"]
        new["affected_ids"] = sorted(mapping[a] for a in issue["affected_ids"])
        new["evidence_sets"] = [sorted(mapping.get(e, e) for e in ev) for ev in issue["evidence_sets"]]
        issues.append(new)
    return {"episode_id": eid, "issues": sorted(issues, key=lambda i: i["issue_id"])}


def transform_files(files: dict[str, str], perm_seed: int) -> tuple[dict[str, str], dict[str, str]]:
    """Return (new files, old->new id mapping incl. the episode id)."""
    pub = parse_public(files)
    truth = json.loads(files["private/truth.json"])
    old_eid = pub["manifest"]["episode_id"]
    rng = random.Random(derive_seed("transform", perm_seed, old_eid))
    mapping = _mapping(pub, rng)
    eid = old_eid
    while eid == old_eid:
        eid = episode_id(rng)
    mapping[old_eid] = eid
    tables = {t: [_remap(r, mapping) for r in pub[t]] for t in ("ledger", "invoices", "payments")}
    fx = list(pub["fx"])
    for rows in (*tables.values(), fx):
        rng.shuffle(rows)
    manifest = dict(pub["manifest"], episode_id=eid)
    public = {"manifest.json": dumps(manifest) + "\n",
              "ledger.csv": render_csv(LEDGER_COLUMNS, tables["ledger"]),
              "invoices.jsonl": render_jsonl(tables["invoices"]),
              "payments.jsonl": render_jsonl(tables["payments"]),
              "fx.csv": render_csv(FX_COLUMNS, fx),
              "policy.json": files["public/policy.json"]}
    old_gen = json.loads(files.get("private/generation.json", "{}"))
    generation = {"transform": {"perm_seed": perm_seed, "source_generation": old_gen},
                  "public_sha256": {k: sha256_text(v) for k, v in public.items()}}
    out = {f"public/{k}": v for k, v in public.items()}
    out["private/truth.json"] = dumps(_remap_truth(truth, mapping, eid, rng)) + "\n"
    provenance = _remap_json(json.loads(files["private/provenance.json"]), mapping)
    provenance.update({"episode_id": eid, "transformed": {"perm_seed": perm_seed}})
    out["private/provenance.json"] = dumps(provenance) + "\n"
    out["private/generation.json"] = dumps(generation) + "\n"
    return out, mapping


def transform(episode_dir: str | Path, perm_seed: int, out_dir: str | Path) -> Path:
    """Write the transformed episode to ``out_dir/<new episode id>`` and return that path."""
    files, mapping = transform_files(read_files(episode_dir), perm_seed)
    eid = json.loads(files["public/manifest.json"])["episode_id"]
    return write_files(files, Path(out_dir) / eid)
