"""`verify` under-reports a dropped sentence."""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

ORIG = """# Decisions

## Recording

Decisions must be written down. A blank is not a decision.
"""

EDIT_DELETED = """# Decisions

## Recording

Decisions must be written down.
"""


def _verify(tmp_path, orig, edit, name="t"):
    o, n = tmp_path / f"{name}.md", tmp_path / f"{name}.kv.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_pass_names_the_dropped_sentence(tmp_path):
    r = _verify(tmp_path, ORIG, EDIT_DELETED, "aphorism_named")

    assert "A blank is not a decision." in r.stdout, r.stdout


def test_the_verdict_and_exit_code_do_not_change(tmp_path):
    """The reporting gap is fixed by naming, not by gating."""
    r = _verify(tmp_path, ORIG, EDIT_DELETED, "aphorism_verdict")

    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "content dropped" not in r.stdout, r.stdout
    assert "RULES LOST" not in r.stdout, r.stdout
