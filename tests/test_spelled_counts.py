"""Every spelled number in `SPELLED_OUT` is counted as a number."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

WORDS = [
    "eight", "eighteen", "eighty", "eleven", "fifteen", "fifty", "five",
    "forty", "four", "fourteen", "nine", "nineteen", "ninety", "seven",
    "seventeen", "seventy", "six", "sixteen", "sixty", "ten", "thirteen",
    "thirty", "three", "twelve", "twenty", "two",
]


def test_the_table_holds_exactly_these_words() -> None:
    """A word added or removed has to come here and say so."""
    from killverbosity import _legacy

    assert sorted(_legacy.SPELLED_OUT) == sorted(WORDS)


@pytest.mark.parametrize("word", WORDS)
def test_a_spelled_number_is_counted(word: str, tmp_path: Path) -> None:
    doc = tmp_path / "one.md"
    doc.write_text(
        "Report\n======\n\n"
        f"The retry ran {word} times before the queue drained and it finished.\n")

    result = run_tool("plan", str(doc), "--json")
    assert result.returncode == 0, result.stderr

    counts = json.loads(result.stdout)["global_context"]["fact_counts"]
    assert counts.get("number") == 1, (
        f"{word!r} was not counted as a number: {counts}")
