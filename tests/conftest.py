"""Shared fixtures."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "kill-verbosity"
sys.path.insert(0, str(REPO))

@pytest.fixture(scope="session")
def kv():
    """The tool, imported as a module."""
    from killverbosity import _legacy

    return _legacy


_IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache",
            ".ruff_cache", "node_modules", ".coverage", ".idea", ".DS_Store"}

_OWNED = ("kill-verbosity", "killverbosity", "SKILL.md", "README.md",
          "specialists", "profiles", "docs", "tests")


def _tree() -> dict:
    """Every file the tool ships, by content digest."""
    out = {}
    for rel in _OWNED:
        root = REPO / rel
        if not root.exists():
            continue
        for p in ([root] if root.is_file() else root.rglob("*")):
            if p.is_file() and not _IGNORED & set(p.parts):
                out[str(p.relative_to(REPO))] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="session", autouse=True)
def _repo_stays_clean():
    """The suite must leave the repository exactly as it found it."""
    before = _tree()
    yield
    after = _tree()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after)
                     if before[p] != after[p])
    report = [f"{label}:\n  " + "\n  ".join(paths)
              for label, paths in (("created", added), ("deleted", removed),
                                   ("modified", changed)) if paths]
    assert not report, (
        "the suite changed the repository. Copy the file into tmp_path and "
        "run against the copy:\n" + "\n".join(report))


@pytest.fixture(autouse=True)
def _default_profile():
    """Put the default profile back after every test."""
    yield
    from killverbosity import _legacy

    if _legacy.PROFILE_NAME != "default":
        _legacy.reset_profile()


@pytest.fixture(autouse=True)
def _agents_resolve_on_windows(monkeypatch):
    """Windows _cli_argv needs shutil.which to find the agent; tests stub the spawn."""
    if sys.platform == "win32":
        monkeypatch.setattr(shutil, "which", lambda n, *a, **k: n)


@pytest.fixture
def doc(tmp_path):
    """Write a document to a scratch file and return its path."""

    def _write(text, name="doc.md"):
        p = tmp_path / name
        p.write_text(text if text.endswith("\n") else text + "\n")
        return p

    return _write


def run_tool(*args, binary=None, cwd=None, force=False):
    """Run the CLI end to end and return the completed process."""
    return subprocess.run(
        [sys.executable, str(binary or LAUNCHER), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "KV_FORCE": "1"} if force else None,
    )


def run_canned(kv, monkeypatch, path, out, reply, extra=(), notes=None):
    """Run the real pipeline with the agent replaced by `reply`."""
    import json

    seen = []
    real_prompt = kv.job_prompt

    def spy(job, *a, **k):
        real_prompt(job, *a, **k)
        seen.append((job["specialist"], job["unit"]))
        return f"@@{job['specialist']}|{job['lo']}|{job['hi']}@@ {job['unit']}"

    def agent(prompt, *_):
        who, lo, hi = prompt.split("@@")[1].split("|")
        lo, hi = int(lo), None if hi == "None" else int(hi)
        return json.dumps({"edits": reply(who, lo, hi),
                           "notes": notes(who, lo, hi) if notes else []}), None

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(
        sys, "argv", ["kill-verbosity", "run", str(path), "-o", str(out), *extra]
    )
    kv.main()
    return seen


@pytest.fixture
def symlinked_launcher(tmp_path):
    """The launcher reached through a relative symlink, as it ships."""
    skill = tmp_path / "skill"
    skill.mkdir(parents=True)
    link = skill / "kill-verbosity"
    try:
        link.symlink_to(LAUNCHER)
    except OSError as e:  # Windows without Developer Mode
        pytest.skip(f"cannot create a symlink here: {e}")
    return link

