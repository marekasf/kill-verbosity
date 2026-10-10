"""`--agent codex` was quota-limited, all 5 jobs fell through to agy, and `run`
announced the substitution three times (per-job, the mid-report count, the
"ALL N JOBS SUBSTITUTED" banner) and then wrote the `.kv.md` anyway. The exit
code was 1 for an unrelated reason (QUOTATIONS LOST), which hid the
substitution further: a caller acting on the exit code alone got a document
edited by a vendor it did not ask for, with a record saying it had been told.
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
    src.write_text(DOC + "\n")
    out = tmp_path / "out.md"
    monkeypatch.setattr(kv, "call_agent", _launcher(substitute))
    monkeypatch.setattr(kv, "JOBS", 1)
    argv = ["kill-verbosity", "run", str(src), "-o", str(out), *extra_argv]
    rc = _run_main(kv, monkeypatch, argv)
    captured = capsys.readouterr()
    return rc, out, captured


def test_all_substituted_and_explicitly_named_agent_stops(
        kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex"], substitute=lambda i: True)

    assert rc == 6, (rc, captured.err)
    assert not out.exists(), "exit 6 must not write the output file"
    assert not kv.run_record_path(out).exists(), \
        "exit 6 must not write a run record for a document it never wrote"
    assert "ALL" in captured.err and "codex" in captured.err, captured.err
    assert "--any-agent" in captured.err, captured.err
    assert kv.journal_path(out).exists(), \
        "the substituted answers must still be banked for a rerun to reuse"


def test_all_substituted_with_agent_left_at_its_default_does_not_stop(
        kv, monkeypatch, tmp_path, capsys):
    """Negative control. Without `--agent` on the command line at all,
    `agent_explicit` must read false and this run must behave exactly as it
    did before -- proceed and write the output. This is the test
    that must fail if the explicit/default distinction is ever dropped and
    every all-substituted run is stopped regardless of how --agent arrived."""
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        [], substitute=lambda i: True)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "a defaulted --agent must still write its output"
    assert "SUBSTITUTED" not in captured.out, \
        "an agent nobody named falls back silently -- no substitution banner"
    assert "failed, answered by" not in captured.err, captured.err


def test_partial_substitution_does_not_stop(kv, monkeypatch, tmp_path, capsys):
    """Some, not all, jobs substituted -- a real run measured 5 of 5, and this
    must stay a warning rather than widen to "any job substituted"."""
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex"], substitute=lambda i: i == 0)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "a partial substitution must still write its output"


def test_any_agent_proceeds_and_says_so(kv, monkeypatch, tmp_path, capsys):
    rc, out, captured = _drive(
        kv, monkeypatch, tmp_path, capsys,
        ["--agent", "codex", "--any-agent"], substitute=lambda i: True)

    assert rc != 6, (rc, captured.err)
    assert out.exists(), "--any-agent must let the run proceed to write"
    assert "--any-agent" in captured.out, captured.out
    assert "ANY-AGENT" in captured.out, \
        "the override must be stamped on its own line"
