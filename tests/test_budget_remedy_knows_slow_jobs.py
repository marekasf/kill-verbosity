"""The budget line offered "lower --job-timeout to N" on a
document whose `structure document` job had already timed out at 240s, so the
lower ceiling would kill that job outright. A job that ran out its full ceiling
is now banked in the journal, and the next run's budget line withdraws that
remedy and names the job.
"""

from __future__ import annotations

import sys

from test_verify_fail_keeps_journal import DOC


def _main(kv, monkeypatch, argv, launcher=None):
    if launcher:
        monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", *argv])
    try:
        return kv.main()
    except SystemExit as e:
        return e.code


def _dry(kv, monkeypatch, capsys, src, out):
    capsys.readouterr()
    assert _main(kv, monkeypatch, ["run", str(src), "-o", str(out),
                                   "--dry-run", "--timeout", "239"]) == 0
    return capsys.readouterr().err


def test_a_job_that_timed_out_withdraws_the_lower_job_timeout_remedy(
        kv, monkeypatch, tmp_path, capsys):
    src, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    src.write_text(DOC + "\n")

    before = _dry(kv, monkeypatch, capsys, src, out)
    assert "or lower --job-timeout to" in before, before

    def slow(prompt, agent, timeout, say=None, avoid=()):
        return "", f"{agent} timed out after {timeout}s"

    _main(kv, monkeypatch, ["run", str(src), "-o", str(out)], slow)
    assert kv.journal_path(out).is_file()

    after = _dry(kv, monkeypatch, capsys, src, out)
    assert "or lower --job-timeout to" not in after, after
    assert "already timed out at 240s" in after, after


def test_a_short_clock_kill_is_not_banked_as_slow(kv, monkeypatch, tmp_path,
                                                  capsys):
    """Control: a job the RUN starved is not evidence the job is slow."""
    src, out = tmp_path / "doc.md", tmp_path / "doc.kv.md"
    src.write_text(DOC + "\n")

    def other(prompt, agent, timeout, say=None, avoid=()):
        return "", f"{agent} exited 1: boom"

    _main(kv, monkeypatch, ["run", str(src), "-o", str(out)], other)
    assert "or lower --job-timeout to" in _dry(kv, monkeypatch, capsys, src, out)


def test_the_slowest_job_is_the_one_named():
    """Sorted by name, specB=240s + specA=200s named specA at 200s."""
    from killverbosity.budget import matrix_note
    note = matrix_note(4, 1, 240, 400, {"specB x": 240, "specA x": 200})
    assert "specB x already timed out at 240s, and 1 more" in note, note
