"""The first line a run prints about the document says what it folded."""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import _legacy as kv

from conftest import run_tool

SENTENCE = ("It is worth noting that the deployment check is missing here and "
            "the team should consider whether to add one going forward before "
            "the next release train departs.")


def _wrapped(tmp_path, paragraphs=6, width=72):
    p = tmp_path / "w.md"
    p.write_text("# Handbook\n\n" + "\n\n".join(
        textwrap.fill(SENTENCE, width=width) for _ in range(paragraphs)) + "\n")
    return p


def _reported(path):
    out = run_tool("run", path, "--dry-run")
    line = next((l for l in out.stderr.splitlines() if "folded" in l), None)
    assert line, out.stderr
    return tuple(int(n) for n in re.findall(r"\d+", line))


def _truth(path):
    src = path.read_text().rstrip("\n").split("\n")
    _lines, spans = kv.unwrap_source(src)
    folded = [s for s in spans if s[1] > s[0]]
    return sum(b - a + 1 for a, b in folded), len(folded)


def test_the_fold_line_counts_what_folded(tmp_path):
    """Six paragraphs of three lines each: eighteen lines into six."""
    path = _wrapped(tmp_path)

    assert _reported(path) == _truth(path) == (18, 6)


def test_the_fold_line_is_right_on_a_real_document():
    """The file that showed it. A hand-written document has headings, lists
    and tables mixed in, which is what pushed the two numbers so far apart."""
    path = Path(__file__).resolve().parents[1] / "docs/known-issues.md"
    if not path.exists():
        pytest_skip = __import__("pytest").skip
        pytest_skip("known-issues.md is gone")

    reported, truth = _reported(path), _truth(path)

    assert reported == truth, f"printed {reported}, folded {truth}"
    assert reported[1] < reported[0], \
        f"more paragraphs than lines folded into them: {reported}"


def test_a_file_with_nothing_to_fold_says_so(tmp_path):
    """The boundary, and the case that used to be silent."""
    p = tmp_path / "s.md"
    p.write_text("# Doc\n\n" + "\n\n".join(
        f"{SENTENCE} Paragraph {n}." for n in range(12)) + "\n")

    out = run_tool("run", p, "--dry-run")

    assert "no wrap margin found" in out.stderr, out.stderr
    assert "folded" not in out.stderr, out.stderr
    assert "over more than one line" not in out.stderr, out.stderr


def test_a_run_says_which_way_the_fold_went_either_way(tmp_path):
    """One of the two lines, never both and never neither."""
    wrapped = _wrapped(tmp_path)
    flat = tmp_path / "flat.md"
    flat.write_text("# Doc\n\n" + "\n\n".join(
        f"{SENTENCE} Paragraph {n}." for n in range(12)) + "\n")

    said = [(("folded" in run_tool("run", p, "--dry-run").stderr),
             ("no wrap margin found" in run_tool("run", p, "--dry-run").stderr))
            for p in (wrapped, flat)]

    assert said == [(True, False), (False, True)], said


def test_a_run_of_one_line_list_items_does_not_defeat_a_real_margin(tmp_path):
    """a run of one-line list items must not read as one paragraph
    that "wrapped" over every item.
    """
    p = tmp_path / "m.md"
    items = "\n".join(
        f"{i}. Step: the importer runs after the manifest is sealed, and it "
        f"must not be restarted while the lock is held, because the lock is "
        f"advisory and the second process proceeds as though it holds it."
        for i in range(5))
    p.write_text("# Handbook\n\n" + "\n\n".join(
        textwrap.fill(f"{SENTENCE} Paragraph {n}.", 78) for n in range(8))
        + "\n\n" + items + "\n")

    out = run_tool("run", p, "--dry-run")

    assert "no wrap margin found" not in out.stderr, out.stderr
    assert "over more than one line" not in out.stderr, out.stderr
    line = next((l for l in out.stderr.splitlines() if "folded" in l), None)
    assert line, out.stderr
    folded_lines, paragraphs = (int(n) for n in re.findall(r"\d+", line))
    assert paragraphs == 8, line
    assert folded_lines > paragraphs, line


def test_the_counts_never_exceed_the_file(tmp_path):
    """The other boundary, and the shape of the old bug: a count larger than
    the thing it counts. Lines folded cannot exceed the file's lines, and
    paragraphs cannot exceed the lines they were folded from."""
    path = _wrapped(tmp_path, paragraphs=4)
    lines_in_file = len(path.read_text().rstrip("\n").split("\n"))

    folded_lines, paragraphs = _reported(path)

    assert folded_lines <= lines_in_file, (folded_lines, lines_in_file)
    assert paragraphs <= folded_lines, (paragraphs, folded_lines)
