"""A run whose jobs fell to another agent counts why the requested agent failed."""

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

_SUBST_NOTE = ("codex failed, answered by agy instead — "
               "codex exited 1: not authenticated, run codex login")


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


def test_every_job_substituted_counts_each_rungs_cause_and_says_all(
        kv, monkeypatch, tmp_path, capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        if say:
            say(_SUBST_NOTE)
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher, "--any-agent")

    m = re.search(r"(\d+) of (\d+) jobs? answered by a substituted backend, "
                  r"not codex", out)
    assert m, f"the existing substitution count line is gone -- out:\n{out}"
    n, total = m.group(1), m.group(2)
    assert n == total, (n, total)

    assert re.search(rf"\bcodex {n} fail \(auth\)", out), (
        f"no per-rung auth cause count for codex -- out:\n{out}")
    assert f"ALL {total} JOBS SUBSTITUTED" in out, (
        f"no loud banner for a run substituted end to end -- out:\n{out}")


def test_a_partly_substituted_run_counts_causes_but_stays_quiet(
        kv, monkeypatch, tmp_path, capsys):
    calls = []

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        calls.append(prompt)
        if len(calls) == 1 and say:
            say(_SUBST_NOTE)
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    m = re.search(r"(\d+) of (\d+) jobs? answered by a substituted backend, "
                  r"not codex", out)
    assert m, f"the existing substitution count line is gone -- out:\n{out}"
    n, total = m.group(1), m.group(2)
    assert n == "1" and total != "1", (n, total)

    assert re.search(r"\bcodex 1 fail \(auth\)", out), (
        f"no per-rung auth cause count for codex -- out:\n{out}")
    assert "JOBS SUBSTITUTED" not in out, (
        f"a partly-substituted run printed the all-substituted banner -- "
        f"out:\n{out}")


def test_an_unsubstituted_run_prints_neither_causes_nor_the_banner(
        kv, monkeypatch, tmp_path, capsys):
    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [], "notes": []}), None

    out, err = _run(kv, monkeypatch, tmp_path, capsys, launcher)

    assert "substituted backend" not in out, out
    assert "fail (" not in out, out
    assert "JOBS SUBSTITUTED" not in out, out
