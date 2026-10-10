"""RULES LOST names the job(s) and specialist beside each lost line."""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

ORIG = """# Runbook

## Retries

The worker retries three times.

It is unclear whether the 30s budget covers the third attempt.
"""

EDITED = """# Runbook

## Retries

The worker retries three times.
"""


def _pair(tmp_path, orig=ORIG, edited=EDITED, name="t"):
    o, n = tmp_path / f"{name}.md", tmp_path / f"{name}.kv.md"
    o.write_text(orig)
    n.write_text(edited)
    return o, n


def test_no_run_record_prints_nothing_extra(tmp_path):
    """Standalone `verify`, no `.kvrun` beside the edited file: unchanged."""
    o, n = _pair(tmp_path)

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "sent to:" not in r.stdout, r.stdout


def test_a_record_with_no_job_spans_prints_nothing_extra(kv, tmp_path):
    """A record from a build before this field existed: still unchanged."""
    o, n = _pair(tmp_path, name="old")
    kv.write_run_record(n, agent="codex")

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "sent to:" not in r.stdout, r.stdout


def test_the_specialist_whose_span_covered_the_line_is_named(kv, tmp_path):
    """One job, one specialist, its span covers the lost line: named."""
    o, n = _pair(tmp_path, name="one")
    kv.write_run_record(
        n, agent="codex",
        job_spans=[{"specialist": "noise", "lo": 1, "hi": 7,
                    "unit": "chunk 1 · Retries"}])

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "sent to: noise (chunk 1 · Retries)" in r.stdout, r.stdout


def test_a_span_that_does_not_cover_the_line_is_not_named(kv, tmp_path):
    """A job elsewhere in the file must not be credited with this line."""
    o, n = _pair(tmp_path, name="elsewhere")
    kv.write_run_record(
        n, agent="codex",
        job_spans=[{"specialist": "prose", "lo": 20, "hi": 30,
                    "unit": "chunk 9 · Somewhere else"}])

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "sent to:" not in r.stdout, r.stdout


def test_two_specialists_sharing_the_span_are_both_named(kv, tmp_path):
    """The shape: two replies can jointly eat one rule, neither alone."""
    o, n = _pair(tmp_path, name="two")
    kv.write_run_record(
        n, agent="codex",
        job_spans=[
            {"specialist": "noise", "lo": 1, "hi": 7,
             "unit": "chunk 1 · Retries"},
            {"specialist": "prose", "lo": 1, "hi": 7,
             "unit": "chunk 1 · Retries"},
        ])

    r = run_tool("verify", o, n)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout
    assert "sent to: noise (chunk 1 · Retries), prose (chunk 1 · Retries)" \
        in r.stdout, r.stdout
