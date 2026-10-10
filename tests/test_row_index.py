"""Numbers that are markers, not values."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))



def _numbers(kv, text):
    return kv.facts(text).get("number", set())


def test_an_inline_enumeration_is_not_two_facts(kv):
    n = _numbers(kv, "There are 2 reasons for this: 1) no outbound "
                     "connections 2) our SLA stops depending on theirs.")
    assert n == {"2"}, n


def test_the_count_in_front_of_it_survives_being_spelled(kv):
    """"There are 2 reasons" → "Two reasons" is the skill's own prose rule,
    and the gate read the spelled form as a deleted number."""
    assert _numbers(kv, "There are 2 reasons for this.") == \
        _numbers(kv, "Two reasons for this.") == {"2"}


def test_a_numbered_list_marker_is_not_a_fact(kv):
    assert _numbers(kv, "1. the queue counts files\n2. it grows") == set()


def test_a_table_row_index_is_not_a_fact(kv):
    assert _numbers(kv, "| 1 | scan |\n| 2 | merge |") == set()


def test_a_bracketed_number_is_still_a_value(kv):
    """The lookbehind wants whitespace and finds the bracket. That is the
    footnote form, so it stays protected."""
    assert _numbers(kv, "The relay handles it (2) today.") == {"2"}


def test_a_back_reference_reads_as_a_marker_and_is_dropped(kv):
    """`see 3)` cannot be told from an opener by shape, so it is blanked and a
    rewrite may drop that 3 with nothing said. The other way round costs a run
    that fails on the edit the skill asked for; this costs a line a person is
    reading anyway."""
    assert _numbers(kv, "The relay handles it, see 3) for the rest.") == set()


