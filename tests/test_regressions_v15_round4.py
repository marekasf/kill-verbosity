"""Regression cases from a review round: protected speech, agent errors, spelled numbers."""

import json
import sys

import pytest

pytestmark = pytest.mark.regression



TURNS = "\n\n".join(
    f"## 00:{i // 60:02d}:{i % 60:02d} Speaker {i % 4}\n\n"
    f"So you know, the thing is that we, sort of, need to look at the pipeline "
    f"again because it— it keeps failing on the second step and nobody has "
    f"actually gone and checked what the retry count is set to right now."
    for i in range(40)
)
TRANSCRIPT = f"# Weekly sync transcript\n\n{TURNS}\n"


def _run(kv, monkeypatch, tmp_path, text, name="doc.md", reply=None):
    src = tmp_path / name
    src.write_text(text)
    monkeypatch.setattr(
        kv, "call_agent",
        lambda *a: (json.dumps(reply or {"edits": [], "notes": []}), None))
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass


def test_a_file_of_protected_speech_is_not_charged_a_length_target(
        kv, monkeypatch, tmp_path, capsys):
    """E1. Every word is quotation, so no reworder ran and none could."""
    _run(kv, monkeypatch, tmp_path, TRANSCRIPT)
    out = capsys.readouterr().out

    assert "over target" not in out, (
        "a target was charged on a file where every word is protected speech "
        "and no reworder was dispatched:\n"
        + next(x for x in out.splitlines() if "over target" in x))


def test_a_file_of_protected_speech_says_nothing_was_sent(
        kv, monkeypatch, tmp_path, capsys):
    """E1, the other half. The line that explains it is behind `if _pw`."""
    _run(kv, monkeypatch, tmp_path, TRANSCRIPT)
    out = capsys.readouterr().out

    assert "not sent to anyone" in out, (
        "no reworder was dispatched and the report never said so:\n" + out)



def test_a_backend_that_fails_on_stdout_prints_its_reason(kv, monkeypatch):
    """F1. The Claude CLI writes its errors to stdout under `-p`."""
    class Done:
        returncode = 1
        stdout = "Credit balance is too low to run this request."
        stderr = ""

    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {})
    monkeypatch.setattr(kv.spawn, "run_tree", lambda *a, **k: Done())
    _out, err = kv.call_agent("prompt", "claude", 30)

    assert err, "a nonzero exit must be an error"
    assert "Credit balance is too low" in err, (
        f"the reason was on stdout and was thrown away: {err!r}")


def test_a_backend_error_still_prefers_stderr(kv, monkeypatch):
    """The fallback must not take stdout when stderr said something."""
    class Done:
        returncode = 1
        stdout = "partial answer text"
        stderr = "model not found: gpt-9"

    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {})
    monkeypatch.setattr(kv.spawn, "run_tree", lambda *a, **k: Done())
    _out, err = kv.call_agent("prompt", "codex", 30)

    assert "model not found: gpt-9" in err, err
    assert "partial answer" not in err, (
        f"stdout was used while stderr had the reason: {err!r}")



def test_a_spelled_number_rewritten_as_a_digit_is_not_invented(kv):
    """G1. `SPELLED_OUT` is applied by the loss check and not by this one."""
    whole = ("The hand-written ideal edits come in at 0.80 times it, under it "
             "on eleven of the sixteen.")
    old = "under it on eleven of the sixteen"
    new = "under it on 11 of 16"

    added = kv.tokens_added(old, new, (), kv.token_lines([whole]), whole)

    assert not added, (
        f"a spelled number and its digit are one fact, and the gate called "
        f"{added} invented")
