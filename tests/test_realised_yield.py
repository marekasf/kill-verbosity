"""The expected-yield line is an UPPER BOUND and
decides nothing alone. On a peer's 8545-word file it printed 40.5%, while
that file's last three real runs removed 3.3%, 0.6% and 0.3% -- three
133-line reports read for nothing, each one starting from a bound the real
runs never came close to.
"""

from __future__ import annotations

import re

from conftest import run_canned, run_tool

FRAME = "It is worth noting that the nightly job finished."

FILLER = "\n\n".join(
    " ".join(f"{w}{i}" for w in ("alpha", "bravo", "charlie", "delta",
                                  "echo", "foxtrot", "golf", "hotel")) + "."
    for i in range(60))

DOC = f"# Log\n\n## Entries\n\n{FILLER}\n\n{FRAME}\n"


def _lines(out):
    exp = next((l for l in out.splitlines() if l.startswith("expected yield:")), "")
    rea = next((l for l in out.splitlines() if l.startswith("realised yield")), "")
    return exp, rea


def _has_number(rea):
    """True only when `rea` carries the actual percentage/word-count figure,
    not merely the words "actually removed" -- which the stale-record
    sentence also uses, in its explanation of why there is no number."""
    return re.search(r"\d+\.\d% \(\d+ of \d+ words\) actually removed", rea) \
        is not None


def test_no_prior_run_prints_bound_only(tmp_path):
    p = tmp_path / "log.md"
    p.write_text(DOC)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    exp, rea = _lines(r.stdout)
    assert exp, r.stdout
    assert not rea, r.stdout


def test_prior_run_prints_both_numbers(kv, monkeypatch, tmp_path):
    p = tmp_path / "log.md"
    p.write_text(DOC)
    out = p.with_suffix(".kv.md")

    def reply(_who, lo, hi):
        if hi is None:
            return []
        return [{"op": "replace", "line": n, "old": DOC.split("\n")[n - 1],
                 "new": ""}
                for n in range(lo, hi + 1)
                if DOC.split("\n")[n - 1].startswith("It is worth noting")]

    run_canned(kv, monkeypatch, p, out, reply)
    assert out.is_file(), "the canned run did not write the default output"
    before = kv.word_count(DOC)
    after = kv.word_count(out.read_text())
    assert after < before, "the canned run did not remove anything to measure"

    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    exp, rea = _lines(r.stdout)
    assert exp, r.stdout
    assert rea, r.stdout
    assert out.name in rea, rea
    m = re.search(r"(\d+\.\d)% \((\d+) of (\d+) words\) actually removed",
                  rea)
    assert m, rea
    pct, removed, of = float(m.group(1)), int(m.group(2)), int(m.group(3))
    assert of == before, (of, before)
    assert removed == before - after, (removed, before, after)
    assert abs(pct - 100 * removed / before) < 0.05, (pct, removed, before)


def test_run_dry_run_prints_the_same_realised_line(kv, monkeypatch, tmp_path):
    """`run --dry-run` reads the same sidecar `plan` does, off `run`'s own
    default output name, even when THIS run is pointed elsewhere with -o."""
    import argparse
    import contextlib
    import io

    p = tmp_path / "log.md"
    p.write_text(DOC)
    out = p.with_suffix(".kv.md")

    def reply(_who, lo, hi):
        if hi is None:
            return []
        return [{"op": "replace", "line": n, "old": DOC.split("\n")[n - 1],
                 "new": ""}
                for n in range(lo, hi + 1)
                if DOC.split("\n")[n - 1].startswith("It is worth noting")]

    run_canned(kv, monkeypatch, p, out, reply)
    plan_rea = _lines(run_tool("plan", p).stdout)[1]
    assert plan_rea

    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    ns = argparse.Namespace(
        file=str(p), out=str(tmp_path / "elsewhere.kv.md"), agent="codex",
        chat=False, dry_run=True, job_timeout=30, no_budget=True, only=None,
        timeout=60, full=False, profile=None)
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = kv.cmd_run(ns, launcher=lambda *a, **k: (None, "unused"))
    assert rc == 0, (rc, stdout.getvalue(), stderr.getvalue())
    assert _lines(stdout.getvalue())[1] == plan_rea, stdout.getvalue()


def test_stale_input_is_flagged_not_presented_as_current(kv, monkeypatch, tmp_path):
    p = tmp_path / "log.md"
    p.write_text(DOC)
    out = p.with_suffix(".kv.md")

    def reply(_who, lo, hi):
        if hi is None:
            return []
        return [{"op": "replace", "line": n, "old": DOC.split("\n")[n - 1],
                 "new": ""}
                for n in range(lo, hi + 1)
                if DOC.split("\n")[n - 1].startswith("It is worth noting")]

    run_canned(kv, monkeypatch, p, out, reply)
    p.write_text(DOC + "\nOne more paragraph added after the run.\n")

    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    exp, rea = _lines(r.stdout)
    assert exp, r.stdout
    assert rea, "a stale record should be named, not silently dropped"
    assert not _has_number(rea), rea
    assert "changed since" in rea, rea


def test_mtime_stale_record_is_flagged(kv, monkeypatch, tmp_path):
    """The record is older than its own output -- something touched the
    output after the run wrote it, so its number is not to be trusted."""
    p = tmp_path / "log.md"
    p.write_text(DOC)
    out = p.with_suffix(".kv.md")

    def reply(_who, lo, hi):
        if hi is None:
            return []
        return [{"op": "replace", "line": n, "old": DOC.split("\n")[n - 1],
                 "new": ""}
                for n in range(lo, hi + 1)
                if DOC.split("\n")[n - 1].startswith("It is worth noting")]

    run_canned(kv, monkeypatch, p, out, reply)
    record = out.with_suffix(out.suffix + ".kvrun")
    assert record.is_file(), "the run did not leave a .kvrun sidecar"
    import os
    t = record.stat().st_mtime + 2
    os.utime(out, (t, t))

    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    exp, rea = _lines(r.stdout)
    assert exp, r.stdout
    assert rea, "a stale-by-mtime record should be named, not silently dropped"
    assert not _has_number(rea), rea
    assert "stale" in rea, rea
