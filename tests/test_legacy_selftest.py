"""The monolith's own assertions, run under pytest."""

from pathlib import Path

import pytest
from conftest import run_tool

FLOOR = 962

SPECIALIST_DIR = Path(__file__).resolve().parent.parent / \
    "specialists"


@pytest.mark.slow
def test_legacy_selftest_passes():
    r = run_tool("selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest ok" in r.stdout, r.stdout


@pytest.mark.slow
def test_legacy_selftest_check_count_does_not_silently_drop():
    """A refactor that deletes assertions must say so."""
    r = run_tool("selftest")
    count = int(r.stdout.split("(")[1].split()[0])
    assert count >= FLOOR, (
        f"selftest is down to {count} checks from {FLOOR}. If checks moved to "
        f"their own test files, lower this number in the same commit."
    )


@pytest.mark.slow
def test_legacy_selftest_never_writes_the_shipped_specialist_prompts():
    """Row T19 (Windows): selftest rewrote `specialists/summary.md` with CRLF
    line endings, 0 CR before and 129 after, same text — because one check
    mutated the SHIPPED file in place with `write_text` (default
    `newline=None`, which TRANSLATES `\\n` to `os.linesep` on write) and
    restored it by writing the same string back, which is not the same
    bytes on a platform whose line separator is not `\\n`.
    """
    files = sorted(SPECIALIST_DIR.glob("*.md"))
    assert files, f"no specialist prompts found under {SPECIALIST_DIR}"
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}

    r = run_tool("selftest")
    assert r.returncode == 0, r.stdout + r.stderr

    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    for p in files:
        assert before[p][0] == after[p][0], \
            f"selftest changed the bytes of a shipped prompt: {p}"
        assert before[p][1] == after[p][1], \
            f"selftest rewrote a shipped prompt in place (mtime moved): {p}"
