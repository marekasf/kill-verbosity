"""The run budget is named BEFORE the wait, not only in the tail."""

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
KV = HERE / "kill-verbosity"

DOC = """# Report

It is important to note that the archival storage tier is, at the end of the
day, considerably less expensive than the standard tier in basically every
region we have looked at.
"""


def plan(tmp_path, *flags):
    """`run --dry-run` and not `plan`: the budget belongs to the command that
    SPAWNS, and `plan` takes no `--timeout` at all. A first draft of this file
    drove `plan`, argparse refused every `--timeout` flag, and the boundary
    case that must stay SILENT passed for that reason rather than for the one
    its name gives -- a vacuous pass that reads exactly like a held one."""
    doc = tmp_path / "report.md"
    doc.write_text(DOC)
    got = subprocess.run(
        [sys.executable, str(KV), "run", str(doc), "--dry-run", *flags],
        capture_output=True, text=True, cwd=tmp_path)
    assert got.returncode == 0, got.stderr[-800:]
    return got


def opening(err: str) -> str:
    """The banner line -- the one a reader sees before anything waits."""
    return next(ln for ln in err.splitlines() if ln.startswith("read as "))


def test_the_budget_is_on_the_opening_line(tmp_path):
    got = plan(tmp_path)
    assert "budget 3600s (--timeout)" in opening(got.stderr)


def test_a_budget_over_ten_minutes_says_what_a_shorter_caller_ceiling_costs(tmp_path):
    """Not the caller's ceiling -- that belongs to whatever spawned us and is
    not knowable here. Ours, so they can compare."""
    err = plan(tmp_path).stderr
    assert "kills it before it finishes" in err
    assert "lower --timeout" in err


def test_a_budget_that_fits_says_nothing_extra(tmp_path):
    """The control. A sentence printed on every run is one that stops being
    read, and the whole point is that it fires when it applies."""
    got = plan(tmp_path, "--timeout", "300")
    assert "budget 300s (--timeout)" in opening(got.stderr)
    assert "kills it before it finishes" not in got.stderr


@pytest.mark.parametrize("value, warned", [("600", False), ("601", True)])
def test_the_boundary_is_where_it_says_it_is(tmp_path, value, warned):
    err = plan(tmp_path, "--timeout", value).stderr
    assert ("kills it before it finishes" in err) is warned
