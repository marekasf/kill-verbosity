"""On Windows a CLI installed through npm is a `.cmd` shim, and `CreateProcess`
cannot run it by its bare name, so the agent is launched by its resolved path.
"""

from __future__ import annotations



def test_cli_argv_resolves_the_windows_shim_by_its_real_extension(kv):
    resolved = r"C:\Users\user\AppData\Roaming\npm\claude.cmd"

    def which(name, path=None):
        assert name == "claude"
        return resolved

    orig = kv.shutil.which
    kv.shutil.which = which
    try:
        argv, err = kv._cli_argv("claude", platform="win32")
    finally:
        kv.shutil.which = orig

    assert err is None, f"expected no error, got {err!r}"
    assert argv == [resolved], (
        "the fix must launch the shim's REAL, extensioned path -- got "
        f"{argv!r}. Reverted to the bare name, this spawns `claude` with no "
        "extension and CreateProcess raises [WinError 193] instead.")


def test_cli_argv_names_the_missing_cli_instead_of_raising_winerror(kv):
    orig = kv.shutil.which
    kv.shutil.which = lambda name, path=None: None
    try:
        argv, err = kv._cli_argv("claude", platform="win32")
    finally:
        kv.shutil.which = orig

    assert argv is None, f"expected no argv on failure, got {argv!r}"
    assert err and "claude" in err, (
        f"the refusal must name the missing CLI, not a WinError: got {err!r}")


def test_cli_argv_is_unchanged_off_windows():
    from killverbosity import _legacy as kv

    argv, err = kv._cli_argv("claude", platform="darwin")
    assert argv == ["claude"] and err is None, (
        "off Windows the bare name must pass through unresolved -- the "
        f"kernel already handles this case: got ({argv!r}, {err!r})")


def test_call_one_spawns_the_resolved_claude_path_on_windows(kv, monkeypatch):
    resolved = r"C:\Program Files\nodejs\claude.cmd"
    monkeypatch.setattr(kv.sys, "platform", "win32")
    monkeypatch.setattr(kv.shutil, "which",
                        lambda name, path=None: resolved if name == "claude"
                        else None)

    seen = {}

    class _FakeResult:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeResult()

    monkeypatch.setattr(kv.spawn, "run_tree", fake_run)

    kv._call_one("prompt text", "claude", 5)

    assert seen.get("cmd"), "no process was spawned"
    assert seen["cmd"][0] == resolved, (
        "`_call_one` must spawn the shim's resolved path, not the bare "
        f"name -- got argv {seen['cmd']!r}. The bare `claude` is exactly "
        "what raises [WinError 193] on a real Windows host.")
