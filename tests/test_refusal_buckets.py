"""Every edit that did not land gets a row, and the headline adds up."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import REPO

DOC = """# Handbook

The importer reads the manifest and resolves every symbol that it names today.
The scheduler reads the queue and resolves every symbol that it names today.
The compactor reads the map and resolves every symbol that it names today.
"""


def _job(lines):
    """Three lines in a row. The last replacement drops the full stop, so a
    gate refuses it and the block it sits in rolls back."""
    return {"specialist": "structure", "lo": 1, "hi": len(lines), "edits": [
        {"line": 3, "old": lines[2], "new": "The importer resolves it.",
         "why": "long sentence"},
        {"line": 4, "old": lines[3], "new": "The scheduler resolves it.",
         "why": "long sentence"},
        {"line": 5, "old": lines[4], "new": "The compactor resolves it",
         "why": "long sentence"},
    ]}


def _buckets(kv, n_jobs):
    """What the headline would print, as numbers."""
    lines = DOC.rstrip("\n").split("\n")
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    results = [_job(lines) for _ in range(n_jobs)]
    _out, applied, refused, _ = kv.merge(
        lines, results, kv.editable_lines(prose, tables, headings, quotes),
        (), headings)
    owned = [r for r in refused if r[2].startswith("already changed by ")]
    return {"proposed": sum(len(r["edits"]) for r in results),
            "applied": len(applied),
            "gates": len(refused) - len(owned),
            "owned": len(owned)}


def test_one_job_adds_up(kv):
    """The case that always worked, kept so the fix cannot buy the two-job
    case by breaking this one. Three edits, three rows, no double-counting:
    line 5 is refused by a gate and must not also get a rollback row."""
    b = _buckets(kv, 1)

    assert b == {"proposed": 3, "applied": 0, "gates": 3, "owned": 0}


def test_two_jobs_on_the_same_lines_add_up(kv):
    """The defect. Six edits and four rows: the two that were applied and then
    rolled back were read as repeats of the two the other job lost to the
    owner rule, and vanished from every bucket."""
    b = _buckets(kv, 2)

    assert b["applied"] + b["gates"] + b["owned"] == b["proposed"], b


def test_the_rolled_back_rows_say_what_broke_the_block(kv):
    """A row is only worth counting if it tells the reader something. Both
    recovered rows name the line that was refused, not just the block."""
    lines = DOC.rstrip("\n").split("\n")
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    _out, _ap, refused, _ = kv.merge(
        lines, [_job(lines), _job(lines)],
        kv.editable_lines(prose, tables, headings, quotes), (), headings)

    blocks = [r for r in refused if "line 5 was refused" in r[2]]

    assert sorted(r[0] for r in blocks) == [3, 4], refused


