"""crosscheck decides "the input moved" by content, not clock."""

from __future__ import annotations

import os
import time

DOC = ("# Notes\n\nThe queue holds 40 jobs per tenant, and this sentence is, in "
       "point of fact, longer than it needs to be.\n")
EDIT = "# Notes\n\nThe queue holds 40 jobs per tenant.\n"


def _crosscheck(kv, monkeypatch, capsys, edited, orig):
    seen = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, **kw):
        seen["prompt"] = kw["input"]
        return _R()

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    args = kv.build_parser().parse_args(
        ["crosscheck", str(edited), str(orig), "--backend", "codex"])
    kv.cmd_crosscheck(args)
    return seen["prompt"], capsys.readouterr().err


def _pair(kv, tmp_path, orig_text, recorded_text, orig_newer):
    orig, edited = tmp_path / "note.md", tmp_path / "note.kv.md"
    orig.write_text(orig_text)
    edited.write_text(EDIT)
    now = time.time()
    old, new = (edited, orig) if orig_newer else (orig, edited)
    os.utime(old, (now - 172800, now - 172800))
    os.utime(new, (now, now))
    kv.write_run_record(edited, source=kv.source_fingerprint(recorded_text))
    os.utime(kv.run_record_path(edited), (now + 1, now + 1))
    return orig, edited


def test_a_touched_but_unchanged_input_is_a_matched_pair(kv, tmp_path,
                                                         monkeypatch, capsys):
    orig, edited = _pair(kv, tmp_path, DOC, DOC, orig_newer=True)
    prompt, err = _crosscheck(kv, monkeypatch, capsys, edited, orig)
    assert "NOT a matched pair" not in prompt, prompt[-600:]
    assert "moved after" not in err and "NEWER" not in err, err


def test_a_changed_input_is_reported_even_when_it_is_older(kv, tmp_path,
                                                           monkeypatch, capsys):
    orig, edited = _pair(kv, tmp_path, DOC.replace("40 jobs", "55 jobs"), DOC,
                         orig_newer=False)
    prompt, err = _crosscheck(kv, monkeypatch, capsys, edited, orig)
    assert "NOT a matched pair" in prompt, prompt[-600:]
    assert "is not the input the run read" in err, err
