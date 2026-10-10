"""A crash must not read as bad input."""

import sys

import pytest

from conftest import run_tool

pytestmark = pytest.mark.regression

BAD_MARKER = """# Notes

<!-- kv:allow-shape inanimate perciever -->

The scheduler under the hood retries every job that fails.
"""


def test_a_refusal_the_caller_can_fix_still_exits_2(doc):
    """One line, no traceback. This is the half that must not change."""
    r = run_tool("plan", doc(BAD_MARKER))

    assert r.returncode == 2, r.stderr
    assert "is not a shape" in r.stderr, r.stderr
    assert "Closest is 'inanimate perceiver'" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, r.stderr


def test_a_crash_is_not_reported_as_bad_input(kv, monkeypatch, doc):
    """A plain ValueError from inside a command has to reach the caller."""
    src = doc("# Notes\n\nThe scheduler under the hood retries every job.\n")

    def boom(*_a, **_k):
        raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(kv, "find_shapes", boom)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "plan", str(src)])

    with pytest.raises(ValueError, match="closed file"):
        kv.main()


def test_usage_error_is_still_a_value_error(kv):
    """Selftest blocks and older callers catch the wide type."""
    assert issubclass(kv.UsageError, ValueError)
