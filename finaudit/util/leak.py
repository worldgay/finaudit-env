"""Vocabulary that must never appear inside public records or observations."""
from __future__ import annotations

FINDING_TYPES = ("DUPLICATE_INVOICE", "PAYMENT_ALLOCATION", "FX_CONVERSION", "PERIOD_CUTOFF")

# Words that would hint at an error, or at private grader material.
HINT_WORDS = ("duplicat", "dupl", "error", "wrong", "mistake", "fraud", "cutoff", "cut-off",
              "misalloc", "unalloc", "invalid", "fake", "issue_id", "seed", "truth",
              "provenance", "private", "inject", "anomal", "suspicious", "bogus")

PATH_MARKERS = ("/home/", "/app/", "/tmp/", "/mnt/", "/root/", "/usr/", "/var/", "\\\\", "C:\\")


def text_has_hint(text: str) -> bool:
    """True when ``text`` contains a hint word (case-insensitive)."""
    low = text.lower()
    return any(w in low for w in HINT_WORDS)


def scan_text(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Return every forbidden token found in ``text``."""
    low = text.lower()
    hits = [w for w in HINT_WORDS if w in low]
    hits += [t for t in FINDING_TYPES if t.lower() in low]
    hits += [p for p in PATH_MARKERS if p.lower() in low]
    hits += [e for e in extra if e and e.lower() in low]
    return hits
