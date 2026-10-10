"""`accept` reads the `.kvcross` sidecar and warns when nothing crosschecked
the output for meaning.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from conftest import run_tool

BASE = ("# T\n\nThe room was warm and the window faced the garden, and the "
        "afternoon went by slowly.\n")
EDITED = "# T\n\nThe room was warm.\n"

WARNED = "Nothing here has crosschecked this output for meaning"


def _pair(tmp_path, name="hand"):
    src = tmp_path / f"{name}.md"
    out = tmp_path / f"{name}.kv.md"
    src.write_text(BASE)
    out.write_text(EDITED)
    return src, out


def test_no_kvcross_at_all_warns_and_still_accepts(kv, tmp_path):
    """`"missing"` -- the ordinary shape: `run` happened, `crosscheck` never
    did, and that is a legitimate, undocumented-as-wrong way to use the tool.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    assert kv.crosscheck_state(out) == "missing"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED in r.stdout, r.stdout
    assert "no .kvcross sidecar exists" in r.stdout, r.stdout


def test_a_fresh_kvcross_is_ok_and_prints_no_warning(kv, tmp_path):
    """`"ok"` -- the control. A real crosscheck ran and left a fresh record;
    accept must say nothing extra about it.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.write_crosscheck_record(
        out, backend="codex", answered_by="agy",
        answered_by_state="read", wrote=["codex"], same_family=False,
        same_family_reason=None, checked=True, not_checked_reason=None,
        dispatched=["agy"])
    assert kv.crosscheck_state(out) == "ok"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED not in r.stdout, r.stdout


def test_a_stale_kvcross_warns_and_still_accepts(kv, tmp_path):
    """`"stale"` -- the sidecar predates the output it claims to describe, so
    it is evidence about an earlier version of the file, not this one.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.write_crosscheck_record(out, backend="codex", answered_by="codex",
                               wrote=["codex"], same_family=False,
                               same_family_reason=None, checked=True,
                               not_checked_reason=None, dispatched=["codex"])
    old = time.time() - 1000
    os.utime(kv.crosscheck_record_path(out), (old, old))
    assert kv.crosscheck_state(out) == "stale"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED in r.stdout, r.stdout
    assert "older than this output" in r.stdout, r.stdout


def test_an_unparseable_kvcross_warns_and_still_accepts(kv, tmp_path):
    """`"bad"` -- the sidecar exists and is not JSON. Reachable exactly the
    way a `.kvrun` reaches the same state: a killed write, hand editing, or a
    build from before a field existed being read by one after.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.crosscheck_record_path(out).write_text("not json{\n")
    assert kv.crosscheck_state(out) == "bad"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED in r.stdout, r.stdout
    assert "will not parse" in r.stdout, r.stdout


def test_an_unavailable_kvcross_warns_and_still_accepts(kv, tmp_path):
    """`"unavailable"` -- a crosscheck was attempted and no reviewer could be
    reached at all (every candidate down or same-family). Different from
    `"missing"`: somebody asked, and there was nobody to ask.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.write_crosscheck_record(out, backend="codex", answered_by=None,
                               wrote=["codex"], same_family="unknown",
                               same_family_reason="no .kvrun record exists "
                               "beside this file", checked=False,
                               not_checked_reason="every candidate down",
                               dispatched=[], unavailable=True)
    assert kv.crosscheck_state(out) == "unavailable"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED in r.stdout, r.stdout
    assert "nobody to ask" in r.stdout, r.stdout


@pytest.mark.parametrize("state", ["missing", "ok", "stale", "bad", "unavailable"])
def test_exit_code_never_moves_with_the_crosscheck_state(kv, tmp_path, state):
    """A warning, never a refusal. Same
    pair, same run record, in every case -- only the `.kvcross` state
    differs, and the exit code must not.
    """
    src, out = _pair(tmp_path, name=f"pair-{state}")
    kv.write_run_record(out)
    if state == "ok":
        kv.write_crosscheck_record(out, backend="codex", answered_by="agy",
                                   wrote=["codex"], same_family=False,
                                   same_family_reason=None, checked=True,
                                   not_checked_reason=None, dispatched=["agy"])
    elif state == "stale":
        kv.write_crosscheck_record(out, backend="codex", answered_by="codex",
                                   wrote=["codex"], same_family=False,
                                   same_family_reason=None, checked=True,
                                   not_checked_reason=None,
                                   dispatched=["codex"])
        old = time.time() - 1000
        os.utime(kv.crosscheck_record_path(out), (old, old))
    elif state == "bad":
        kv.crosscheck_record_path(out).write_text("not json{\n")
    elif state == "unavailable":
        kv.write_crosscheck_record(out, backend="codex", answered_by=None,
                                   wrote=["codex"], same_family="unknown",
                                   same_family_reason="x", checked=False,
                                   not_checked_reason="x", dispatched=[],
                                   unavailable=True)
    assert kv.crosscheck_state(out) == state

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), \
        f"crosscheck_state={state!r} changed accept's exit code: " \
        f"{r.returncode}\n{r.stdout}{r.stderr}"



