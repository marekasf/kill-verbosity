"""`plan` output: boilerplate lines that told the reader nothing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_tool

FILLER = "The team reviews each deployment for accuracy and records the outcome."

WRAPPED = """# Notes

## What the checker does

The run reads the file and reports every shape that it found, and a note
on the ordering is printed beside the list so the reader knows what it
is looking at.

The list is ordered by line so that a reader can walk the file from the
top to the bottom while holding the printed report beside it as they go
through it.

The second pass over the same output was measured across nine samples
and bought very little in the end, so the tool does not offer a revision
pass at all.

Every gate matches text rather than meaning, so a sentence turned around
keeps all of its words and passes each of the checks that run before the
file lands.

A reader who wants the short version can read the header line, which
names the count and the cost, and then decide whether the rest is worth
their attention.
"""


def test_silent_chunks_name_their_line_range_and_heading(tmp_path):
    """The summary line named silent chunks by number only, and told the
    reader to "read them yourself" with no way to find them. Each one now
    prints the line range and heading a firing chunk prints."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# Notes\n\n"
        + "".join(f"## Section {i}\n\n{FILLER} {FILLER}\n\n"
                  for i in range(1, 3))
        + "## Last\n\nIt is worth noting that the deployment finished.\n")

    out = run_tool("plan", p).stdout

    assert "3 chunks found nothing: 1-3" in out, out
    assert "chunk   2  lines" in out and "Section 1" in out, out
    assert "chunk   3  lines" in out and "Section 2" in out, out
    after = out.split("found nothing")[1]
    assert after.splitlines()[1].strip().endswith(
        "them.") or "prose words" in after.splitlines()[1], after


def test_header_states_total_and_prose_once(tmp_path):
    """Two word counts, "37 fault-shapes in 14502 words" and "963 of 12669
    prose words", with nothing saying the second was a subset of the first.
    The header now names both, and the rate divides by the prose figure."""
    p = tmp_path / "doc.md"
    p.write_text(
        "# Notes\n\n| col | note |\n|---|---|\n| a | one two three four |\n\n"
        "It is worth noting that the deployment finished in the end.\n")

    out = run_tool("plan", p).stdout
    head = next(x for x in out.splitlines() if "fault-shape" in x)

    assert "of them prose" in head, head
    import re
    total = int(re.search(r"in (\d+) words", head).group(1))
    prose = int(re.search(r"(\d+) of them prose", head).group(1))
    assert 0 < prose < total, head
    rate = float(re.search(r"\(([\d.]+) per 1000", head).group(1))
    assert rate == round(1 * 1000 / prose, 1), head


def test_fold_note_says_which_way_and_why(tmp_path):
    """The note said folding only reveals shapes, even on the one real
    report where the folded count printed SMALLER than the count above it.
    It now names the direction the numbers actually moved."""
    doc = tmp_path / "w.md"
    doc.write_text(WRAPPED)

    out = run_tool("plan", doc).stdout
    note = next(l for l in out.splitlines() if "hard-wraps" in l)

    assert "counts 1 there" in note, note
    assert "1 more" in note, note
    assert "reveals a shape split across two lines" in note, note


def test_folded_count_no_longer_undercounts_list_faults(kv):
    """`_folded_shape_count` called `find_shapes` alone, so a document whose
    extra hit was a list fault compared a folded count that could never
    include it against `_census_n`, which does — an undercount with nothing
    to do with folding, printed as if it were the fold's doing."""
    text = WRAPPED + (
        "- Ship the release after the go/no-go call on Monday\n"
        "- Ship the release after the go/no-go call on Monday\n"
        "- Page the on-call engineer if the deploy fails\n")
    lines = text.split("\n")
    folded, _spans = kv.unwrap_source(lines)
    assert len(folded) != len(lines), "fixture must still hard-wrap"
    prose, heads, tables, quotes = kv.mask("\n".join(folded), "d.md")
    find_only = len(kv.find_shapes(prose, tables, heads, quotes, chat=False))
    faults = len(kv.list_faults(prose, folded))
    assert faults > 0, "fixture does not trigger a list fault"

    got = kv._folded_shape_count(text, "d.md", False, -1)

    assert got == find_only + faults, (got, find_only, faults)


def test_wall_advice_prints_once_as_a_legend(tmp_path):
    """One sentence of advice printed once per wall paragraph — 85 times on
    a real document, 19% of the output. It now prints once, above the chunk
    list, and each entry keeps line, kind, sentence count and word count."""
    wall = ("The service starts. It reads the queue. It writes each row. "
            "It commits the batch. It releases the lock. It logs the run.")
    p = tmp_path / "doc.md"
    p.write_text(
        f"# Notes\n\n## First\n\n{wall}\n\n## Second\n\n{wall}\n")

    out = run_tool("plan", p).stdout

    assert out.count("keep the claim and its strongest support") == 1, out
    assert "wall: keep the claim and its strongest support." in out, out
    assert out.count("wall (") == 2, out
