"""The input moved after the edit, and nothing said so."""
import os
import time

from conftest import run_tool

DOC = ("# Notes\n\nThe registry holds 121 plugins across 8 kinds, and this "
       "sentence is, in point of fact, rather longer than it needs to be.\n")
GREW = DOC.replace("121 plugins", "167 plugins")
EDIT = ("# Notes\n\nThe registry holds 121 plugins across 8 kinds.\n")


def _pair(tmp_path, orig_text, edit_text, orig_newer):
    orig = tmp_path / "note.md"
    edited = tmp_path / "note.kv.md"
    orig.write_text(orig_text)
    edited.write_text(edit_text)
    now = time.time()
    if orig_newer:
        os.utime(edited, (now - 172800, now - 172800))
        os.utime(orig, (now, now))
    else:
        os.utime(orig, (now - 172800, now - 172800))
        os.utime(edited, (now, now))
    return orig, edited


def test_verify_says_the_input_moved_after_the_edit(tmp_path):
    orig, edited = _pair(tmp_path, GREW, EDIT, orig_newer=True)
    r = run_tool("verify", orig, edited)
    said = r.stderr
    assert "is NEWER than" in said, said
    assert "apart" in said, said
    assert "172800s apart" in said, said


def test_an_ordinary_pair_says_nothing_at_all(tmp_path):
    """The control, and it is the whole decision."""
    orig, edited = _pair(tmp_path, DOC, EDIT, orig_newer=False)
    r = run_tool("verify", orig, edited)
    assert "is NEWER than" not in r.stderr, r.stderr
    assert "moved after the edit" not in r.stderr, r.stderr


def test_the_crosscheck_reviewer_is_told_and_not_only_the_human(
        kv, tmp_path, monkeypatch):
    """The half that produces the wrong ACTION rather than the wrong reading."""
    orig, edited = _pair(tmp_path, GREW, EDIT, orig_newer=True)
    seen = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["prompt"] = kw["input"]
        return _R()

    monkeypatch.setattr(kv.spawn, "run_tree", _fake_run)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    args = kv.build_parser().parse_args(
        ["crosscheck", str(edited), str(orig), "--backend", "codex"])
    kv.cmd_crosscheck(args)
    prompt = seen["prompt"]
    assert "NOT a matched pair" in prompt, prompt[-800:]
    assert "is NEWER than" in prompt, prompt[-800:]
    assert "may never have been deleted" in prompt, prompt[-800:]
    assert "never propose" in prompt.lower(), prompt[-800:]


def test_the_crosscheck_prompt_is_clean_for_a_matched_pair(
        kv, tmp_path, monkeypatch):
    orig, edited = _pair(tmp_path, DOC, EDIT, orig_newer=False)
    seen = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["prompt"] = kw["input"]
        return _R()

    monkeypatch.setattr(kv.spawn, "run_tree", _fake_run)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    args = kv.build_parser().parse_args(
        ["crosscheck", str(edited), str(orig), "--backend", "codex"])
    kv.cmd_crosscheck(args)
    prompt = seen["prompt"]
    assert "NOT a matched pair" not in prompt, prompt[-800:]


def test_a_run_and_its_own_output_are_never_called_stale(kv, monkeypatch,
                                                         tmp_path, capsys):
    """The inner call site. `run` writes the sidecar itself, so its own inner
    `verify` must be silent -- a warning there fires on every single run."""
    from conftest import run_canned
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    run_canned(kv, monkeypatch, doc, tmp_path / "out.md", lambda *_: [])
    said = capsys.readouterr()
    assert "is NEWER than" not in said.err, said.err
