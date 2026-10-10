"""An unmatched bracket is reported on the line that holds it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import _legacy as kv


BULLETS = [
    "- **Unbounded body size.** FastAPI has default body limits with",
    "  no cap on the streaming path, so a large post is buffered whole.",
    "  The fix is a middleware that rejects a body over the limit.",
    "- **Retry storm.** The client retries three times) with no backoff.",
]


def test_the_line_holding_the_orphan_is_the_one_reported():
    assert kv.unpaired_paragraphs(BULLETS) == {4: ["parenthesis"]}


def test_a_balanced_list_reports_nothing():
    ok = list(BULLETS[:3]) + ["- **Retry storm.** It retries (three times)."]
    assert kv.unpaired_paragraphs(ok) == {}


def test_an_orphan_opener_is_reported_where_it_opens():
    """A wrapped sentence whose closer was reworded away. The opener is the
    half still in the file, so it is the half to point at."""
    assert kv.unpaired_paragraphs(
        ["The job runs nightly (except on", "the last Sunday of the month."]
    ) == {1: ["parenthesis"]}


def test_two_orphans_of_one_kind_are_both_counted():
    """Once per unit of imbalance, so a second stray is not free."""
    assert kv.unpaired_paragraphs(["a ( b ( c"]) == \
        {1: ["parenthesis", "parenthesis"]}


def test_two_kinds_on_different_lines_are_reported_apart():
    assert kv.unpaired_paragraphs(
        ["one ` backtick here", "and one ( paren here"]
    ) == {1: ["backtick"], 2: ["parenthesis"]}


def test_a_paragraph_that_balances_across_its_lines_is_not_an_orphan():
    assert kv.unpaired_paragraphs(["opens (here", "and closes) here"]) == {}


def test_a_blank_line_still_ends_the_paragraph():
    assert kv.unpaired_paragraphs(["opens (here", "", "closes) here"]) == \
        {1: ["parenthesis"], 3: ["parenthesis"]}
