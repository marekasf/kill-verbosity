"""A source line loses its commit sha and the gate says it was noise going."""

from __future__ import annotations

import sys

import pytest
from conftest import REPO, run_tool

sys.path.insert(0, str(REPO / "bin"))

from killverbosity import _legacy as kv

DOC = """# Review

%s
Line numbers below refer to that tree.

## The retry budget is read from the wrong field

At `proxy.py:143` the budget is read off the request rather than the route.
Fix: read it off the route, falling back to the request only when unset.
"""

CUT = DOC % ""


def _excused_as_process(tmp_path, source_line: str) -> bool:
    """Did `verify` file the lost sha under 'cutting those is the job'?"""
    a, b = tmp_path / "orig.md", tmp_path / "new.md"
    a.write_text(DOC % source_line)
    b.write_text(CUT)
    return "sat only in a commit ref" in run_tool("verify", a, b).stdout


EVIDENCE = [
    "Source: `ai-assistant-gateway` at `5bb0c2a`, read 9 September.",
    "Sources: `ai-assistant-gateway` at `5bb0c2a`, checked 9 September.",
    "- Source: `ai-assistant-gateway` at `5bb0c2a`.",
    "The gateway sat at `5bb0c2a`, verified 9 September.",
    "Checked against `ai-assistant-gateway` at `5bb0c2a`, 9 September.",
    "Verified against `ai-assistant-gateway` at `5bb0c2a`.",
    "The behaviour was measured at `5bb0c2a`.",
]

PROCESS = [
    "This dates from Oct 2025 (`5bb0c2a`).",
    "Built from `4737d6b`.",
    "Sources of truth are listed below; this was built from `4737d6b`.",
]


@pytest.mark.parametrize("line", EVIDENCE)
def test_a_governed_ref_is_evidence_and_its_loss_is_not_excused(tmp_path,
                                                                line):
    assert not _excused_as_process(tmp_path, line)


@pytest.mark.parametrize("line", PROCESS)
def test_the_control_a_process_ref_is_still_safe_to_cut(tmp_path, line):
    """The negative control, and the reason the carve-out is narrow."""
    assert _excused_as_process(tmp_path, line)


def test_the_shape_scan_and_the_pardon_agree(tmp_path):
    """Both halves in one input, because they are one decision."""
    a = tmp_path / "orig.md"
    a.write_text(DOC % "Source: `ai-assistant-gateway` at `5bb0c2a`, "
                       "read 9 September.")

    planned = run_tool("plan", a).stdout

    assert "commit or checkout ref" not in planned, planned
    assert not _excused_as_process(
        tmp_path, "Source: `ai-assistant-gateway` at `5bb0c2a`, "
                  "read 9 September.")


def test_a_sha_is_required_before_anything_is_excused():
    """`checkout master` names a working copy and cites nothing."""
    still_fires = [
        "We verified this against checkout master.",
        "Findings come from the local main checkout.",
        "Rebuilt from checkout main.",
    ]
    for line in still_fires:
        assert [c for _, c, _ in kv.find_shapes([line])] \
            == ["commit or checkout ref"], line

    assert not kv.find_shapes(["We verified this against `5bb0c2a`, "
                               "the merge commit."])
