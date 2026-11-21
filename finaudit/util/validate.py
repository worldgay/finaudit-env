"""A small JSON-Schema subset validator (stdlib only).

Supported keywords: type, properties, required, additionalProperties (bool),
items, enum, const, pattern, minimum, maximum, minLength, maxLength,
minItems, maxItems, anyOf, oneOf.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def load_schema(name: str) -> dict:
    """Load ``finaudit/schemas/<name>.schema.json``."""
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def errors(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Return a list of validation errors (empty when valid)."""
    out: list[str] = []
    typ = schema.get("type")
    if typ is not None:
        types = typ if isinstance(typ, list) else [typ]
        if not any(_TYPES[t](value) for t in types):
            return [f"{path}: expected {typ}"]
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: not in enum")
    out.extend(_scalar_errors(value, schema, path))
    if isinstance(value, dict):
        out.extend(_object_errors(value, schema, path))
    if isinstance(value, list):
        out.extend(_array_errors(value, schema, path))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            ok = [not errors(value, sub, path) for sub in schema[key]]
            if (key == "anyOf" and not any(ok)) or (key == "oneOf" and sum(ok) != 1):
                out.append(f"{path}: {key} failed")
    return out


def _scalar_errors(value: Any, schema: dict, path: str) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: pattern")
        if len(value) < schema.get("minLength", 0):
            out.append(f"{path}: too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: too long")
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above maximum")
    return out


def _object_errors(value: dict, schema: dict, path: str) -> list[str]:
    out: list[str] = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            out.append(f"{path}.{key}: required")
    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in props:
                out.append(f"{path}.{key}: unexpected")
    for key, sub in props.items():
        if key in value:
            out.extend(errors(value[key], sub, f"{path}.{key}"))
    return out


def _array_errors(value: list, schema: dict, path: str) -> list[str]:
    out: list[str] = []
    if len(value) < schema.get("minItems", 0):
        out.append(f"{path}: too few items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        out.append(f"{path}: too many items")
    if "items" in schema:
        for i, item in enumerate(value):
            out.extend(errors(item, schema["items"], f"{path}[{i}]"))
    return out


def is_valid(value: Any, schema_name: str) -> bool:
    """True when ``value`` validates against the named schema."""
    return not errors(value, load_schema(schema_name))
