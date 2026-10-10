"""`accept --dry-run` printed every check EXCEPT the
crosscheck notice.
"""

from __future__ import annotations

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


def test_dry_run_prints_the_same_notice_the_real_accept_does(kv, tmp_path):
    src, out = _pair(tmp_path)
    kv.write_run_record(out)
    assert kv.crosscheck_state(out) == "missing"

    dry = run_tool("accept", "--dry-run", src, out)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert WARNED in dry.stdout, dry.stdout
    assert "no .kvcross sidecar exists" in dry.stdout, dry.stdout
    assert src.read_text() == BASE


def test_dry_run_prints_nothing_extra_when_the_crosscheck_is_ok(kv, tmp_path):
    src, out = _pair(tmp_path, name="clean")
    kv.write_run_record(out)
    kv.write_crosscheck_record(
        out, backend="codex", answered_by="agy (model=gemini-3.7-flash)",
        answered_by_state="read", wrote=["codex"], same_family=False,
        same_family_reason=None, checked=True, not_checked_reason=None,
        dispatched=["agy"])
    assert kv.crosscheck_state(out) == "ok"

    dry = run_tool("accept", "--dry-run", src, out)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert WARNED not in dry.stdout, dry.stdout
