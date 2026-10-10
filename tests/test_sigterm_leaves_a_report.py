"""A `timeout 1800` wrapper
around a `run` whose own budget was 3600s killed it at span 3 of 34, and it
left no report at all -- only a partial log. Verified: no SIGTERM handler in
`_legacy.py`, so the default disposition ends the process on the spot and
every answer the journal had already banked (`one()` writes it as each job
lands, well before the merge/report code runs) sits there with nothing left
running to read it back.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="SIGTERM delivery semantics differ on Windows; the bug report "
           "and the `timeout(1)` wrapper it names are both POSIX.")

DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])


def _run(kv, monkeypatch, tmp_path, capsys):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    out = tmp_path / "out.md"

    monkeypatch.setattr(kv, "JOBS", 1)
    calls = []

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        calls.append(prompt)
        if len(calls) == 1:
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.3)
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    try:
        rc = kv.main()
    except SystemExit as e:
        rc = e.code
    out_text = capsys.readouterr()
    return rc, out_text.out, out_text.err, len(calls)


def test_sigterm_mid_dispatch_still_prints_a_report_and_exits_143(
        kv, monkeypatch, tmp_path, capsys):
    rc, out, err, n_calls = _run(kv, monkeypatch, tmp_path, capsys)

    assert rc == 143, (rc, out, err)
    assert "exit 143:" in out, out
    assert "never edited" in out or "is incomplete" in out, out
    assert n_calls == 1, (
        f"the run kept dispatching after SIGTERM -- {n_calls} jobs were "
        f"asked, not 1")
    assert "SIGTERM" in err, err


def test_an_ordinary_run_is_unaffected_by_the_sigterm_plumbing(
        kv, monkeypatch, tmp_path, capsys):
    """Control: installing and restoring the handler must not change an
    ordinary run that is never signalled at all."""
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    out = tmp_path / "out.md"

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    try:
        rc = kv.main()
    except SystemExit as e:
        rc = e.code
    said = capsys.readouterr()

    assert rc != 143, (rc, said.out, said.err)
    assert "exit 143:" not in said.out, said.out
    assert "SIGTERM" not in said.err, said.err
