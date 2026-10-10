"""A review that loses "Dana asked this" reassigns his finding to its author."""

from __future__ import annotations

import sys

import pytest
from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

from killverbosity import _legacy as kv

ORIG = """# Review

## The status body is not trustworthy

The handler trusts the body of every status it receives, which is not safe.
Fix: drop the claim, or allow-list the statuses you trust. Dana asked this on line 66.

## Concurrency has no source parameter

The helper cannot be told which source to count against.
Fix: give it the same `source` parameter its sibling has. Dana asked this on line 181.

## The second option is the better one

That is Ayushi's second option, and the report backs it.
"""

PARTIAL = ORIG.replace(
    "Fix: drop the claim, or allow-list the statuses you trust."
    " Dana asked this on line 66.",
    "Fix: drop the claim, or allow-list the statuses you trust (line 66).")

REWORDED = ORIG.replace(
    "That is Ayushi's second option, and the report backs it.",
    "This matches the second option, backed by the report.")

DELETED = (ORIG.replace(" Dana asked this on line 66.", "")
               .replace(" Dana asked this on line 181.", ""))


def _reported(tmp_path, new_text: str) -> str:
    a, b = tmp_path / "orig.md", tmp_path / "new.md"
    a.write_text(ORIG)
    b.write_text(new_text)
    for line in run_tool("verify", a, b).stdout.splitlines():
        if "said fewer times than before" in line:
            return line.strip()
    return ""


def test_a_subject_credit_partly_lost_is_reported(tmp_path):
    """The reported case, and the one the widening is for."""
    assert "Dana 2→1" in _reported(tmp_path, PARTIAL)


def test_a_possessive_lost_by_rewording_is_still_reported(tmp_path):
    """This half already worked. It is here so a change to the subject rule
    cannot pass by breaking the rule that was already right."""
    assert "Ayushi 1→0" in _reported(tmp_path, REWORDED)


def test_a_name_deleted_whole_is_still_silent(tmp_path):
    """The refused half, asserted so it cannot be reversed by accident."""
    assert _reported(tmp_path, DELETED) == ""


@pytest.mark.parametrize("new_text,why", [
    (ORIG, "nothing changed at all"),
    (ORIG.replace("The handler trusts the body of every status it receives, "
                  "which is not safe.",
                  "The handler trusts every status body."),
     "a cut that touches no name"),
])
def test_the_controls_stay_silent(tmp_path, new_text, why):
    assert _reported(tmp_path, new_text) == "", why


def test_an_ordinary_word_opening_a_sentence_is_not_a_credit():
    """`Summary noted`, `Issues raised` — the verb list alone reported 30 such
    names over 201 documents.
    """
    text = ("Summary noted the gap. A summary is owed here.\n"
            "Issues raised the count. Several issues remain open.\n"
            "Dana asked this on line 66.\n")

    found = {m.group(1) for m in kv.credited_names(text)
             if m.group(1) not in kv.NAME_NOT}

    assert found == {"Dana"}, found


def test_a_closed_class_opener_is_dropped_even_in_a_short_document():
    """The lower-case test is per-document, so it cannot carry a word the
    document happens never to write in lower case. `NAME_NOT` is the belt, and
    it holds closed classes only — determiners, pronouns, quantifiers, spelled
    numbers — because each of those lists has an end.
    """
    text = "Both asked for it. Every reviewer wants the same thing.\n"

    assert not [m for m in kv.credited_names(text)
                if m.group(1) not in kv.NAME_NOT]
    assert [m.group(1) for m in kv.credited_names("Ayushi asked for it.\n")] \
        == ["Ayushi"]
