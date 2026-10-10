"""A status qualifier now fails hard; a short aphorism stays a
known, deliberate gap.
"""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

STATUS_ORIG = """# Deploy Policy

## Merges

Use manual approval for merges to main. This guidance is superseded by the
auto-merge policy.
"""

STATUS_EDIT_DELETED = """# Deploy Policy

## Merges

Use manual approval for merges to main.
"""

STATUS_EDIT_KEPT = """# Deploy Policy

## Merges

Manual approval for merges to main is superseded by the auto-merge policy.
"""

APHORISM_ORIG = """# Decisions

## Recording

Decisions must be written down. A blank is not a decision.
"""

APHORISM_EDIT_DELETED = """# Decisions

## Recording

Decisions must be written down.
"""


def _verify(tmp_path, orig, edit, name="t"):
    o, n = tmp_path / f"{name}.md", tmp_path / f"{name}.kv.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_a_deleted_supersession_notice_is_rules_lost(tmp_path):
    """Retired guidance must not read as current guidance."""
    r = _verify(tmp_path, STATUS_ORIG, STATUS_EDIT_DELETED, "status_gone")

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "superseded by the auto-merge policy" in r.stdout, r.stdout


def test_a_reworded_supersession_notice_still_passes(tmp_path):
    """Counterweight: folding the fact into a shorter sentence is correct
    work and must not hard-fail."""
    r = _verify(tmp_path, STATUS_ORIG, STATUS_EDIT_KEPT, "status_kept")

    assert r.returncode != 1, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout


def test_a_deleted_short_aphorism_is_a_known_gap_not_fixed_here(tmp_path):
    """Pins the CURRENT, documented behaviour -- silent PASS."""
    r = _verify(tmp_path, APHORISM_ORIG, APHORISM_EDIT_DELETED,
                "aphorism_gone")

    assert r.returncode == 0, r.stdout
    assert "content dropped" not in r.stdout, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout
