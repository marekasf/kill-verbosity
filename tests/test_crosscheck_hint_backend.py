"""The final report's crosscheck hint names only a reviewer that is installed.

When neither candidate reviewer is installed, the printed command carries no
`KV_BACKEND=` at all, rather than a name the host cannot run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
from pathlib import Path

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


def _quiet(_prompt, _agent, _n):
    return json.dumps({"edits": [], "notes": ["nothing to do"]}), None


def _runfix(kv, avail, agent="codex"):
    d = Path(tempfile.mkdtemp())
    src = d / "doc.md"
    src.write_text(_DOC, encoding="utf-8")

    def _stub(prompt, agent, timeout):
        return _quiet(prompt, agent, timeout)

    ns = argparse.Namespace(
        file=str(src), out=None, agent=agent, chat=False, dry_run=False,
        job_timeout=30, no_budget=True, only=None, timeout=60,
        full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = kv.cmd_run(ns, launcher=_stub)
    return rc, out.getvalue(), err.getvalue()


def test_no_candidate_installed_prints_no_name(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": False, "codex": False})
    rc, out, err = _runfix(kv, None, agent="codex")
    assert "Nothing here checked this file for meaning" in out, (rc, out, err)
    assert "KV_BACKEND=" not in out, (
        f"no candidate installed and a backend name was still printed: "
        f"{out!r}")
    assert "kill-verbosity crosscheck" in out, out


def test_alt_confirmed_up_is_still_named(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": False, "codex": True})
    rc, out, err = _runfix(kv, None, agent="claude")
    assert "KV_BACKEND=codex " in out, (rc, out, err)
