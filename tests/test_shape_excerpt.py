"""A shape row says which sentence it found, not just which shape."""

from __future__ import annotations

import sys

from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

TWO = ("# T\n\n"
       "It is worth noting that the queue drains slowly under load today.\n\n"
       "It is worth noting that the retry budget is three seconds per job.\n")


def _rows(out):
    return [l for l in out.splitlines() if "  frame " in l]


def test_two_sentences_that_open_alike_print_different_rows(tmp_path):
    doc = tmp_path / "two.md"
    doc.write_text(TWO)

    rows = _rows(run_tool("plan", str(doc)).stdout)

    assert len(rows) == 2, rows
    assert "queue drains" in rows[0], rows
    assert "retry budget" in rows[1], rows


def test_two_hits_on_one_line_print_different_rows(tmp_path):
    """A markdown paragraph is one line until something wraps it, so the two
    sentences that open alike are usually on the same line. Taking the first
    match every time printed the identical row twice, which is the fault."""
    doc = tmp_path / "same.md"
    doc.write_text("# T\n\nIt is worth noting that the queue drains slowly. "
                   "It is worth noting that the retry budget is three.\n")

    rows = _rows(run_tool("plan", str(doc)).stdout)

    assert len(rows) == 2, rows
    assert rows[0] != rows[1], rows
    assert "queue drains" in rows[0], rows
    assert "retry budget" in rows[1], rows


def test_the_excerpt_stops_at_the_end_of_its_sentence(tmp_path):
    """Running to the end of the line pulls in the next sentence, which reads
    as part of the hit and sends the reader to fix text nothing flagged."""
    doc = tmp_path / "one.md"
    doc.write_text("# T\n\nIt is worth noting that the queue is slow. "
                   "The operator is paged after the retry budget expires.\n")

    row = _rows(run_tool("plan", str(doc)).stdout)[0]

    assert "queue is slow." in row, row
    assert "operator" not in row, row


def test_the_surviving_list_tells_two_hits_on_one_line_apart(tmp_path):
    """`verify`'s surviving-shapes list had the same fault worse. On a real
    file it printed `L269 'clean'` five times, two of them on the same line,
    on the one list that asks the reader to decide about each hit."""
    orig = tmp_path / "a.md"
    orig.write_text("# T\n\nThe clean index URL hides the token. "
                    "The clean report shows the retry.\n")
    edited = tmp_path / "b.md"
    edited.write_text(orig.read_text())

    row = [l for l in run_tool("verify", str(orig), str(edited)).stdout
           .splitlines() if "evaluative adjective (" in l][0]

    assert "index URL" in row, row
    assert "report shows" in row, row


def test_a_full_stop_inside_the_match_does_not_cut_the_match(kv):
    """The end is looked for after the match. Searching from the start of it
    cut `It is e.g. worth noting` down to `It is e.g.` — less than the phrase
    the row exists to report."""
    from killverbosity import unmask

    src = ["A row. It is e.g. worth noting that the queue drains slowly."]

    said = unmask.in_context(src, src, 1, "It is e.g. worth noting")

    assert said.startswith("It is e.g. worth noting"), said
    assert "queue drains" in said, said


def test_a_row_that_falls_back_to_the_whole_line_keeps_the_match(kv):
    """`as_written` returns the whole line for a table row. Cutting that at
    the line's first full stop printed `| Yes.` for a row reporting text
    further along it — the flagged words absent from their own row."""
    from killverbosity import unmask

    raw = ["| Yes. | It is worth noting that the queue drains slowly. |"]
    masked = [raw[0][:-3]]

    said = unmask.in_context(raw, masked, 1, "It is worth noting")

    assert "It is worth noting" in said, said


def test_the_hit_itself_is_still_the_match(kv):
    """The widening must not reach `find_shapes`, whose text the gates and
    `verify` compare against the document."""
    prose = TWO.splitlines()
    hits = kv.find_shapes(prose)

    assert hits, hits
    assert all(t == "It is worth noting" for _l, k, t in hits
               if k == "frame"), hits