def _never_checked(kv, out, why="every candidate down", **extra):
    """The shape `_legacy.py` actually writes when nobody was asked."""
    kv.write_crosscheck_record(out, backend="codex", answered_by=None,
                               wrote=["codex"], same_family="unknown",
                               same_family_reason=None, checked=False,
                               not_checked_reason=why, dispatched=[], **extra)


def test_a_never_checked_record_is_not_ok(kv, tmp_path):
    """The defect itself. `checked: False` used to fall through every branch
    to "ok", because the only test for *nobody was asked* read a key
    (`unavailable`) that nothing writes."""
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    _never_checked(kv, out)

    assert kv.crosscheck_state(out) == "not-checked"

    r = run_tool("accept", src, out)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    assert WARNED in r.stdout, r.stdout


def test_the_recorded_reason_reaches_the_warning(kv, tmp_path):
    """`not_checked_reason` is written by every `checked=False` site and
    must be read. The warning that says no crosscheck ran is the half a
    reader can already see; WHY nobody was asked is the half only the record
    knows."""
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    _never_checked(kv, out, why="same family as the writer")

    assert kv.crosscheck_not_checked_reason(out) == "same family as the writer"
    r = run_tool("accept", src, out)
    assert "same family as the writer" in r.stdout, r.stdout


def test_a_utime_cannot_launder_a_never_checked_record(kv, tmp_path):
    """THE SERIOUS ONE. A `checked: False` record older than its output used
    to read "stale", and the obvious response to a staleness warning is to
    re-date the file -- which flipped it to "ok". So the remedy the wrong
    diagnosis invited manufactured a clean pass for a crosscheck that never
    ran, and `accept` then took text no second model had read.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    _never_checked(kv, out)

    older = out.stat().st_mtime - 3600
    os.utime(kv.crosscheck_record_path(out), (older, older))
    assert kv.crosscheck_state(out) == "not-checked", "stale must not mask it"

    os.utime(kv.crosscheck_record_path(out), None)
    assert kv.crosscheck_state(out) == "not-checked", "a utime laundered it"


def test_staleness_still_wins_for_a_record_that_was_checked(kv, tmp_path):
    """The control for the reorder. Reading `checked` before the mtime compare
    must not cost a genuinely checked record its staleness verdict -- that
    rule predates this and is the reason the sidecar is dated at all."""
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.write_crosscheck_record(out, backend="codex", answered_by="gemini",
                               wrote=["codex"], same_family=False,
                               same_family_reason=None, checked=True,
                               not_checked_reason=None, dispatched=["gemini"],
                               findings=[])
    older = out.stat().st_mtime - 3600
    os.utime(kv.crosscheck_record_path(out), (older, older))

    assert kv.crosscheck_state(out) == "stale"
    assert kv.crosscheck_not_checked_reason(out) is None


def test_an_absent_checked_key_is_not_a_false_one(kv, tmp_path):
    """Older records carry no `checked` key and are not claims that nobody
    was asked. Absence must fall through as it always did, or this fix warns
    on every old record on every host.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    kv.write_crosscheck_record(out, backend="codex", answered_by="gemini",
                               wrote=["codex"], dispatched=["gemini"])

    assert kv.crosscheck_state(out) != "not-checked"
    assert kv.crosscheck_not_checked_reason(out) is None


def test_unavailable_outranks_not_checked_when_a_record_has_both(
        kv, tmp_path):
    """Precedence, asserted rather than left to branch order. `unavailable`
    means somebody asked and there was nobody to ask; `not-checked` means only
    that no second model read this. The narrower claim gets the narrower
    message, and a record carrying both is the narrower case.
    """
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    _never_checked(kv, out, unavailable=True)

    assert kv.crosscheck_state(out) == "unavailable"
    assert kv.crosscheck_not_checked_reason(out) is None, (
        "the reason belongs to not-checked and must not leak into another "
        "state's message")


def test_every_writer_site_says_what_it_means_by_checked():
    """The writer half. A site that means *nobody was asked* has to SAY
    `checked=False`, because the reader cannot infer it.
    """
    import ast

    src = Path(__file__).resolve().parents[1] / "killverbosity" / "_legacy.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "write_crosscheck_record"]
    assert calls, "no call sites found -- the function was renamed or moved"

    silent = [c.lineno for c in calls
              if not any(k.arg == "checked" for k in c.keywords)]
    assert not silent, (
        f"{src.name} line(s) {silent} call write_crosscheck_record without an "
        f"explicit checked=; an absent key reads as could-not-tell, so a site "
        f"that means False writes a record accept cannot warn on")
