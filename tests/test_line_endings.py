"""A file's line endings survive the tool."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import run_canned, run_tool
from killverbosity.runrecord import write_run_record

BODY = (
    "# Latency\n"
    "\n"
    "It is worth noting that the p99 sits at 240 ms on the `search` path.\n"
    "\n"
    "## What to do\n"
    "\n"
    "Move the ranking call off the request path before the next release.\n"
)


def _crlf(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("utf-8")


def _endings(path: Path) -> tuple[int, int]:
    """(CRLF count, bare LF count)."""
    raw = path.read_bytes()
    return raw.count(b"\r\n"), raw.count(b"\n") - raw.count(b"\r\n")


def test_run_keeps_crlf(kv, monkeypatch, tmp_path):
    """The defect: seven CRLF lines in, zero out, on top of the real edit."""
    src = tmp_path / "in.md"
    src.write_bytes(_crlf(BODY))
    out = tmp_path / "out.md"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    crlf, lf = _endings(out)
    assert lf == 0, f"{lf} lines were rewritten to bare LF"
    assert crlf > 0


def test_run_keeps_lf(kv, monkeypatch, tmp_path):
    """The boundary. Preserving CRLF must not start emitting it everywhere."""
    src = tmp_path / "in.md"
    src.write_bytes(BODY.encode("utf-8"))
    out = tmp_path / "out.md"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    crlf, lf = _endings(out)
    assert crlf == 0, f"{crlf} lines gained a CR"
    assert lf > 0


def test_one_stray_crlf_does_not_convert_the_file(kv, monkeypatch, tmp_path):
    """A mixed file follows its majority, so the odd line out is the only edit."""
    src = tmp_path / "in.md"
    src.write_bytes(BODY.replace("# Latency\n", "# Latency\r\n").encode("utf-8"))
    out = tmp_path / "out.md"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    assert out.read_bytes() == BODY.encode("utf-8"), "the stray CRLF spread"


def test_a_tie_goes_to_lf(kv, monkeypatch, tmp_path):
    """Equal counts pick LF. Documented because nothing else decides it."""
    half = "# Latency\r\n\r\nIt is worth noting that the p99 is 240 ms here.\r\n\r\n"
    rest = "## What to do\n\nMove the ranking call off the request path.\n\n"
    src = tmp_path / "in.md"
    src.write_bytes((half + rest).encode("utf-8"))
    out = tmp_path / "out.md"
    crlf_in, lf_in = _endings(src)
    assert crlf_in == lf_in, f"the fixture is not a tie: {crlf_in} vs {lf_in}"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    crlf, _ = _endings(out)
    assert crlf == 0


def test_a_cr_only_file_keeps_its_cr(kv, monkeypatch, tmp_path):
    """`read_text` translates a lone CR too, so it needs counting to survive."""
    src = tmp_path / "in.md"
    src.write_bytes(BODY.replace("\n", "\r").encode("utf-8"))
    out = tmp_path / "out.md"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    raw = out.read_bytes()
    assert raw.count(b"\n") == 0, "a CR-only file was rewritten to LF"
    assert raw.count(b"\r") > 0


def test_non_ascii_text_survives_the_round_trip(kv, monkeypatch, tmp_path):
    """Read and write both name utf-8 now, so the locale cannot mangle a file."""
    src = tmp_path / "in.md"
    body = BODY.replace("Latency", "Latencé — naïve ☕")
    src.write_bytes(body.encode("utf-8"))
    out = tmp_path / "out.md"

    run_canned(kv, monkeypatch, src, out, lambda *_: [])

    assert "�" not in out.read_text(encoding="utf-8")
    assert "Latencé — naïve ☕" in out.read_text(encoding="utf-8")


def test_accept_refuses_two_hard_links_to_one_file(tmp_path):
    """`resolve()` sees two paths; `samefile` sees one inode."""
    src, out = tmp_path / "a.md", tmp_path / "a.kv.md"
    src.write_bytes(BODY.encode())
    os.link(src, out)
    write_run_record(out, agent="codex", incomplete=[])

    r = run_tool("accept", src, out)

    assert r.returncode == 2, r.stdout + r.stderr
    assert "same file" in r.stderr, r.stderr


@pytest.mark.parametrize("style", ["crlf", "lf"])
def test_accept_keeps_the_endings_it_was_given(tmp_path, style):
    """`accept` copies the output over the input and lost them the same way."""
    src, out = tmp_path / "a.md", tmp_path / "a.kv.md"
    edited = BODY.replace("It is worth noting that the", "The")
    src.write_bytes(_crlf(BODY) if style == "crlf" else BODY.encode())
    out.write_bytes(_crlf(edited) if style == "crlf" else edited.encode())
    write_run_record(out, agent="codex", incomplete=[])

    r = run_tool("accept", src, out)
    assert r.returncode == 0, r.stdout + r.stderr

    assert src.read_bytes() == out.read_bytes(), "accept changed the bytes"
