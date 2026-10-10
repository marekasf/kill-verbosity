"""What depth a summary heading is written at."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

TITLED = ["# The queue", "", "## Background", "", "a.", "", "## Detail", "",
          "b."]


def _level(kv, lines):
    _prose, headings, _t, _q = kv.mask("\n".join(lines))
    return kv.section_level(headings, lines)


def test_a_section_is_one_under_the_title(kv):
    assert _level(kv, TITLED) == 2


def test_the_depth_comes_from_the_document_not_from_the_title(kv):
    """A Markdown export from Google Docs writes its title `##` and its
    sections `##` too. One deeper than the title would put the summary below
    the sections it belongs beside."""
    got = _level(kv, ["## The queue", "", "## Background", "", "a.", "",
                      "## Detail", "", "b."])

    assert got == 2


def test_one_section_written_too_deep_does_not_move_the_answer(kv):
    """`min`, not the first heading after the title."""
    got = _level(kv, ["# The queue", "", "### Stray", "", "a.", "",
                      "## Detail", "", "b."])

    assert got == 2


def test_a_file_with_no_title_gets_no_opinion(kv):
    """A transcript of `###### 00:00` stamps and a bare headingless note. Both
    guesses tried here were wrong on a fixture, so the rule declines."""
    assert _level(kv, ["plain text.", "", "more.", "", "end."]) == 0
    assert _level(kv, ["Dana", "", "###### 00:00 - 01:10", "", "speech.", "",
                       "Alex", "", "###### 01:10 - 02:00", "", "more."]) == 0


def test_the_merge_rewrites_a_summary_written_too_deep(kv):
    """End to end, through the gate that already moves the line."""
    lines = list(TITLED)
    prose, headings, _t, _q = kv.mask("\n".join(lines))
    merged, applied, refused, _ = kv.merge(
        lines, [{"specialist": "summary", "edits": [
            {"op": "insert", "line": len(lines),
             "new": "### Summary\n\nThe result in one line."}]}],
        set(range(1, len(lines) + 1)), (), headings)

    assert applied and not refused, (applied, refused)
    assert "## Summary" in merged[:3], merged
    assert "### Summary" not in merged, merged


def _insert(kv, lines):
    lines = list(lines)
    _prose, headings, _t, _q = kv.mask("\n".join(lines))
    merged, applied, refused, _ = kv.merge(
        lines, [{"specialist": "summary", "edits": [
            {"op": "insert", "line": len(lines),
             "new": "## Summary\n\nThe result in one line."}]}],
        set(range(1, len(lines) + 1)), (), headings)
    assert applied and not refused, (applied, refused)
    return merged


def test_a_setext_title_is_two_lines_and_keeps_both(kv):
    """The gate counted one, so the summary landed between the title and its
    underline: the title became a paragraph and the underline a stray row."""
    got = _insert(kv, ["The queue", "=========", "", "## Background", "",
                       "a.", "", "## Detail", "", "b."])

    assert got[:2] == ["The queue", "========="], got[:4]
    assert got[3] == "## Summary", got[:6]


def test_frontmatter_keeps_line_one(kv):
    """Frontmatter has to open the file to be frontmatter. There is no heading
    in it, so there was no title, so the gate was 1 and the summary went above
    the opening `---` — turning it into a rule and two lines of stray text."""
    got = _insert(kv, ["---", "title: The queue", "---", "", "## Background",
                       "", "a.", "", "## Detail", "", "b."])

    assert got[0] == "---" and got[2] == "---", got[:5]
    assert "## Summary" in got[3:6], got[:8]


def test_frontmatter_and_a_title_puts_it_under_the_title(kv):
    """The later of the two gates wins, not the first one that answers."""
    got = _insert(kv, ["---", "title: q", "---", "", "# The queue", "",
                       "## Background", "", "a.", "", "## Detail", "", "b."])

    assert got[4] == "# The queue", got[:7]
    assert got[6] == "## Summary", got[:9]


def test_a_summary_written_too_shallow_is_refused(kv):
    """`# Summary` under an H1 title is a second document title, and
    it is also the shape with no heading at or above its own level before EOF:
    nothing would stop its territory at the next `##`. Narrowing (the deep
    case above) is cosmetic and stays a rewrite; widening used to be fixed the
    same way, and that is what let a real run's `# Summary` swallow the rest
    of a 14.5k-word document. Refused now, not guessed at."""
    lines = list(TITLED)
    _prose, headings, _t, _q = kv.mask("\n".join(lines))
    merged, applied, refused, _ = kv.merge(
        lines, [{"specialist": "summary", "edits": [
            {"op": "insert", "line": len(lines),
             "new": "# Summary\n\nThe result in one line."}]}],
        set(range(1, len(lines) + 1)), (), headings)

    assert not any(a[2] == "insert" for a in applied), applied
    assert refused and "re-parent" in refused[0][2], refused
    assert "## Summary" not in merged, merged
