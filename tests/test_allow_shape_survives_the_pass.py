"""`kv:allow-shape` is the author's promise, and it was read off the model's file."""

from __future__ import annotations

import pytest

from conftest import run_tool

CLEAN, BROKE = 0, 1

ORIGINAL = """\
# The shape vocabulary

<!-- kv:allow-shape frame -->

This document is about the frame shape, so it says the words on purpose.

It is worth noting that a frame opens a sentence with nothing in it.

The detector reads the opening clause and nothing else, so the rule is cheap.

## Why it matters

A reader who meets a frame skips the sentence, and the sentence carried the
point a reader came for.
"""

DROPPED = ORIGINAL.replace("<!-- kv:allow-shape frame -->\n\n", "")


def _pair(tmp_path, edited):
    orig = tmp_path / "orig.md"
    out = tmp_path / "orig.kv.md"
    orig.write_text(ORIGINAL)
    out.write_text(edited)
    return orig, out


def test_dropping_the_marker_does_not_revoke_it(tmp_path):
    """The dirty input: the comment went and the shape it allowed did not."""
    orig, out = _pair(tmp_path, DROPPED)

    res = run_tool("verify", orig, out)

    assert "SHAPES INTRODUCED" not in res.stdout, res.stdout
    assert res.returncode == CLEAN, (res.returncode, res.stdout)


def test_a_shape_the_input_never_allowed_is_still_reported(tmp_path):
    """The control, in the SAME arm as the thing under test."""
    edited = DROPPED.replace(
        "The detector reads the opening clause and nothing else, "
        "so the rule is cheap.",
        "It should be noted that the detector reads the opening clause only.")
    assert edited != DROPPED, "the fixture no longer reaches the shape scan"
    orig, out = _pair(tmp_path, edited)

    res = run_tool("verify", orig, out)

    assert "SHAPES INTRODUCED" in res.stdout, res.stdout
    assert "hedge" in res.stdout, res.stdout
    assert "frame" not in res.stdout, res.stdout
    assert res.returncode == BROKE, (res.returncode, res.stdout)


def test_the_marker_is_still_read_off_the_edited_file(tmp_path):
    """Union, not swap."""
    base = ORIGINAL.replace(
        "It is worth noting that a frame opens a sentence with nothing in it.\n"
        "\n", "")
    orig = tmp_path / "orig.md"
    out = tmp_path / "orig.kv.md"
    orig.write_text(base.replace("<!-- kv:allow-shape frame -->",
                                 "<!-- kv:allow-shape hedge -->"))
    out.write_text(base.replace(
        "## Why it matters",
        "It is worth noting that a frame opens a sentence with nothing in it.\n"
        "\n## Why it matters"))

    res = run_tool("verify", orig, out)

    assert "SHAPES INTRODUCED" not in res.stdout, res.stdout
    assert res.returncode == CLEAN, (res.returncode, res.stdout)


@pytest.mark.parametrize("extra", [(), ("--full",)])
def test_the_union_holds_whatever_the_report_width(tmp_path, extra):
    """The verdict is not a display setting."""
    orig, out = _pair(tmp_path, DROPPED)

    res = run_tool("verify", orig, out, *extra)

    assert res.returncode == CLEAN, (extra, res.returncode, res.stdout)
