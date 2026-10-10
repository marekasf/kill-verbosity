"""`kv:keep` is per line (and its own wrap-continuation stops at the first
blank line), and a "Working rules (verbatim)" block is usually several rules
separated by blank lines -- so protecting it meant writing `kv:keep` on
every rule rather than once around the whole block.
"""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "bin"))


def test_a_block_between_the_markers_is_kept_across_blank_lines(kv):
    prose = [
        "# Working rules (verbatim)",
        "",
        "<!-- kv:freeze -->",
        "1. Never delete a decision without a citation.",
        "",
        "2. Every claim carries the command that produced it.",
        "<!-- kv:end -->",
        "",
        "Ordinary prose after the block, still editable.",
        "",
    ]
    kept = kv.keep_lines(prose)
    assert kept >= {3, 4, 5, 6, 7}, kept
    assert 9 not in kept, kept


def test_the_markers_themselves_are_kept(kv):
    prose = ["<!-- kv:freeze -->", "A rule.", "<!-- kv:end -->"]
    kept = kv.keep_lines(prose)
    assert kept == {1, 2, 3}, kept


def test_an_unterminated_freeze_runs_to_the_end_of_the_document(kv):
    prose = ["<!-- kv:freeze -->", "A rule.", "Another rule, never closed."]
    kept = kv.keep_lines(prose)
    assert kept == {1, 2, 3}, kept


def test_frozen_lines_are_excluded_from_editable_lines(kv):
    prose = [
        "<!-- kv:freeze -->",
        "You must always validate input before decoding it.",
        "<!-- kv:end -->",
        "Ordinary editable prose line here.",
    ]
    editable = kv.editable_lines(prose, tables=[], headings=[], quotes=[])
    assert 2 not in editable, editable
    assert 4 in editable, editable


def test_frozen_lines_never_fire_a_shape(kv):
    prose = [
        "<!-- kv:freeze -->",
        "You must always validate input before decoding it, no matter "
        "what the caller claims about it already being safe.",
        "<!-- kv:end -->",
    ]
    hits = kv.find_shapes(prose)
    frozen_hits = [h for h in hits if h[0] in (1, 2, 3)]
    assert frozen_hits == [], frozen_hits
