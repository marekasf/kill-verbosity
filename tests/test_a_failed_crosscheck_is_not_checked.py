"""A crosscheck whose reviewer exits non-zero is recorded as not checked."""

from __future__ import annotations

import argparse
import json
import subprocess

import pytest

import killverbosity.runrecord as runrecord

pytestmark = pytest.mark.regression

SESSION_LIMIT_STDERR = (
    "claude: starting\n"
    "You've hit your session limit · resets 11:02pm\n")


def _pair(tmp_path, text="# Doc\n\nSome prose here.\n"):
    orig, out = tmp_path / "d.md", tmp_path / "d.kv.md"
    orig.write_text(text)
    out.write_text(text)
    return orig, out


def _ns(orig, out, backend):
    return argparse.Namespace(file=str(out), original=str(orig), context=[],
                              backend=backend, full=False)


def _record(out):
    return json.loads(runrecord.crosscheck_record_path(out).read_text())


def _write_agy_run(kv, out):
    kv.write_run_record(
        out, agent="agy",
        job_spans=[{"lo": 1, "hi": 3, "specialist": "noise", "unit": "chunk",
                    "answered_rung": "agy", "answered_by": "agy",
                    "answered_by_state": "read", "substituted": False}])


def _run_failing_claude(kv, monkeypatch, tmp_path, stdout=""):
    """Only claude is installed, and it fails, so nothing else is tried."""
    orig, out = _pair(tmp_path)
    _write_agy_run(kv, out)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"claude": True})

    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout,
                                           SESSION_LIMIT_STDERR)

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    return orig, out, kv.cmd_crosscheck(_ns(orig, out, "claude"))


def test_the_sidecar_says_unchecked(kv, monkeypatch, tmp_path, capsys):
    _orig, out, _ = _run_failing_claude(kv, monkeypatch, tmp_path)
    capsys.readouterr()
    rec = _record(out)
    assert rec["checked"] is False, rec
    assert rec["not_checked_reason"], rec


def test_the_reason_names_the_backend_and_its_cause(
        kv, monkeypatch, tmp_path, capsys):
    """A reason a later reader can act on, not a bare false."""
    _orig, out, _ = _run_failing_claude(kv, monkeypatch, tmp_path)
    capsys.readouterr()
    reason = _record(out)["not_checked_reason"]
    assert "claude" in reason, reason
    assert "exited 1" in reason, reason
    assert "session limit" in reason, reason


def test_a_failure_that_produced_text_is_still_unchecked(
        kv, monkeypatch, tmp_path, capsys):
    """Text on stdout from a process that exited non-zero is not a review."""
    _orig, out, _ = _run_failing_claude(
        kv, monkeypatch, tmp_path,
        stdout="- kind: lost_fact\n  the release-share number is gone\n")
    capsys.readouterr()
    assert _record(out)["checked"] is False, _record(out)


def test_an_unmade_family_comparison_is_null_not_false(
        kv, monkeypatch, tmp_path, capsys):
    """There is no family to compare when nobody answers, so `false` there is
    a default that reads like a finding."""
    _orig, out, _ = _run_failing_claude(kv, monkeypatch, tmp_path)
    capsys.readouterr()
    assert _record(out)["same_family"] is None, _record(out)


def test_the_exit_code_is_not_checked(kv, monkeypatch, tmp_path, capsys):
    """A reviewer that fails judged nothing: exit 5, never 1 ("broken")."""
    _orig, _out, (rc, _kinds) = _run_failing_claude(kv, monkeypatch, tmp_path)
    capsys.readouterr()
    assert rc == kv.CROSSCHECK_NOT_CHECKED, rc


def test_stderr_says_what_was_written_down(kv, monkeypatch, tmp_path, capsys):
    """The terminal has to name it too, not only the sidecar."""
    _run_failing_claude(kv, monkeypatch, tmp_path)
    err = capsys.readouterr().err
    assert "not checked" in err, err


def test_a_backend_that_answers_is_still_checked(kv, monkeypatch, tmp_path,
                                                 capsys):
    """The control: a successful crosscheck still records `checked: true`."""
    orig, out = _pair(tmp_path)
    _write_agy_run(kv, out)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})

    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "no findings.", "")

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    rc, _kinds = kv.cmd_crosscheck(_ns(orig, out, "codex"))
    capsys.readouterr()
    assert rc == 0, rc
    rec = _record(out)
    assert rec["checked"] is True, rec
    assert rec["not_checked_reason"] is None, rec
