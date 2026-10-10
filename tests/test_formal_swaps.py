"""R2: a plain word replaced by a longer one that says the same thing."""

from __future__ import annotations

import pytest


FORMAL = [
    ("stay", "remain"),
    ("stays", "remains"),
    ("keeps", "preserves"),
    ("needs", "requires"),
    ("hold", "retain"),
    ("have", "provide"),
    ("put", "provide"),
    ("tell", "distinguish"),
    ("right", "correct"),
    ("hand", "manual"),
]

LEGITIMATE = [
    ("run", "runs", "a number change, which `same_number_stem` already skips"),
    ("and", "while", "a connective, not a plain word with a formal twin"),
    ("a", "or", "a function word"),
    ("thing", "component", "vague to specific, which is the tool's own job"),
    ("Some", "Caller-injected", "the same, at 4 characters to 15"),
    ("the", "execution", "not a substitution at all in meaning"),
    ("so", "leaving", "`so <clause>` to a participial phrase: a restructure"),
    ("has", "details", "the declared alignment artefact, not a swap"),
    ("keeps", "keep", "shorter, so out of scope by construction"),
    ("stays", "is", "shorter"),
]


def test_the_reported_family_is_refused(kv):
    assert FORMAL, "EMPTY: every assertion below would pass on no input"
    for was, now in FORMAL:
        got = kv.formal_swaps(f"the parser {was} open", f"the parser {now} open")
        assert got == [(was, now)], (was, now, got)


def test_no_legitimate_swap_is_refused(kv):
    assert LEGITIMATE, "EMPTY: this control would pass on no input"
    for was, now, why in LEGITIMATE:
        got = kv.formal_swaps(f"the parser {was} open", f"the parser {now} open")
        assert got == [], (was, now, why, got)


def test_longer_is_required_and_is_not_the_rule(kv):
    """A plain word replaced by something SHORTER is not this rule's business."""
    assert kv.formal_swaps("it stays open", "it is open") == []
    assert kv.formal_swaps("it stays open", "it remains open") == [
        ("stays", "remains")]


def test_the_list_holds_no_function_words(kv):
    """The exclusions are the measurement, so they are asserted as absences."""
    for w in ("so", "but", "also", "and", "has", "had", "more", "most",
              "now", "then", "about", "the", "a", "it", "is"):
        assert w not in kv.PLAIN_WORDS, w


def test_a_refused_formal_swap_is_named_in_the_report(kv, tmp_path,
                                                      monkeypatch):
    """The refusal has to say WHICH words, or the reader cannot judge it."""
    got = kv.formal_swaps("the parser stays open and needs a flag",
                          "the parser remains open and requires a flag")
    assert got == [("stays", "remains"), ("needs", "requires")], got


IDIOMS = [
    ("done by hand", "done manually", "`by hand` is two words for one"),
    ("pick this up right now", "pick this up immediately",
     "`right now` likewise"),
    ("the hand-edited rows", "the manually edited rows",
     "`hand-edited` is ONE token, invisible to a one-to-one swap"),
]


def test_a_multi_word_idiom_cannot_reach_the_rule(kv):
    assert IDIOMS, "EMPTY: this control would pass on no input"
    for old, new, why in IDIOMS:
        assert kv.formal_swaps(old, new) == [], (old, new, why)


def test_the_hand_instance_fires_on_the_sense_that_was_reported(kv):
    """`hand` was offered as a member that cannot fire correctly here. It can."""
    assert kv.formal_swaps("no longer costs a hand step",
                           "no longer costs a manual step") == [("hand", "manual")]
    assert kv.formal_swaps("Hand the strategy only bars 0..t",
                           "Provide the strategy only bars 0..t") == [("Hand", "Provide")]


def test_the_gate_refuses_the_edit_and_names_the_pair(kv):
    """End to end through `merge`, which is where a reader meets it."""
    lines = ["# Doc", "", "The parser stays open until the session ends.", ""]
    _m, applied, refused, _d = kv.merge(
        list(lines),
        [{"specialist": "prose",
          "edits": [{"op": "replace", "line": 3, "old": lines[2],
                     "new": "The parser remains open until the session ends."}]}],
        set(range(1, len(lines) + 1)), (), [(0, 1, "Doc")])
    assert not applied, applied
    assert len(refused) == 1, refused
    reason = refused[0][2]
    assert "`stays` -> `remains`" in reason, reason
    assert "longer one that says the same thing" in reason, reason


def test_the_control_an_ordinary_shortening_still_lands(kv):
    """Without this the case above is satisfied by a merge that refuses all."""
    lines = ["# Doc", "", "It is worth noting that the parser stays open.", ""]
    _m, applied, refused, _d = kv.merge(
        list(lines),
        [{"specialist": "prose",
          "edits": [{"op": "replace", "line": 3, "old": lines[2],
                     "new": "The parser stays open."}]}],
        set(range(1, len(lines) + 1)), (), [(0, 1, "Doc")])
    assert applied and not refused, (applied, refused)


def test_an_equal_length_reword_is_not_this_rule(kv):
    """`>` and not `>=`, asserted because the audit could not see the flip."""
    assert kv.formal_swaps("it keeps open", "it holds open") == []
    assert kv.formal_swaps("it must stay", "it must hold") == []


def test_an_agreement_change_between_two_members_is_not_refused(kv):
    """`keep -> keeps` is longer AND both words are on the list."""
    for was, now in (("keep", "keeps"), ("stay", "stays"), ("hold", "holds"),
                     ("need", "needs"), ("make", "makes"), ("end", "ends")):
        got = kv.formal_swaps(f"the gate {was} open", f"the gate {now} open")
        assert got == [], (was, now, got)
