"""running the tool must not write `__pycache__` into the tool tree."""

import os
import shutil
import subprocess
import sys

import pytest
from conftest import LAUNCHER, REPO

pytestmark = pytest.mark.smoke

HOSTILE = {"PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}


pytestmark = pytest.mark.skipif(
    getattr(sys, "pycache_prefix", None) is not None,
    reason="this interpreter writes bytecode under sys.pycache_prefix, "
           "never beside the source, so nothing here can be observed")


def _copy(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(LAUNCHER, root / "kill-verbosity")
    shutil.copytree(REPO / "killverbosity", root / "killverbosity",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _env():
    return {k: v for k, v in os.environ.items()
            if k not in ("KV_REEXEC", "PYTHONDONTWRITEBYTECODE")}


def _caches(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("__pycache__"))


def test_the_copy_can_grow_a_cache_at_all(tmp_path):
    """Control: a plain import of the copied package writes bytecode."""
    root = _copy(tmp_path)
    r = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(root)!r}); "
         "import killverbosity._legacy"],
        capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stderr
    assert _caches(root), "the control wrote no __pycache__, so the cases " \
        "below cannot tell a fix from a copy that never compiles"


def test_version_in_place_writes_no_bytecode(tmp_path):
    root = _copy(tmp_path)
    r = subprocess.run(
        [sys.executable, str(root / "kill-verbosity"), "--version"],
        capture_output=True, text=True, env=_env())
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.strip(), r.stderr
    assert not _caches(root), f"--version wrote bytecode: {_caches(root)}"


def test_version_after_the_utf8_hop_writes_no_bytecode(tmp_path):
    """Under a non-UTF-8 locale the launcher re-execs itself and keeps `-B`."""
    root = _copy(tmp_path)
    r = subprocess.run(
        [sys.executable, str(root / "kill-verbosity"), "--version"],
        capture_output=True, text=True, env={**_env(), **HOSTILE})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.strip(), r.stderr
    assert not _caches(root), \
        f"--version after the hop wrote bytecode: {_caches(root)}"
