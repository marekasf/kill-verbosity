"""A swap that changes what a sentence CLAIMS is refused, and the record is readable."""

from __future__ import annotations

import pytest

REFUSED = [("holds", "needs", "a modal"),
           ("needs", "turns", "a modal"),
           ("every", "no", "a quantifier"),
           ("proves", "tests", "a claim verb")]

ALLOWED = [("passes", "reads"), ("taking", "took"), ("doubling", "doubled"),
           ("Every", "every"), ("miss", "bypass"),
           ("is", "are"), ("is", "has"), ("handles", "is")]

BY_HAND_CAUGHT = [("ALLOWS", "allowed", "a permission verb"),
                  ("consulted", "checked", "a claim verb"),
                  ("is", "handles", "a relation for an action"),
                  ("has", "covers", "a relation for an action")]

BY_HAND_MISSED = [("performs", "ran"),
                  ("ages", "invalidates"), ("it", "Row"), ("miss", "bypass")]

REPORTING = [("said", "claimed"), ("said", "reported"), ("says", "reports"),
             ("says", "notes"), ("claim", "guarantee")]

REPORTING_HOLES = [("performs", "executes"), ("refuses", "rejects"),
                   ("dies", "fails"), ("names", "records"),
                   ("miss", "bypass")]

ANTONYM_HOLES = [("before", "after"), ("increase", "drop"),
                 ("above", "below"), ("upstream", "downstream")]


ONE_SIDED = [("holds", "keeps", "a modal"),
             ("needs", "turns", "a modal"),
             ("several", "every", "a quantifier"),
             ("finds", "proves", "a claim verb"),
             ("said", "shipped", "a reporting verb"),
             ("held", "notes", "a reporting verb")]


@pytest.mark.parametrize("was,now,what", REFUSED + ONE_SIDED)
def test_a_swap_across_a_meaning_set_is_caught(kv, was, now, what):
    got = kv.meaning_swaps(f"The gate {was} for each row.",
                           f"The gate {now} for each row.")
    assert got == [(was, now, what)], got


@pytest.mark.parametrize("was,now", ALLOWED)
def test_a_swap_outside_the_sets_is_left_alone(kv, was, now):
    """The controls, and the last two are declared holes rather than passes."""
    assert kv.meaning_swaps(f"The gate {was} for each row.",
                            f"The gate {now} for each row.") == []


@pytest.mark.parametrize("was,now,what", BY_HAND_CAUGHT)
def test_a_swap_the_reporters_named_by_hand_is_caught(kv, was, now, what):
    got = kv.meaning_swaps(f"The gate {was} for each row.",
                           f"The gate {now} for each row.")
    assert got == [(was, now, what)], got


@pytest.mark.parametrize("was,now,what", [(a, b, "a reporting verb")
                                          for a, b in REPORTING])
def test_a_reporting_verb_swap_is_caught(kv, was, now, what):
    """Five of run 3's ten remaining leaks, and one more from run 2."""
    got = kv.meaning_swaps(f"The gate {was} so.", f"The gate {now} so.")
    assert got == [(was, now, what)], got


@pytest.mark.parametrize("was,now", REPORTING_HOLES)
def test_the_other_five_leaks_stay_declared_holes(kv, was, now):
    """The bound the reporting session put on its own proposal."""
    assert kv.meaning_swaps(f"The gate {was} so.",
                            f"The gate {now} so.") == []


@pytest.mark.parametrize("was,now", ANTONYM_HOLES)
def test_an_antonym_swap_is_a_declared_hole(kv, was, now):
    """The hole a cross-check found, and the refutation of the inversion."""
    assert kv.meaning_swaps(f"The gate ran {was} the row.",
                            f"The gate ran {now} the row.") == []


@pytest.mark.parametrize("was,now", BY_HAND_MISSED)
def test_a_swap_the_reporters_named_is_declared_missed(kv, was, now):
    """The residue, asserted rather than described."""
    assert kv.meaning_swaps(f"The gate {was} for each row.",
                            f"The gate {now} for each row.") == []


def test_the_copula_rule_is_one_direction_only(kv):
    """The control that decides whether the copula rule is a rule or a ban."""
    assert kv.meaning_swaps("The gate is the row filter.",
                            "The gate handles the row filter.") != []
    assert kv.meaning_swaps("The gate handles the row filter.",
                            "The gate is the row filter.") == []


def test_a_swap_that_two_rules_see_is_reported_once(kv):
    """`is -> proves` is a copula AND a claim verb, and it is one swap."""
    got = kv.meaning_swaps("The gate is the row filter.",
                           "The gate proves the row filter.")
    assert got == [("is", "proves", "a claim verb")], got


def test_dropping_a_modal_while_shortening_is_not_a_swap(kv):
    """The deliberate hole, asserted, because it is what keeps the rate down."""
    assert kv.meaning_swaps("You must always run the tests before merging.",
                            "Run the tests before merging.") == []


