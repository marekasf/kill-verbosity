"""The CONTROL for T68, written before the fix and pinning what is wrong now."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO))

from killverbosity import blame
from killverbosity._legacy import DUPLICATE_FROM_WORDS, repeat_key

OPENING = " ".join(f"word{i}" for i in range(DUPLICATE_FROM_WORDS))

CLUSTER = [{"text": f"{OPENING} and then the cluster continues",
            "lines": [40]}]


def _result(specialist, tail, line, group=None):
    edit = {"line": line, "old": "x", "new": f"{OPENING} {tail}"}
    if group is not None:
        edit["group"] = group
    return {"specialist": specialist, "edits": [edit]}


def _rows(results):
    return blame.repeat_rows(CLUSTER, results, repeat_key, DUPLICATE_FROM_WORDS)


def test_both_edits_really_do_match_the_fingerprint():
    """The premise. Without this the rest of the file is vacuous."""
    only_prose = _rows([_result("prose", "rewritten by prose", 11)])
    only_noise = _rows([_result("noise", "rewritten by noise", 22)])
    assert [r[1] for r in only_prose] == ["prose"], only_prose
    assert [r[1] for r in only_noise] == ["noise"], only_noise


def test_every_matching_edit_is_blamed_for_the_same_one_cluster():
    """DEFECT PINNED, and it is NOT the defect the report described."""
    rows = _rows([_result("prose", "rewritten by prose", 11),
                  _result("noise", "rewritten by noise", 22)])
    assert len(rows) == 2, f"one row per matching edit, got {rows}"
    assert {r[1] for r in rows} == {"prose", "noise"}, rows
    assert len({r[2] for r in rows}) == 1, rows
    assert all(len(r) == 3 for r in rows), rows
    assert "guess" not in " ".join(str(x) for r in rows for x in r).lower(), rows


def test_order_changes_the_rows_order_and_nothing_else():
    """The assertion my first draft got wrong, kept as a note to the next reader."""
    forward = _rows([_result("prose", "rewritten by prose", 11),
                     _result("noise", "rewritten by noise", 22)])
    reverse = _rows([_result("noise", "rewritten by noise", 22),
                     _result("prose", "rewritten by prose", 11)])
    assert [r[1] for r in forward] == ["prose", "noise"], forward
    assert [r[1] for r in reverse] == ["noise", "prose"], reverse
    assert set(forward) == set(reverse), (forward, reverse)


def test_group_is_carried_on_the_edits_and_ignored_by_blame():
    """The fix's raw material, asserted present and asserted unused."""
    assert "group" not in blame.__dict__, (
        "blame now references a group; the guess may be gone - re-point this "
        "file at the derived behaviour")
    src = (REPO / "killverbosity" / "blame.py").read_text()
    assert "group" not in src, "blame.py now mentions group - see above"

    tagged = _rows([_result("prose", "rewritten by prose", 11, group="jobA"),
                    _result("noise", "rewritten by noise", 22, group="jobB")])
    untagged = _rows([_result("prose", "rewritten by prose", 11),
                      _result("noise", "rewritten by noise", 22)])
    assert tagged == untagged, (
        "the group key changed the answer, so it is no longer ignored")
