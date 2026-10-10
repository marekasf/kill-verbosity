"""In an 85-job run, the line "The recommendation in this paragraph was superseded on 2026-09-04
..." was deleted, so a withdrawn recommendation read as live. RULES LOST
caught it, but the specialist should never have been allowed to try:
`_STATUS_SUPERSEDED` fed `rule_strength`/`claims_lost` only, never
`keep_lines`, so a supersede/retract/withdraw sentence was fully editable.
"""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))


def test_a_superseded_sentence_is_kept(kv):
    prose = [
        "# Guidance",
        "",
        "The recommendation in this paragraph was superseded on "
        "2026-09-04 by the new auto-merge policy.",
        "",
        "Ordinary prose line that carries no marker at all.",
        "",
    ]
    kept = kv.keep_lines(prose)
    assert 3 in kept, kept


def test_a_retracted_sentence_is_kept(kv):
    prose = [
        "# Guidance",
        "",
        "This finding was retracted after the peer review found the "
        "baseline invalid.",
        "",
    ]
    kept = kv.keep_lines(prose)
    assert 3 in kept, kept


def test_a_withdrawn_sentence_is_kept(kv):
    prose = [
        "# Guidance",
        "",
        "The proposal was withdrawn once the measurement came back.",
        "",
    ]
    kept = kv.keep_lines(prose)
    assert 3 in kept, kept


def test_wrapped_marker_paragraph_keeps_every_continuation_line(kv):
    prose = [
        "# Guidance",
        "",
        "The recommendation in this paragraph was superseded",
        "by the new auto-merge policy, effective 2026-09-04.",
        "",
        "A separate paragraph, unrelated and editable.",
        "",
    ]
    kept = kv.keep_lines(prose)
    assert kept >= {3, 4}, kept
    assert 6 not in kept, kept


def test_ordinary_prose_with_no_marker_is_not_kept_by_this_rule(kv):
    prose = ["# Doc", "", "This sentence carries none of those words at all.", ""]
    kept = kv.keep_lines(prose)
    assert 3 not in kept, kept
