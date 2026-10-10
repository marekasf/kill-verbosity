"""A prompt template's hole is the one token it cannot lose."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

TEMPLATE = """<role>
You are diagnosing a failure in the current repository.
</role>

<task>
{{USER_FOCUS}}
</task>

<output_contract>
Output exactly three lines, in this order:

root-cause: <one-sentence statement of the most likely cause>
</output_contract>
"""


def test_the_placeholder_is_protected(kv):
    assert kv.facts(TEMPLATE)["placeholder"] == {"{{USER_FOCUS}}"}


def test_dropping_it_reads_as_a_lost_token(kv):
    """The whole point. Without the kind, both files carried the same token
    set and the edit that empties the template passed."""
    before = kv.facts(TEMPLATE)
    after = kv.facts(TEMPLATE.replace("{{USER_FOCUS}}", "the failure"))

    assert before["placeholder"] - after.get("placeholder", set()) == \
        {"{{USER_FOCUS}}"}


def test_backticked_and_bare_are_the_same_token(kv):
    """A code span that is wholly one kind of token is filed under that kind.
    Without it, adding a pair of backticks reads as one loss and one
    invention."""
    assert kv.facts("the single {{USER_FOCUS}} placeholder")["placeholder"] == \
        kv.facts("the single `{{USER_FOCUS}}` placeholder")["placeholder"]


def test_the_specialist_prompts_interpolations_count_too(kv):
    """`summary.md` carries three, and they size the summary it writes."""
    got = kv.facts("Keep it to {{SUMMARY_CAP}} words. Under "
                   "{{SUMMARY_MIN_WORDS}} it is a heading pretending.")

    assert got["placeholder"] == {"{{SUMMARY_CAP}}", "{{SUMMARY_MIN_WORDS}}"}


def test_a_hole_inside_a_link_leaves_the_link_whole(kv):
    """`url` runs first, so the whole link is one token, holes and all."""
    got = kv.facts("see https://api.example.com/{{version}}/jobs for it")

    assert got["url"] == {"https://api.example.com/{{version}}/jobs"}
    assert "placeholder" not in got


def test_a_hole_named_like_a_ticket_is_still_a_hole(kv):
    """`ticket` and `version` both match inside the braces, so the placeholder
    pass has to come before them or the braces are left as debris."""
    assert kv.facts("a {{ABC-123}} hole")["placeholder"] == {"{{ABC-123}}"}
    assert kv.facts("a {{v1.2.3}} hole")["placeholder"] == {"{{v1.2.3}}"}


def test_the_gap_does_not_cross_a_line(kv):
    """A hole is written on one line. Letting the gap span a newline lets a
    stray `{{` pair with a `}}` in another paragraph."""
    assert "placeholder" not in kv.facts("a {{\nUSER_FOCUS\n}} hole")


def test_ordinary_braces_are_not_a_placeholder(kv):
    """A JSON example in a fence is masked, but one written inline is not, and
    the shape has to stay tight enough not to take it."""
    assert "placeholder" not in kv.facts('send {"op": "insert"} and {} too')
