"""`run` three times on an 8545-word worklog
copy, 34 spans at about 200 s each, removed 3.3%, 0.6% and 0.3% of the words,
and all three FAILED verify. It would not have started at that yield, and the
real cost was reading a 133-line report for nothing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re

from conftest import run_tool

FRAME = "It is worth noting that the nightly job finished."

FILLER = "\n\n".join(
    " ".join(f"{w}{i}" for w in ("alpha", "bravo", "charlie", "delta",
                                  "echo", "foxtrot", "golf", "hotel")) + "."
    for i in range(60))

LOW = f"# Log\n\n## Entries\n\n{FILLER}\n\n{FRAME}\n"
HIGH = "# Log\n\n## Entries\n\n" + "\n\n".join(
    f"It is worth noting that host{i} finished." for i in range(12)) + "\n"


def _yield_line(out):
    return next((l for l in out.splitlines() if l.startswith("expected yield:")), "")


def _numbers(line):
    m = re.search(r"at most (\d+) of (\d+) words \((\d+\.\d)%\)", line)
    assert m, line
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


def _dry_run(kv, monkeypatch, path):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    ns = argparse.Namespace(
        file=str(path), out=None, agent="codex", chat=False, dry_run=True,
        job_timeout=30, no_budget=True, only=None, timeout=60,
        full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = kv.cmd_run(ns, launcher=lambda *a, **k: (None, "unused"))
    return rc, out.getvalue(), err.getvalue()


def test_low_yield_warns_in_plan_and_dry_run(kv, monkeypatch, tmp_path):
    p = tmp_path / "log.md"
    p.write_text(LOW)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    line = _yield_line(r.stdout)
    assert line, r.stdout
    assert "UPPER BOUND" in line and "not a prediction" in line, line
    assert "unlikely to land much" in line, line
    at, of, pct = _numbers(line)
    assert pct < 5.0 and at > 0, line

    rc, out, err = _dry_run(kv, monkeypatch, p)
    assert rc == 0, (rc, out, err)
    assert _yield_line(out) == line, (out, line)
    lines = out.splitlines()
    assert lines.index(line) < next(i for i, l in enumerate(lines)
                                    if l.lstrip().startswith("prose ")), out


def test_high_yield_does_not_warn(kv, monkeypatch, tmp_path):
    p = tmp_path / "log.md"
    p.write_text(HIGH)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    line = _yield_line(r.stdout)
    assert line, r.stdout
    assert "unlikely to land much" not in line, line
    assert _numbers(line)[2] >= 5.0, line

    rc, out, _err = _dry_run(kv, monkeypatch, p)
    assert rc == 0
    assert _yield_line(out) == line, out


def test_the_number_is_at_least_the_words_on_the_flagged_lines(kv, tmp_path):
    p = tmp_path / "log.md"
    p.write_text(LOW)
    at, of, _pct = _numbers(_yield_line(run_tool("plan", p).stdout))
    assert at >= len(FRAME.split()), (at, FRAME)
    assert of == kv.word_count(LOW), (of, kv.word_count(LOW))


def test_a_run_that_deletes_every_flagged_line_removes_no_more_than_the_bound(
        kv, monkeypatch, tmp_path):
    """The bound held against the real merge: a canned specialist makes the
    largest fix a shape asks for -- the whole flagged line, gone -- and the
    words that actually left the file are compared with the printed number."""
    from conftest import run_canned

    doc = HIGH + "\n" + FILLER + "\n"
    p = tmp_path / "log.md"
    p.write_text(doc)
    at, _of, _pct = _numbers(_yield_line(run_tool("plan", p).stdout))
    src = doc.split("\n")

    def reply(who, lo, hi):
        if hi is None:
            return []
        return [{"op": "replace", "line": n, "old": src[n - 1], "new": ""}
                for n in range(lo, hi + 1)
                if src[n - 1].startswith("It is worth noting")]

    out = tmp_path / "log.kv.md"
    run_canned(kv, monkeypatch, p, out, reply)
    removed = kv.word_count(doc) - kv.word_count(out.read_text())
    assert removed > 0, "no edit landed, so this compares the bound with nothing"
    assert removed <= at, (removed, at)
