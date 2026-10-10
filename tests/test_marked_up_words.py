"""Putting a word the file already uses into backticks is not a new fact."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import _legacy as kv


HEADING = "#### Worked example — badges-microservice !112 (web-core, green)"
LINE = "Retry it first."
DOC = [HEADING, LINE]


def _added(new: str, doc: list[str] = DOC) -> str:
    return kv.tokens_added(LINE, new, (), kv.token_lines(doc), "\n".join(doc))


def test_a_word_from_a_heading_may_be_marked_up():
    assert _added("Retry `badges-microservice` !112 first.") == ""


def test_a_word_from_prose_may_be_marked_up():
    doc = ["The badges-microservice pipeline is green.", LINE]
    assert _added("Retry `badges-microservice` first.", doc) == ""


def test_a_word_from_a_code_example_may_be_marked_up():
    """It is still a word the reader has already been given."""
    doc = ["```sh", "deploy badges-microservice", "```", LINE]
    assert _added("Retry `badges-microservice` first.", doc) == ""


def test_a_word_the_file_never_uses_is_still_refused():
    assert _added("Retry `never-written` first.") == "never-written"


def test_half_of_a_hyphenated_name_is_refused():
    """A hyphen counts into the word. Left as a plain `\\w` boundary it reads
    `production` as already written wherever `non-production` is, which
    licenses a reword that inverts the sentence."""
    assert _added("Retry `badges` first.") == "badges"


def test_the_opposite_of_a_word_is_not_that_word():
    doc = ["The job only runs against non-production.", LINE]
    assert _added("Retry `production` first.", doc) == "production"


def test_a_code_span_wrapped_across_two_lines_is_still_found():
    """The file hard-wraps, so a two-word span can have a newline in it."""
    doc = ["Never run rm -rf", "/data on the live box.", LINE]
    assert _added("Retry `rm -rf /data` first.", doc) == ""


def test_a_word_only_a_comment_holds_is_refused():
    """`facts()` strips comments before it reads anything, so a word visible
    only to the parser cannot license an invented one."""
    doc = ["<!-- badges-microservice was renamed -->", LINE]
    assert _added("Retry `badges-microservice` first.", doc) \
        == "badges-microservice"


def test_a_number_the_file_never_states_is_still_refused():
    """A number carries its unit, so the refusal names `47min` and not `47`."""
    assert _added("Retry after 47 minutes.") == "47min"


def test_the_one_line_is_still_the_answer_when_no_document_is_given():
    """The parameter defaults off, so every other caller keeps its behaviour."""
    assert kv.tokens_added("Retry `x-y` now.", "Retry `x-y` later.") == ""
    assert kv.tokens_added(LINE, "Retry `x-y` now.") == "x-y"