def test_the_gate_refuses_the_edit_and_names_the_pair(kv):
    """End to end through `merge`, which is where a reader meets it."""
    lines = ["# Doc", "", "Every gate copies the digest of the bars.", ""]
    _m, applied, refused, _d = kv.merge(
        list(lines),
        [{"specialist": "prose",
          "edits": [{"op": "replace", "line": 3, "old": lines[2],
                     "new": "No gate copies the digest of the bars."}]}],
        set(range(1, len(lines) + 1)), (), [(0, 1, "Doc")])
    assert not applied, applied
    assert len(refused) == 1, refused
    reason = refused[0][2]
    assert "`Every` -> `No`" in reason, reason
    assert "a quantifier" in reason, reason


def test_the_control_an_ordinary_shortening_still_lands(kv):
    """Without this the test above is satisfied by a merge that refuses all."""
    lines = ["# Doc", "", "It is worth noting that the gate copies a digest.",
             ""]
    _m, applied, refused, _d = kv.merge(
        list(lines),
        [{"specialist": "prose",
          "edits": [{"op": "replace", "line": 3, "old": lines[2],
                     "new": "The gate copies a digest."}]}],
        set(range(1, len(lines) + 1)), (), [(0, 1, "Doc")])
    assert applied and not refused, (applied, refused)



LONG = ("Content keying ensures that perturbed gate copies of the digest of "
        "the bars are never confused with the originals, which is what the "
        "cache relies on when it bypasses a rebuild of the whole set.")


def test_the_excerpt_is_centred_on_the_swapped_word(kv):
    got = kv.swap_excerpt(LONG, "bypasses")
    assert "bypasses" in got, got
    assert len(got) <= 72, (len(got), got)
    assert got != " ".join(LONG.split())[:70], got


def test_a_short_line_comes_back_whole_and_unmarked(kv):
    """The control. Ellipses on a line that was never trimmed would say the
    reader is missing text when they are not."""
    short = "The gate bypasses a rebuild."
    assert kv.swap_excerpt(short, "bypasses") == short


def test_a_word_at_the_end_still_brings_its_context(kv):
    """The window has to slide rather than run off the end — a swap in the
    last clause is exactly where the head-of-line excerpt was least useful."""
    got = kv.swap_excerpt(LONG + " The digest is stable.", "stable")
    assert "stable" in got, got
    assert got.startswith("…"), got



WRITE_IS_NOT_A_REPORTING_VERB = [("records", "writes"), ("writes", "records"),
                                 ("logs", "writes"), ("wrote", "stored")]


@pytest.mark.parametrize("was,now", WRITE_IS_NOT_A_REPORTING_VERB)
def test_the_mechanical_sense_of_write_is_not_a_claim_change(kv, was, now):
    assert kv.meaning_swaps(f"The worker {was} the outcome to Loki.",
                            f"The worker {now} the outcome to Loki.") == []


def test_dropping_write_did_not_empty_the_reporting_set(kv):
    """The control. Every assertion above is satisfied by a set that no longer
    catches anything, which is what deleting the wrong line would produce."""
    assert kv.meaning_swaps("The row said the gate holds.",
                            "The row claimed the gate holds.") == [
        ("said", "claimed", "a reporting verb")]


NUMBER_ONLY = [("check", "checks"), ("checks", "check"), ("test's", "test"),
               ("proves", "prove"), ("need", "needs")]


@pytest.mark.parametrize("was,now", NUMBER_ONLY)
def test_a_plural_or_possessive_is_not_a_meaning_change(kv, was, now):
    assert kv.meaning_swaps(f"The gate {was} for each row.",
                            f"The gate {now} for each row.") == []


TENSE_STILL_COUNTS = [("shows", "showed", "a claim verb"),
                      ("check", "checked", "a claim verb"),
                      ("proves", "proven", "a claim verb"),
                      ("says", "said", "a reporting verb")]


@pytest.mark.parametrize("was,now,what", TENSE_STILL_COUNTS)
def test_a_tense_change_is_still_a_meaning_change(kv, was, now, what):
    got = kv.meaning_swaps(f"The gate {was} for each row.",
                           f"The gate {now} for each row.")
    assert got == [(was, now, what)], got


def test_the_number_skip_does_not_reach_a_two_letter_word(kv):
    """`is -> has` must stay a copula-for-a-copula control and not become a
    number match: stripping the `s` from a three-letter word would make
    `bare("has") == "ha"` and could collide with anything."""
    assert kv.same_number_stem("has", "have") is False
    assert kv.same_number_stem("is", "it") is False
    assert kv.same_number_stem("check", "checks") is True


def test_the_alignment_residue_is_declared_and_not_silent(kv):
    """7 of the 36 are difflib aligning a function word against a content word
    inside a larger rewrite. Each IS a real change to the sentence, so it is
    refused on purpose; what is unusable is the excerpt, which names two words
    never swapped for each other. Asserted so the day someone fixes the
    alignment this goes red and they update the residue instead of leaving a
    docstring claiming a hole that closed."""
    got = kv.meaning_swaps("The gate is the row filter for the set.",
                           "The gate is only the row filter for the set.")
    assert got == [], got
    assert kv.meaning_swaps("The gate reads the rows.",
                            "The gate reads only rows.") == [
        ("the", "only", "a quantifier")]
