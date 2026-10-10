"""`crosscheck` hands the prompt to every agent on stdin, never in argv.

Windows caps a whole command line at about 32767 characters, so a long prompt
as a positional argument raises `[WinError 206] The filename or extension is
too long`.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import pytest

MARKER = "MARKER-" + "x" * 400


def _run_crosscheck(kv, monkeypatch, tmp_path, backend):
    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nSome verbose prose here.\n")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake_run)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {backend: True})
    monkeypatch.setattr(kv, "_cli_argv", lambda name: ([name], None))
    monkeypatch.setattr(kv, "crosscheck_prompt", lambda *a, **k: MARKER)
    monkeypatch.setattr(kv, "run_notes_prompt", lambda *a, **k: "")
    kv.cmd_crosscheck(argparse.Namespace(
        file=str(target), original=None, context=[], dropped=[],
        backend=backend, mode="review", timeout=60))
    return seen


@pytest.mark.parametrize("backend", ["claude", "codex", "agy"])
def test_crosscheck_sends_the_prompt_on_stdin(kv, monkeypatch, tmp_path,
                                              backend):
    seen = _run_crosscheck(kv, monkeypatch, tmp_path, backend)
    assert not any(MARKER in str(a) for a in seen["cmd"]), seen["cmd"]
    sent = seen["kwargs"].get("input") or ""
    if backend == "agy":
        sent = json.loads(sent)["message"]["content"]
    assert MARKER in sent, seen["kwargs"]
