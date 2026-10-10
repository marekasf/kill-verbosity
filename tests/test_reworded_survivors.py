"""A reword that only changed the grammar is not a lost sentence."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from killverbosity import inflect, rescue

from conftest import run_tool


SAME = [
    ("imported", "import"),
    ("referenced", "reference"),
    ("causes", "cause"),
    ("listed", "list"),
    ("running", "run"),
    ("stopping", "stop"),
    ("planned", "plan"),
    ("carries", "carry"),
    ("boxes", "box"),
    ("moved", "move"),
    ("matches", "match"),
    ("applied", "apply"),
    ("referencing", "reference"),
    ("panicked", "panic"),
    ("panicking", "panic"),
    ("backed", "back"),
]

DIFFERENT = [
    ("cares", "cars"),
    ("planned", "plane"),
    ("caring", "carting"),
    ("winning", "wine"),
    ("hopped", "hope"),
    ("basses", "base"),
    ("cars", "caring"),
    ("mops", "moped"),
]


@pytest.mark.parametrize(("a", "b"), SAME)
def test_two_forms_of_one_word_match_either_way_round(a, b):
    assert a in inflect.spread([b]), f"{b} does not reach {a}"
    assert b in inflect.spread([a]), f"{a} does not reach {b}"


@pytest.mark.parametrize(("a", "b"), DIFFERENT)
def test_two_different_words_do_not_match(a, b):
    assert a not in inflect.spread([b]), f"{b} wrongly reaches {a}"
    assert b not in inflect.spread([a]), f"{a} wrongly reaches {b}"


def test_share_counts_the_words_the_author_wrote():
    """The denominator is the original sentence, not its expansion."""
    was = {"confirmed", "imported", "referenced", "across", "three"}
    now = {"three", "import", "reference"}

    assert inflect.share(was, inflect.spread(now)) == pytest.approx(0.6)
    assert len(was & now) / len(was) == pytest.approx(0.2)


def test_share_of_nothing_is_zero():
    assert inflect.share(set(), inflect.spread(["anything"])) == 0.0


def test_one_survivor_answers_for_one_deleted_sentence():
    """Without it, a short line inside several deletions pardons them all."""
    words = {"alpha", "beta", "gamma"}
    deleted = [(1, inflect.spread(words)), (2, inflect.spread(words))]

    got = rescue.answered(deleted, [(0, words)], 0.5)

    assert len(got) == 1


def test_a_survivor_claimed_by_the_first_list_is_not_offered_to_the_second():
    words = {"alpha", "beta", "gamma"}
    taken: set[int] = set()

    first = rescue.answered([(1, inflect.spread(words))],
                            [(0, words)], 0.5, taken)
    second = rescue.answered([(2, inflect.spread(words))],
                             [(0, words)], 0.5, taken)

    assert first == {1}
    assert second == set()


def test_the_highest_scoring_pair_is_claimed_first():
    """A weak pair never takes a survivor from a strong one."""
    survivor = {"alpha", "beta", "gamma", "delta"}

    got = rescue.answered(
        [(1, inflect.spread({"alpha", "beta", "gamma", "zeta"})),
         (2, inflect.spread(survivor | {"epsilon"}))],
        [(0, survivor)], 0.5)

    assert got == {2}


def test_a_tie_goes_to_the_earlier_sentence():
    words = {"alpha", "beta", "gamma"}

    got = rescue.answered(
        [(7, inflect.spread(words)), (2, inflect.spread(words))],
        [(0, words)], 0.5)

    assert got == {2}


def test_under_three_shared_words_nothing_is_claimed():
    got = rescue.answered([(1, inflect.spread({"alpha", "beta"}))],
                          [(0, {"alpha", "beta"})], 0.5)

    assert got == set()


def _pair(tmp_path, was, now):
    a, b = tmp_path / "was.md", tmp_path / "now.md"
    a.write_text(was)
    b.write_text(now)
    return a, b


def test_a_reworded_sentence_is_not_reported_dropped(tmp_path):
    o, n = _pair(
        tmp_path,
        "# Notes\n\nThe fix is to move the Go toolchain to the highest "
        "version listed, then let the job re-run.\n\nThere is usually a "
        "second, compounding cause: an EOL Terraform client.\n\nConfirmed "
        "imported and referenced across all three service repositories.\n",
        "# Notes\n\nBump the Go toolchain to the highest version.\n\nAn EOL "
        "Terraform client also causes failure.\n\nAll three service "
        "repositories import and reference it.\n",
    )

    r = run_tool("verify", o, n)

    assert r.returncode == 0, r.stdout
    assert "content dropped" not in r.stdout, r.stdout


def test_a_deleted_rule_is_still_reported(tmp_path):
    """The control. Rescuing rewords must not pardon a deletion."""
    o, n = _pair(
        tmp_path,
        "# Notes\n\nBump the Go toolchain to the highest version.\n\nNever "
        "run the importer against the production warehouse without a "
        "snapshot.\n",
        "# Notes\n\nBump the Go toolchain to the highest version.\n",
    )

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout


def test_a_sentence_that_lost_its_count_is_not_called_a_survivor(tmp_path):
    """Words alone score it 1.0. The number it carried is gone from the file."""
    o, n = _pair(
        tmp_path,
        "# Ticket\n\nThe form asks for three kinds of name: users, service "
        "accounts and teams.\n",
        "# Ticket\n\nThe form asks for teams.\n",
    )

    r = run_tool("verify", o, n)

    assert r.returncode == 3, r.stdout
    assert "three kinds of name" in r.stdout, r.stdout
