"""`.kvcross` records what the reviewer found, so a clean read and an unread
answer are told apart on disk.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import pytest

import killverbosity.runrecord as runrecord
from conftest import run_tool

pytestmark = pytest.mark.regression

CODEX_WRITER = "codex"


def _pair(tmp_path, name="d", text="# Doc\n\nSome prose here.\n"):
    orig, out = tmp_path / f"{name}.md", tmp_path / f"{name}.kv.md"
    orig.write_text(text)
    out.write_text(text)
    return orig, out


def _ns(orig, out, backend):
    return argparse.Namespace(file=str(out), original=str(orig), context=[],
                              backend=backend, full=False)


def _record(out):
    return json.loads(runrecord.crosscheck_record_path(out).read_text())


def _write_codex_run(kv, out):
    """A run record naming codex as the writer, so `agy` (google family)
    reviewing it is a real, determinate mismatch and the review proceeds."""
    kv.write_run_record(
        out, agent="codex",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "codex", "answered_by": CODEX_WRITER,
                    "answered_by_state": "read", "substituted": False}])


def _dispatch(kv, monkeypatch, stdout):
    """agy answers in stream-json; the answer is the result event's text."""
    event = json.dumps({"event": "result",
                        "result": {"status": "SUCCESS", "response": stdout}})

    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, event + "\n", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": True})


def test_a_real_finding_is_recorded_as_a_non_empty_list(
        kv, monkeypatch, tmp_path, capsys):
    """State one: the reviewer found something. `findings` must carry it,
    not just the exit code the CLI wrapper derives from it."""
    orig, out = _pair(tmp_path)
    _write_codex_run(kv, out)
    _dispatch(kv, monkeypatch,
             "- kind: lost_fact\n  the release-share number is gone\n")

    rc, kinds = kv.cmd_crosscheck(_ns(orig, out, "agy"))
    capsys.readouterr()

    assert rc == 0, rc
    assert kinds["lost_fact"] == 1, kinds
    rec = _record(out)
    assert rec["checked"] is True, rec
    assert rec["findings"] == ["lost_fact"], rec
    assert runrecord.crosscheck_findings(out) == ["lost_fact"]


def test_a_clean_read_is_recorded_as_an_empty_list_not_absence(
        kv, monkeypatch, tmp_path, capsys):
    """State two: the reviewer read the file and reported nothing. This is
    the case that matters -- `checked: true, same_family: false` --
    and it must be `findings: []` on disk, present and empty, not missing."""
    orig, out = _pair(tmp_path)
    _write_codex_run(kv, out)
    _dispatch(kv, monkeypatch, "no findings -- the edit is faithful.\n")

    rc, kinds = kv.cmd_crosscheck(_ns(orig, out, "agy"))
    capsys.readouterr()

    assert rc == 0, rc
    assert not sum(kinds.values()), kinds
    rec = _record(out)
    assert rec["checked"] is True, rec
    assert rec["same_family"] is False, rec
    assert "findings" in rec, rec
    assert rec["findings"] == [], rec
    assert runrecord.crosscheck_findings(out) == []


def test_an_older_record_reads_as_could_not_tell_not_clean(tmp_path):
    """State three: a `.kvcross` written by a build before `findings`
    existed. `checked: true` with no `findings` key at all -- exactly what
    every `write_crosscheck_record` call site wrote before this fix, and
    still what any caller that omits the new keyword argument writes today.
    Must NOT read as `[]`."""
    _orig, out = _pair(tmp_path)
    runrecord.write_crosscheck_record(
        out, backend="codex", answered_by="agy",
        answered_by_state="read", wrote=["codex"], same_family=False,
        same_family_reason=None, checked=True, not_checked_reason=None,
        dispatched=["agy"])

    assert runrecord.crosscheck_state(out) == "ok"
    assert "findings" not in _record(out), _record(out)
    assert runrecord.crosscheck_findings(out) is None


def test_accept_warns_on_an_older_record_but_does_not_refuse(tmp_path):
    """The consumer-facing half: `accept` must tell a reader it cannot say
    whether an old `.kvcross` was clean, and must not turn that into a
    refusal -- a warning, never a refusal."""
    src = tmp_path / "hand.md"
    out = tmp_path / "hand.kv.md"
    text = ("# T\n\nThe room was warm and the window faced the garden, and "
            "the afternoon went by slowly.\n")
    src.write_text(text)
    out.write_text("# T\n\nThe room was warm.\n")
    runrecord.write_run_record(out)
    runrecord.write_crosscheck_record(
        out, backend="codex", answered_by="agy", wrote=["codex"],
        same_family=False, same_family_reason=None, checked=True,
        not_checked_reason=None, dispatched=["agy"])

    r = run_tool("accept", src, out)

    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert "cannot tell you clean from unread" in r.stdout, r.stdout
    assert "Nothing here has crosschecked" not in r.stdout, r.stdout


def test_accept_stays_quiet_on_a_fresh_empty_findings_record(tmp_path):
    """Negative control for the warning above: a genuinely fresh, clean
    record (`findings: []` present) must not trip the "could not tell"
    warning -- it is exactly the state the warning exists to distinguish
    FROM."""
    src = tmp_path / "hand2.md"
    out = tmp_path / "hand2.kv.md"
    text = ("# T\n\nThe room was warm and the window faced the garden, and "
            "the afternoon went by slowly.\n")
    src.write_text(text)
    out.write_text("# T\n\nThe room was warm.\n")
    runrecord.write_run_record(out)
    runrecord.write_crosscheck_record(
        out, backend="codex", answered_by="agy", wrote=["codex"],
        same_family=False, same_family_reason=None, checked=True,
        not_checked_reason=None, dispatched=["agy"], findings=[])

    r = run_tool("accept", src, out)

    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert "cannot tell you clean from unread" not in r.stdout, r.stdout
    assert "Nothing here has crosschecked" not in r.stdout, r.stdout


def test_cli_exit_is_3_for_a_meaning_finding_and_0_for_a_style_one(
        kv, monkeypatch, tmp_path, capsys):
    """The command line exits 3 when the reviewer reports a lost fact or a
    reversed/weakened rule, and 0 when it reports only a non-meaning kind."""
    orig, out = _pair(tmp_path)
    _write_codex_run(kv, out)

    _dispatch(kv, monkeypatch, "- kind: lost_fact\n  the number is gone\n")
    assert kv.cmd_crosscheck_cli(_ns(orig, out, "agy")) == 3
    assert "exit 3:" in capsys.readouterr().out

    _dispatch(kv, monkeypatch, "- kind: verbose\n  still wordy\n")
    assert kv.cmd_crosscheck_cli(_ns(orig, out, "agy")) == 0
    capsys.readouterr()
