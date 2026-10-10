"""`--version` hashes `_legacy.py` and says nothing about what that
filename means, so the line reads as a build pinned to dead code.
"""

from conftest import run_tool


def test_version_line_says_legacy_py_is_the_live_main_module():
    r = run_tool("--version")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 2, r.stdout
    assert lines[1].strip().endswith("_legacy.py"), r.stdout
    assert "not dead code" in lines[0] or "live" in lines[0] or \
        "main module" in lines[0], (
        f"--version names no context for _legacy.py: {lines[0]!r}"
    )
