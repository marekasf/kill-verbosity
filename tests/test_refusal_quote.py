"""A refusal quotes the text it is refusing over, and the quote is readable."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

SUBTITLE = "check the deployment configuration before the migration runs"
LINES = ["# The queue", "", f"## Summary — {SUBTITLE}", "",
         "Some body text here.", "", "## Detail", "", "More text."]


def test_a_refused_rename_quotes_the_instruction_on_a_word(kv):
    """The rename drops a subtitle telling the reader what to do, and nothing
    in the reply carries it, so the edit is refused. The reason quotes it."""
    _prose, headings, _t, _q = kv.mask("\n".join(LINES))
    _merged, applied, refused, _ = kv.merge(
        LINES, [{"specialist": "structure",
                 "edits": [{"op": "replace", "line": 3,
                            "new": "## Summary"}]}],
        set(range(1, len(LINES) + 1)), (), headings)

    assert not applied and len(refused) == 1, (applied, refused)
    reason = refused[0][2]

    assert "…" in reason, reason
    assert "migr'" not in reason, reason
    for word in reason.split("'")[1].rstrip("…").split():
        assert word in SUBTITLE.split(), (word, reason)
