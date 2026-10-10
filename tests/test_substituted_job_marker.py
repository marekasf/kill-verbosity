"""`run --agent codex`: every job was answered by another agent, and every job
line in the listing still printed the ok mark, so the substitution was real
but invisible.
"""

from __future__ import annotations

import json
import re
import sys

DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])


def _run(kv, monkeypatch, tmp_path, capsys, launcher, *extra_argv):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src),
                         "--agent", "codex", "-o", str(tmp_path / "out.md"),
                         *extra_argv])
    try:
        kv.main()
    except SystemExit:
        pass
    said = capsys.readouterr()
    return said.out, said.err


def test_a_substituted_success_is_not_marked_ok(kv, monkeypatch, tmp_path,
                                                capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        if say:
            say("codex failed, answered by claude instead — usage limit reached")
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher, "--any-agent")

    assert not re.search(r"\[\s*\d+/\s*\d+\]\s+·", err), (
        f"a substituted job's line still prints the ok mark -- err:\n{err}")
    assert re.search(r"\[\s*\d+/\s*\d+\]\s+~", err), (
        f"no job line carries the distinct substituted mark `~` -- err:\n{err}")
    assert re.search(r"\bjobs? answered by a substituted backend, not codex",
                     out), (
        f"the run summary never counts the substituted jobs -- out:\n{out}")


def test_an_unsubstituted_success_still_reads_as_ok(kv, monkeypatch, tmp_path,
                                                     capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    assert re.search(r"\[\s*\d+/\s*\d+\]\s+·", err), (
        f"an ordinary success lost its ok mark -- err:\n{err}")
    assert not re.search(r"\[\s*\d+/\s*\d+\]\s+~", err), (
        f"an unsubstituted run was marked as substituted -- err:\n{err}")
    assert "substituted backend" not in out, (
        f"an unsubstituted run printed a substitution count anyway -- "
        f"out:\n{out}")
