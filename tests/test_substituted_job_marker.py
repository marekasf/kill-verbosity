"""A backend fallback is normal behaviour and kill-verbosity prints nothing
about it. A substituted job that answered prints exactly like an ok job, and
`.kvrun` still records the substitution.
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
    src.write_text(DOC + "\n", encoding="utf-8")
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


def test_a_substituted_success_prints_like_an_ok_job(kv, monkeypatch,
                                                     tmp_path, capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        if say:
            say("codex failed, answered by claude instead — usage limit reached")
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    assert re.search(r"\[\s*\d+/\s*\d+\]\s+·", err), err
    assert not re.search(r"\[\s*\d+/\s*\d+\]\s+~", err), err
    for text in (out, err):
        assert "SUBSTITUTED" not in text, text
        assert "substituted backend" not in text, text
    rec = json.loads(kv.run_record_path(tmp_path / "out.md").read_text(encoding="utf-8"))
    assert rec["substituted_jobs"] >= 1, rec


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
