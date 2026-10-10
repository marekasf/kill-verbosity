"""A weak wrap margin reaches the notes tally; a launch failure is not retried on the same agent."""

from __future__ import annotations

import json
import sys


DOC = "\n".join(
    ["# Notes", "", "This paragraph wraps across", "two full lines on purpose.",
     ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])


def test_weak_margin_is_counted_in_the_notes_tally_not_only_stderr(
        kv, monkeypatch, tmp_path, capsys):
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src),
                         "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "notes (" in out, (
        "no notes tally printed at all -- nothing reached stdout. stdout "
        f"was:\n{out}")
    assert "no wrap margin found" in out, (
        "the weak-margin caveat never reached the notes tally on stdout -- "
        f"it is still only a stderr print. stdout was:\n{out}")


def test_launch_failure_is_marked_and_not_retried_on_same_backend(
        kv, monkeypatch, tmp_path, capsys):
    def _raise(exc):
        def _run(*a, **k):
            raise exc
        return _run

    monkeypatch.setattr(kv.spawn, "run_tree",
                        _raise(OSError(2, "No such file or directory")))
    _, os_err = kv._call_one("prompt", "claude", 5)
    assert isinstance(os_err, kv._LaunchError), (
        "an OSError from launching a backend must be marked as a launch "
        f"failure, distinct from a timeout: got {os_err!r}")

    monkeypatch.setattr(
        kv.spawn, "run_tree",
        _raise(kv.subprocess.TimeoutExpired(cmd=["claude"], timeout=5)))
    _, timeout_err = kv._call_one("prompt", "claude", 5)
    assert not isinstance(timeout_err, kv._LaunchError), (
        "a timeout is not a launch failure -- it may clear on a retry -- and "
        f"must not be marked as one: got {timeout_err!r}")
    monkeypatch.undo()

    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    calls = []

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        calls.append(tuple(avoid))
        if not avoid:
            return "", kv._LaunchError("could not run claude: "
                                       "[Errno 2] No such file or directory")
        return json.dumps({"edits": [], "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src),
                         "--agent", "claude", "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    retries = [c for c in calls if c]
    assert retries, (
        "EMPTY: the launch failure was never retried, so this case cannot "
        f"see whether the retry excluded the backend -- calls={calls}")
    assert all(c == ("claude",) for c in retries), (
        "a launch failure must not be retried against the SAME backend -- "
        f"at least one retry's `avoid` was not `('claude',)`: {retries!r}, so "
        "`claude` was re-dialled into the one launch that can never succeed "
        "twice")
