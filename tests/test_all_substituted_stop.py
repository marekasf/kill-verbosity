"""A run whose specialists were ALL answered by a fallback agent writes its
output like any other run. A fallback is normal behaviour, not an error.
`--any-agent` is still accepted so old commands parse.
"""

from __future__ import annotations

import json
import sys

FELL = "codex failed, answered by agy instead — usage limit reached"

DOC = "\n".join(
    ["# Notes", ""]
    + [line for i in range(1, 5) for line in (
        f"## Section {i}", "",
        f"It should be noted that the worker, in point of fact, retries job "
        f"{i} and records the outcome in the store for the purposes of a "
        f"later inspection by whichever operator happens to be on call.", "")])


def _launcher(substitute):
    """`substitute(call_index) -> bool` decides whether that call's answer
    is reported as a fallback to another agent."""
    calls = {"n": 0}

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        i = calls["n"]
        calls["n"] += 1
        if say and substitute(i):
            say(FELL)
        return json.dumps({"edits": [], "notes": []}), None

    return launcher


def _run_main(kv, monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    try:
        return kv.main()
    except SystemExit as e:
        return e.code


def _drive(kv, monkeypatch, tmp_path, capsys, extra_argv, substitute):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n", encoding="utf-8")
    out = tmp_path / "out.md"
    monkeypatch.setattr(kv, "call_agent", _launcher(substitute))
    monkeypatch.setattr(kv, "JOBS", 1)
    argv = ["kill-verbosity", "run", str(src), "-o", str(out), *extra_argv]
    rc = _run_main(kv, monkeypatch, argv)
    captured = capsys.readouterr()
    return rc, out, captured


def test_all_substituted_and_explicitly_named_agent_writes(
        kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex"], substitute=lambda i: True)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "an all-substituted run must write its output"
    assert kv.run_record_path(out).exists(), captured.err
    assert "nothing is written" not in captured.err, captured.err
    assert "--any-agent" not in captured.err + captured.out


def test_all_substituted_with_agent_left_at_its_default_writes(
        kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        [], substitute=lambda i: True)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "a defaulted --agent must still write its output"
    assert "SUBSTITUTED" not in captured.out
    assert "failed, answered by" not in captured.err, captured.err


def test_partial_substitution_writes(kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex"], substitute=lambda i: i == 0)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "a partial substitution must still write its output"


def test_any_agent_is_accepted_and_ignored(kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex", "--any-agent"], substitute=lambda i: True)

    assert rc != 6, (rc, captured.err)
    assert out.exists()
    assert "ANY-AGENT" not in captured.out, captured.out
