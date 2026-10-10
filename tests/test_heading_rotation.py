"""Pairing headings when a section moved and was renamed in the same run."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))

OLD = ["Sec 0", "Sec 1", "Sec 2"]
BODIES = {t: set(f"{t} w{i} x{i} y{i} z{i}".split()) for i, t in enumerate(OLD)}


def _heads(names):
    return [(i * 4 + 1, 2, t) for i, t in enumerate(names)]


def _moves(kv, new, bodies):
    return kv.heading_moves(_heads(OLD), _heads(new), BODIES, bodies)


def test_a_reorder_does_not_report_a_section_that_is_still_there(kv):
    """`Sec 0` moved down; both sections above it were renamed."""
    pairs, gone = _moves(kv, ["New Sec 1", "Sec 0", "New Sec 2"],
                         {"New Sec 1": BODIES["Sec 1"],
                          "Sec 0": BODIES["Sec 0"],
                          "New Sec 2": BODIES["Sec 2"]})

    assert not gone, gone
    assert sorted(pairs) == [("Sec 1", "New Sec 1"), ("Sec 2", "New Sec 2")]


def test_a_real_deletion_among_the_renames_is_still_reported(kv):
    """The correction must not swallow the thing the report exists for."""
    pairs, gone = _moves(kv, ["New Sec 2", "Sec 0"],
                         {"New Sec 2": BODIES["Sec 2"],
                          "Sec 0": BODIES["Sec 0"]})

    assert gone == ["Sec 1"], (pairs, gone)
    assert pairs == [("Sec 2", "New Sec 2")]


def test_a_pair_the_position_pass_got_right_is_left_alone(kv):
    """A rename in place, bodies unchanged. The body pass agrees and stops."""
    pairs, gone = _moves(kv, ["Sec 0", "Renamed", "Sec 2"],
                         {"Sec 0": BODIES["Sec 0"],
                          "Renamed": BODIES["Sec 1"],
                          "Sec 2": BODIES["Sec 2"]})

    assert not gone, gone
    assert pairs == [("Sec 1", "Renamed")]


def test_a_section_renamed_and_rewritten_keeps_its_pair(kv):
    """No body in common, so the names are the only evidence left."""
    pairs, gone = _moves(kv, ["Sec 0", "Sec 1 rewritten", "Sec 2"],
                         {"Sec 0": BODIES["Sec 0"],
                          "Sec 1 rewritten": set("all new words now".split()),
                          "Sec 2": BODIES["Sec 2"]})

    assert not gone, gone
    assert pairs == [("Sec 1", "Sec 1 rewritten")]


def test_a_deletion_beside_a_new_section_is_not_called_a_rename(kv):
    """`Sec 1` deleted and an unrelated `Appendix` written in its place."""
    pairs, gone = _moves(kv, ["Sec 0", "Appendix", "Sec 2"],
                         {"Sec 0": BODIES["Sec 0"],
                          "Appendix": set("further reading and links".split()),
                          "Sec 2": BODIES["Sec 2"]})

    assert gone == ["Sec 1"], (pairs, gone)
    assert not pairs, pairs


def test_a_shared_function_word_is_not_evidence_of_a_rename(kv):
    """`The notes` deleted, `The appendix` written where it stood."""
    tail = {"t1", "t2", "t3", "t4"}
    gone = kv.heading_moves(
        [(1, 2, "The notes"), (5, 2, "Tail")],
        [(1, 2, "The appendix"), (5, 2, "Tail")],
        {"The notes": set("a1 a2 a3 a4 a5".split()), "Tail": tail},
        {"The appendix": set("x1 x2 x3 x4 x5".split()), "Tail": tail})[1]
    kept = kv.heading_moves(
        [(1, 2, "Considered alternatives"), (5, 2, "Tail")],
        [(1, 2, "Alternatives"), (5, 2, "Tail")],
        {"Considered alternatives": set("a1 a2 a3 a4 a5".split()),
         "Tail": tail},
        {"Alternatives": set("x1 x2 x3 x4 x5".split()), "Tail": tail})[0]

    assert gone == ["The notes"], gone
    assert kept == [("Considered alternatives", "Alternatives")], kept


def test_a_short_section_is_not_swallowed_by_a_long_one(kv):
    """A three-word section deleted, beside a long one that was renamed."""
    small = set("see the runbook".split())
    large = small | {f"w{i}" for i in range(60)}
    pairs, gone = kv.heading_moves(
        [(1, 2, "Tiny"), (5, 2, "Huge")], [(1, 2, "Huge renamed")],
        {"Tiny": small, "Huge": large}, {"Huge renamed": large})

    assert "Tiny" in gone, (pairs, gone)
    assert pairs == [("Huge", "Huge renamed")]


def test_two_sections_with_the_same_name_lose_only_one(kv):
    """`kept` is a list of heading text, and a restored pair removed every
    entry matching it. Two sections called `Notes`, one renamed and one
    deleted, reported nothing gone."""
    old = [(1, 2, "Notes"), (5, 2, "Notes"), (9, 2, "Tail")]
    new = [(1, 2, "Notes rewritten"), (5, 2, "Tail")]
    o_body = {"Notes": set("shared a b c".split()),
              "Tail": set("t1 t2 t3 t4".split())}
    n_body = {"Notes rewritten": set("all different words here".split()),
              "Tail": o_body["Tail"]}

    pairs, gone = kv.heading_moves(old, new, o_body, n_body)

    assert gone == ["Notes"], (pairs, gone)
    assert pairs == [("Notes", "Notes rewritten")]
