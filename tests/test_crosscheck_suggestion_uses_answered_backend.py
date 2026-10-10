"""The printed crosscheck suggestion excludes the agent that really answered.

A run whose jobs fell through to another agent must not be told to review
itself with an agent from the same vendor as the one that wrote the edits;
`crosscheck`'s own same-family guard would refuse that suggestion.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import tempfile
from pathlib import Path

GOOGLE = "agy"

_DOC = "\n".join([
    "# Retention", "",
    "In order to facilitate the retention of session rows the system "
    "leverages a robust and scalable architecture designed for storage.",
    "", "## Storage", "",
    "Session rows are retained for twelve months in the primary store. It "
    "should be noted that this is a very important consideration here.",
    "",
    "The utilisation of the archival tier enables the organisation to "
    "reduce costs in a manner that is both efficient and effective.",
    "", "## Policy", "",
    "Session rows are retained for twelve months in the primary store. It "
    "should be noted that this is a very important consideration here.",
    "",
    "The gate holds at 85% and the latency budget is 250ms for every "
    "request the service must process during normal operations.", "",
]) + "\n"


def _suggested_backend(out):
    lines = [ln for ln in out.splitlines() if "KV_BACKEND=" in ln]
    assert lines, f"no crosscheck suggestion named a backend: {out[-400:]!r}"
    return lines[0].split("KV_BACKEND=")[1].split()[0]


def _runfix(kv, monkeypatch, agent="codex"):
    """Run `cmd_run --agent {agent}` where every job is answered by GOOGLE,
    a different vendor, and the run's stderr names the substitution.
    """
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": True, "codex": True})
    d = Path(tempfile.mkdtemp())
    src = d / "doc.md"
    src.write_text(_DOC, encoding="utf-8")

    def _stub(prompt, requested_agent, timeout, say=None, answered=None):
        if say:
            say(f"{requested_agent} failed; answered by {GOOGLE} "
                f"(requested {requested_agent} — SUBSTITUTED)")
        if answered:
            answered(requested_agent, GOOGLE, True)
        return json.dumps({"edits": [], "notes": ["nothing to do"]}), None

    ns = argparse.Namespace(
        file=str(src), out=None, agent=agent, chat=False, dry_run=False,
        job_timeout=30, no_budget=True, only=None, timeout=60,
        full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = kv.cmd_run(ns, launcher=_stub)
    return rc, out.getvalue(), err.getvalue(), d


def test_suggestion_excludes_the_backend_that_really_answered(kv, monkeypatch):
    rc, out, err, d = _runfix(kv, monkeypatch, agent="codex")
    try:
        assert "SUBSTITUTED" in err, err
        wrote = kv.answering_backends(kv.read_run_record(d / "doc.kv.md"))
        assert wrote and GOOGLE in wrote, wrote

        got = _suggested_backend(out)
        assert not kv.same_family(got, wrote), (
            f"the suggestion named {got!r}, which the same-family guard "
            f"crosscheck itself enforces would refuse against a run "
            f"actually answered by {wrote!r}")
        assert got == "codex", got
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_qualifying_backend_prints_the_refusal_reason_not_a_command(
        kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": True, "codex": True})
    d = Path(tempfile.mkdtemp())
    src = d / "doc.md"
    src.write_text(_DOC, encoding="utf-8")
    calls = {"n": 0}

    def _stub(prompt, requested_agent, timeout, say=None, answered=None):
        calls["n"] += 1
        via = GOOGLE if calls["n"] % 2 else "codex"
        if answered:
            answered(requested_agent, via, True)
        return json.dumps({"edits": [], "notes": ["nothing to do"]}), None

    ns = argparse.Namespace(
        file=str(src), out=None, agent="claude", chat=False,
        dry_run=False, job_timeout=30, no_budget=True, only=None,
        timeout=60, full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            kv.cmd_run(ns, launcher=_stub)
        printed = out.getvalue()
        wrote = kv.answering_backends(kv.read_run_record(d / "doc.kv.md"))
        assert GOOGLE in wrote and "codex" in wrote, wrote
        assert calls["n"] >= 2, "need both families to actually answer a job"

        assert "KV_BACKEND=" not in printed, printed[-400:]
        assert "read it for sense:" in printed, printed[-400:]
        assert "file-capable backend" in printed, printed[-400:]
    finally:
        shutil.rmtree(d, ignore_errors=True)
