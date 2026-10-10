"""A shape whose hit in a cell is unclearable or destructive is not scanned
for in a cell.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import _legacy as kv


ROW = "| Fixture, clean prompts blocked | 3.0% to 7.9% | 1.0% to 5.9% |"
TABLE = ["| Case | Before | After |", "| --- | --- | --- |", ROW]


def _kinds(lines: list[str]) -> set[str]:
    prose, heads, tables, quotes = kv.mask("\n".join(lines), "t.md")
    return {c for _, c, _ in kv.find_shapes(prose, tables, heads, quotes)}


def test_a_percentage_range_in_a_cell_is_not_a_hit():
    assert "number without its noun" not in _kinds(TABLE)


def test_the_same_range_in_prose_is_still_a_hit():
    assert "number without its noun" in _kinds(["Worth switching on, "
                                                "from 83% to 86%."])


def test_the_last_cell_of_a_row_is_silent_too():
    """The structural case: nothing at all follows the last figure, so before
    this it fired on every table row that ended in a range."""
    assert "number without its noun" not in _kinds(
        ["| Metric | Change |", "| --- | --- |", "| Recall | 61% → 80% |"])


def test_a_range_in_a_heading_still_fires():
    """Only cells are blind. A heading is a sentence the author wrote."""
    assert "number without its noun" in _kinds(["## Recall moves 61% → 80%."])


def test_every_other_shape_still_reads_the_cell():
    """The blind list is two shapes, not a licence to stop scanning tables."""
    assert "evaluative adjective" in _kinds(TABLE)



DATED = "FIXED 2026-09-11 - the gate now reads the span."


def test_dated_provenance_in_a_cell_is_not_a_hit():
    assert "worklog" not in _kinds(
        ["| id | status |", "| --- | --- |", f"| F3 | {DATED} |"])


def test_the_same_sentence_in_prose_is_still_a_hit():
    """The control, and it is the half that earns the case: one sentence, the
    row walls the only difference."""
    assert "worklog" in _kinds([DATED])


def test_a_dated_heading_still_fires():
    """Blind in CELLS only. `## Status re-verified against the code,
    2026-08-21` is a heading a person wrote, and it is the one hit of the four
    on the fix log that this change must leave alone."""
    assert "worklog" in _kinds(
        ["## Status re-verified against the code, 2026-08-21", "", "body"])


def test_the_section_opener_arm_is_blind_in_a_cell_too():
    """One shape name, so both arms go. A cell reading `Current status:
    blocked` is that row's data, and keeping the arm alive in cells would need
    a second shape name — which `genre-log` would then not switch off."""
    assert "worklog" not in _kinds(
        ["| area | note |", "| --- | --- |", "| gate | Current status: blocked |"])


def test_a_table_that_names_nothing_is_missed_and_that_is_the_trade():
    """`| Result | 3% to 7% |` really does leave the figure unexplained. It is
    missed, because telling it apart from a table that does name the measure
    means guessing what a column header means. The hit was not actionable even
    when it was right: the fix is to rename the header, which is not the line
    the shape pointed at."""
    assert "number without its noun" not in _kinds(
        ["| Case | Result |", "| --- | --- |", "| Fixture | 3% to 7% |"])


def test_the_blind_list_names_only_shapes_that_exist():
    every = set(kv.EXISTENCE) | set(kv.SUBSTITUTION) | set(kv.OCCURRENCE) \
        | set(kv.CHAT)
    assert kv.CELL_BLIND <= every, kv.CELL_BLIND - every
