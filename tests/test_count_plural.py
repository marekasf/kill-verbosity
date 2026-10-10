"""A count and its noun agree. `1 candidates` was printed on a real run."""

from __future__ import annotations

import sys

from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

ONE = ("The plan is simple and it is worth noting that the work is done.\n\n"
       "See docs/x.md.\n")


def test_count_agrees_with_its_noun(kv):
    assert kv.count(1, "chunk") == "1 chunk"
    assert kv.count(0, "chunk") == "0 chunks"
    assert kv.count(2, "chunk") == "2 chunks"
    assert kv.count(1, "entry", "entries") == "1 entry"
    assert kv.count(3, "entry", "entries") == "3 entries"


def test_a_file_with_one_chunk_and_one_hit_says_so(tmp_path):
    """End to end. The two counts that can be 1 are both in `plan`."""
    doc = tmp_path / "one.md"
    doc.write_text(ONE)

    out = run_tool("plan", str(doc)).stdout

    assert "1 chunk " in out, out
    assert "1 candidate." in out, out
    assert "1 chunks" not in out and "1 candidates" not in out, out
