"""Every printed line number is one the reader can find in their own file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import _legacy, wrapping


SPANS = [(0, 2), (3, 3), (4, 7)]


def test_one_folded_line_prints_the_span_it_came_from():
    assert wrapping.label(1, 1, SPANS) == "L1-3"


def test_a_folded_line_that_folded_nothing_prints_one_number():
    assert wrapping.label(2, 2, SPANS) == "L4"


def test_a_range_runs_from_the_first_source_line_to_the_last():
    assert wrapping.label(1, 3, SPANS) == "L1-8"


def test_no_spans_means_the_numbers_are_already_the_authors():
    assert wrapping.label(4, 9, []) == "L4-9"


def test_a_line_past_the_end_is_clamped_not_raised_on():
    """A specialist can answer with a line past its span. A wrong number in a
    refusal must not take the whole report down with it."""
    assert wrapping.label(99, 99, SPANS) == "L5-8"


def test_a_line_below_the_start_is_clamped():
    assert wrapping.label(0, 0, SPANS) == "L1-3"


CLUSTER = [{"lines": [2, 3], "words": 9, "text": "the same"}]


def test_a_repeat_job_is_labelled_in_the_authors_lines():
    """`repeat · lines 5/25` is read by a person, so it counts their lines."""
    job, = _legacy.duplicate_jobs(CLUSTER, 10, SPANS + [(8, 8), (9, 9)])
    assert job["unit"] == "repeat · lines 4/5"


def test_a_repeat_jobs_span_stays_in_folded_lines():
    """The span is what the specialist is given, and it works on the folded
    text. Mapping it to source lines would send it the wrong paragraphs."""
    job, = _legacy.duplicate_jobs(CLUSTER, 10, SPANS + [(8, 8), (9, 9)])
    assert (job["lo"], job["hi"]) == (1, 5)


def test_a_file_that_did_not_fold_labels_its_lines_unchanged():
    job, = _legacy.duplicate_jobs(CLUSTER, 10)
    assert job["unit"] == "repeat · lines 2/3"
