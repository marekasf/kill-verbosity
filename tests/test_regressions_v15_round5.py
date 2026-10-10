"""Round-five findings from a review."""

import json
import sys

import pytest

from killverbosity import pointers

pytestmark = pytest.mark.regression


def _plan(kv, monkeypatch, tmp_path, text, name="doc.md"):
    """`plan` builds the work list without calling any agent."""
    src = tmp_path / name
    src.write_text(text)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "plan", str(src)])
    try:
        kv.main()
    except SystemExit:
        pass


def _run(kv, monkeypatch, tmp_path, text, reply, name="doc.md"):
    src = tmp_path / name
    src.write_text(text)
    monkeypatch.setattr(
        kv, "call_agent",
        lambda *a: (json.dumps(reply), None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass



def test_an_unchanged_repeat_is_not_reported_as_introduced(kv):
    """H2. `duplicates` grows a match rightwards while every copy agrees."""
    shared = ("the retry count is never read back from the running job so"
              " nobody can tell")
    before = [{"lines": [486, 519], "words": 14, "text": shared + " what it"}]
    after = [{"lines": [491, 524], "words": 16, "text": shared + " what it is"}]

    _fixed, added = kv.repeat_delta(before, after)

    assert not added, (
        "a repeat present in the original, unchanged, was reported as "
        f"introduced by the run: {added}")


def test_a_genuinely_new_repeat_is_still_reported(kv):
    """H2 guard. The default-of-one branch is what catches a real one."""
    fresh = [{"lines": [12, 40], "words": 9,
              "text": "a phrase the original document never said twice at all"}]

    _fixed, added = kv.repeat_delta([], fresh)

    assert added, "a cluster the original did not have must be reported"


def test_a_third_copy_of_an_existing_repeat_is_still_reported(kv):
    """H2 guard. Said once more than the author did is what the list is for."""
    text = "before it gives up and moves on to the next candidate line"
    before = [{"lines": [10, 20], "words": 11, "text": text}]
    after = [{"lines": [10, 20, 31], "words": 11, "text": text}]

    _fixed, added = kv.repeat_delta(before, after)

    assert added, "a third copy of a phrase the original repeated twice is new"



def test_a_pointer_naming_two_sections_follows_both_renames():
    """H1. `follow()` matches the whole bracket as one heading name."""
    results = [{"specialist": pointers.OWNER, "edits": [
        {"new": "Start with the parser (Do this first; If time runs short)."}]}]
    renames = {"Do this first": "Commit `errors.py`",
               "If time runs short": "Cut here"}

    pointers.follow(results, renames)
    got = results[0]["edits"][0]["new"]

    assert "Do this first" not in got, f"first name not followed: {got}"
    assert "If time runs short" not in got, f"second name not followed: {got}"
    assert "Commit `errors.py`" in got and "Cut here" in got, got


def test_a_one_section_pointer_still_follows():
    """H1 guard. The ordinary case must not change."""
    results = [{"specialist": pointers.OWNER,
                "edits": [{"new": "See the notes (Do this first)."}]}]

    pointers.follow(results, {"Do this first": "Commit `errors.py`"})

    assert results[0]["edits"][0]["new"] == "See the notes (Commit `errors.py`)."


def test_a_bracket_naming_no_heading_is_left_alone():
    """H1 guard. Not every bracket is a pointer."""
    results = [{"specialist": pointers.OWNER,
                "edits": [{"new": "Read it twice (slowly; out loud)."}]}]

    pointers.follow(results, {"Do this first": "Commit `errors.py`"})

    assert results[0]["edits"][0]["new"] == "Read it twice (slowly; out loud)."


def test_a_half_matching_pointer_keeps_the_name_it_cannot_follow():
    """H1. One renamed section and one untouched, in the same bracket."""
    results = [{"specialist": pointers.OWNER,
                "edits": [{"new": "Both (Do this first; Appendix)."}]}]

    pointers.follow(results, {"Do this first": "Commit `errors.py`"})
    got = results[0]["edits"][0]["new"]

    assert "Commit `errors.py`" in got, got
    assert "Appendix" in got, f"the unrenamed name was dropped: {got}"



def test_the_em_dash_clusters_print_as_one_row(kv, monkeypatch, tmp_path,
                                               capsys):
    """H11. On the comments file, lines 126 to 194 each printed the shape
    name and an empty text column — 54 rows saying one thing.
    """
    paras = "\n\n".join(
        f"The retry count — the one the job reads — is not written down "
        f"anywhere in section {i}, and nobody has checked it."
        for i in range(20))
    _plan(kv, monkeypatch, tmp_path, f"# Notes\n\n{paras}\n")
    rows = [l for l in capsys.readouterr().out.splitlines()
            if "em-dash cluster" in l]

    assert rows, "the shape fired and printed nothing"
    assert len(rows) < 20, (
        f"{len(rows)} em-dash rows for 20 paragraphs — still one each:\n"
        + "\n".join(rows[:5]))
    blank = [r for r in rows if not r.split("em-dash cluster")[1].strip()]
    assert not blank, f"rows with an empty text column: {blank}"
