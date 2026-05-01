"""Shared CLI display helpers used by both run.py and run_benchmark.py.

Kept tiny on purpose — only formatting helpers belong here. Anything that
touches scenario state, adapter calls, or filesystem layout lives in the
runners themselves.
"""

from __future__ import annotations


def format_error_oneline(err: str | None, max_len: int = 80) -> str:
    """Strip boilerplate adapter prefixes, collapse repeated warning lines, and
    truncate at a word boundary so the per-cell row stays readable.

    Adapter errors typically arrive as:
        "Conversion failed: netconvert failed: Warning: Ambiguity in turnarounds
         computation at junction 'n10033'.\\nWarning: Ambiguity in ... 'n10034'.\\n..."
    which formats as:
        "Ambiguity in turnarounds computation at junction 'n10033' (+4 more)"
    """
    if not err:
        return "unknown error"

    text = err.strip()
    for prefix in (
        "Conversion failed: ", "netconvert failed: ", "DTALite prep failed: ",
        "MATSim failed: ", "Error: ", "Warning: ",
    ):
        while text.startswith(prefix):
            text = text[len(prefix):]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "unknown error"

    head = lines[0]
    for prefix in ("Warning: ", "Error: "):
        if head.startswith(prefix):
            head = head[len(prefix):]

    extra = len(lines) - 1
    suffix = f" (+{extra} more)" if extra > 0 else ""

    budget = max(10, max_len - len(suffix))
    if len(head) > budget:
        cut = head[:budget].rsplit(" ", 1)[0]
        if not cut:
            cut = head[:budget]
        head = cut + "…"

    return head + suffix
