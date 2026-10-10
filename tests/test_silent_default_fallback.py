"""A run with no --agent and no KV_AGENT uses whichever agent is installed and
falls back silently: an absent or failing candidate prints no error line.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

DOC = "\n".join(
    ["# Notes", ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 6)])

ANSWER = json.dumps({"edits": [], "notes": []})
NOISE = re.compile(r"failed|fallback|falling to|substituted|not installed|"
                   r"exited \d", re.I)


def _run(kv, monkeypatch, tmp_path, capsys, installed, fake):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    monkeypatch.delenv("KV_AGENT", raising=False)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", installed)
    monkeypatch.setattr(kv.shutil, "which", lambda n, *a, **k: n)
    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    return capsys.readouterr()


def test_only_delegate_installed_is_used_with_no_error_lines(
        kv, monkeypatch, tmp_path, capsys):
    spawned = []

    def fake(cmd, **kw):
        spawned.append((list(cmd), kw.get("input")))
        return subprocess.CompletedProcess(cmd, 0, ANSWER, "")

    said = _run(kv, monkeypatch, tmp_path, capsys, {"delegate": True}, fake)

    assert spawned, said.err
    for cmd, stdin in spawned:
        assert cmd[:6] == ["delegate", "--mode", "raw", "--timeout",
                           cmd[4], "--prompt-file"] and cmd[-1] == "-", cmd
        assert "--strict" not in cmd, cmd
        assert stdin and "worker" in stdin, "the prompt did not go on stdin"
    assert not NOISE.search(said.err), said.err


def test_a_failing_first_agent_falls_back_silently(
        kv, monkeypatch, tmp_path, capsys):
    spawned = []

    def fake(cmd, **kw):
        spawned.append(cmd[0])
        if cmd[0] == "claude":
            return subprocess.CompletedProcess(cmd, 1, "", "not logged in\n")
        return subprocess.CompletedProcess(cmd, 0, ANSWER, "")

    said = _run(kv, monkeypatch, tmp_path, capsys,
                {"claude": True, "delegate": True}, fake)

    assert "claude" in spawned and "delegate" in spawned, spawned
    assert not NOISE.search(said.err), said.err
    assert "substituted backend" not in said.out, said.out
