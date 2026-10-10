"""A structural move must appear in the run record."""

from killverbosity import moves


def test_a_move_is_recorded():
    applied = [(117, "move the dated warning down", "move", None)]
    assert moves.records(applied) == [
        {"op": "move", "line": 117, "why": "move the dated warning down"}]


def test_a_move_block_is_recorded_too():
    applied = [(7, "into the summary", "move-block", None)]
    assert [r["op"] for r in moves.records(applied)] == ["move-block"]


def test_ordinary_edits_are_not_recorded_as_moves():
    applied = [(3, "cut a filler word", "replace", None),
               (9, "drop a dead line", "delete", None),
               (12, "add the summary", "insert", None)]
    assert moves.records(applied) == []


def test_only_the_moves_come_back_from_a_mixed_run():
    applied = [(3, "cut filler", "replace", None),
               (117, "move the warning", "move", None),
               (12, "add summary", "insert", None),
               (7, "into summary", "move-block", None)]
    got = moves.records(applied)
    assert [r["line"] for r in got] == [117, 7]


def test_no_moves_is_an_empty_list_not_a_missing_key():
    assert moves.records([]) == []
