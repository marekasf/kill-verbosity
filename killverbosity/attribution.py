"""Lines where a named person is credited with saying something."""
from __future__ import annotations

import re

_NAME = r"[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}"
ATTRIBUTION = re.compile(
    r"^\s*(?:[-*+]\s+|>\s*)?"
    r"\*\*(?:"
    rf"{_NAME},[^*]*\d[^*]*?:"
    rf"|{_NAME}'s [a-z][^*]{{0,60}}?:"
    r")"
)


def lines(prose) -> set[int]:
    """1-based line numbers carrying an attribution."""
    return {i for i, ln in enumerate(prose, 1) if ATTRIBUTION.match(ln)}
