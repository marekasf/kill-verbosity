"""UNHEADED named an interval the number did not come from."""

from __future__ import annotations

import re

import pytest

from killverbosity import summary as S


def _heads(prose):
    out = []
    for i, ln in enumerate(prose):
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def _state(kv, md, words=None):
    prose = md.split("\n")
    return kv.opening_summary(_heads(prose), prose, words or len(md.split()))


LEDE = " ".join(["word"] * 120)
FILLER = " ".join(["filler"] * 900)

SHAPES = {
    "below-title": (f"# Title\n\n{LEDE}\n\n## Section\n\n{FILLER}", None),
    "above-first": (f"{LEDE}\n\n## Setup\n\n{FILLER}", None),
    "title-only": (f"# Title\n\n{LEDE}", 1000),
}


@pytest.mark.parametrize("branch", sorted(SHAPES))
def test_every_branch_is_reachable_and_says_its_own_interval(kv, branch):
    md, words = SHAPES[branch]
    st = _state(kv, md, words)
    assert st.get("lede") == 120, st
    assert st.get("lede_where") == branch, st
    said = kv.summary_verdict(st)[1]
    assert f"UNHEADED — 120 words of prose sit {S.LEDE_WHERE[branch]}." in said, said
    for other, phrase in S.LEDE_WHERE.items():
        if other != branch:
            assert phrase not in said, (branch, other, said)


@pytest.mark.parametrize("branch", sorted(SHAPES))
def test_the_specialist_prompt_names_the_same_interval(kv, branch):
    md, words = SHAPES[branch]
    where = _state(kv, md, words).get("lede_where")
    said = kv.unheaded_note(120, True, where)
    assert f"120 words of prose {S.LEDE_WHERE[branch]}." in said, said
    for other, phrase in S.LEDE_WHERE.items():
        if other != branch:
            assert phrase not in said, (branch, other, said)


def test_a_payload_with_no_branch_reads_as_the_untitled_case(kv):
    """The fallback is a reading, not a hedge."""
    assert S.lede_where_phrase(None) == S.LEDE_WHERE["above-first"]
    assert S.lede_where_phrase("something-that-is-not-a-branch") == \
        S.LEDE_WHERE["above-first"]
    said = kv.summary_verdict({"present": False, "words": 4000, "doc": 4000,
                               "lede": 77})
    assert "77 words of prose sit above the first heading." in said[1], said


def test_the_count_only_wrapper_stays_int_valued(kv):
    """`_legacy._unheaded_lede` is the count and nothing else."""
    prose = f"# Title\n\n{LEDE}\n\n## Section".split("\n")
    assert kv._unheaded_lede(_heads(prose), prose, 4000) == 120
