r"""Does the launcher restart in UTF-8 text mode when the locale is not UTF-8."""

import os
import subprocess
import sys

import pytest
from conftest import LAUNCHER

pytestmark = pytest.mark.smoke

ENTRY = str(LAUNCHER)
HOP, GUARD = "reexec_utf8", "KV_REEXEC"

MARKER = "UTF8-HOPPED-TO"
RETURNED = "UTF8-RETURNED-WITHOUT-EXITING"

WIN = sys.platform == "win32"
posix_only = pytest.mark.skipif(WIN, reason="needs an ASCII locale or a /bin/sh")

HOSTILE = {"PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"}

def _env(hostile=True, **extra):
    """The ambient environment with every guard cleared, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if k != GUARD}
    if hostile:
        env.update(HOSTILE)
    else:
        for k in HOSTILE:
            env.pop(k, None)
    env.update(extra)
    return env


def _fake_python(tmp_path, guard, rc=0):
    """A script standing in for the interpreter the hop execs."""
    if WIN:
        fake = tmp_path / "fake-python.cmd"
        fake.write_text(
            f"@echo off\r\necho {MARKER} %0 %*\r\n"
            f"if defined {guard} (echo GUARD=set) else (echo GUARD=)\r\n"
            f"exit /b {rc}\r\n", encoding="utf-8")
        return fake
    fake = tmp_path / "fake-python"
    fake.write_text(
        f'#!/bin/sh\necho "{MARKER} $0 $@"\necho "GUARD=${{{guard}:+set}}"\n'
        f"exit {rc}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


_DRIVE = """
import sys, types
src = open({entry!r}, encoding="utf-8").read()
ns = {{"__file__": {entry!r}, "__name__": "drive"}}
exec(compile(src, {entry!r}, "exec"), ns)
ns["WINDOWS"] = {windows}
ns["sys"] = types.SimpleNamespace(
    flags=sys.flags, argv=[{entry!r}, "selftest"], executable={fake!r},
    stderr=sys.stderr, version_info=sys.version_info, path=sys.path,
    modules=sys.modules, exit=sys.exit)
ns[{hop!r}]()
print({returned!r})
"""


def _drive(tmp_path, windows=WIN, rc=0, opt=False, hostile=True,
           guard_preset=False):
    """Run the launcher's hop under a chosen arm and hand back the result."""
    fake = _fake_python(tmp_path, GUARD, rc=rc)
    src = _DRIVE.format(
        entry=ENTRY, fake=str(fake), hop=HOP, windows=bool(windows),
        returned=RETURNED)
    extra = {GUARD: "1"} if guard_preset else {}
    if not hostile:
        # Windows text IO is the ANSI code page unless asked otherwise, so
        # "not hostile" has to ask for UTF-8 mode outright to be a no-op there.
        extra["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, *(["-O"] if opt else []), "-c", src],
        capture_output=True, text=True, env=_env(hostile, **extra))


_PROBE = (
    "import sys, codecs, locale\n"
    "print('utf8_mode', sys.flags.utf8_mode)\n"
    "print('preferred', codecs.lookup("
    "locale.getpreferredencoding(False)).name)\n"
)


def _probe(env):
    r = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True,
        env=env)
    assert r.returncode == 0, r.stderr
    return dict(line.split(" ", 1) for line in r.stdout.strip().splitlines())


@posix_only
def test_the_hostile_environment_is_really_hostile():
    """THE INSTRUMENT PROVING ITSELF, and it is not a formality here."""
    assert _probe(_env(hostile=True)) == {
        "utf8_mode": "0", "preferred": "ascii"}
    assert _probe(_env(hostile=False))["preferred"] == "utf-8"
    near_miss = _env(hostile=False, LC_ALL="C")
    assert _probe(near_miss)["utf8_mode"] == "1", (
        "`LC_ALL=C` alone is a UTF-8 environment on this interpreter; a case "
        "written with it measures the no-op arm")


@pytest.mark.parametrize("windows", [False, True], ids=["execv", "spawn"])
@pytest.mark.parametrize("rc", [0, 3])
def test_the_hop_reports_the_status_the_child_exited_with(
        windows, rc, tmp_path):
    """The reported harm is a status, and it is lost on the Windows arm only."""
    if WIN and not windows:
        pytest.skip("os.execv does not replace the process on Windows")
    r = _drive(tmp_path, windows=windows, rc=rc)

    assert r.returncode == rc, (r.returncode, r.stdout, r.stderr)
    assert MARKER in r.stdout, (r.stdout, r.stderr)
    assert RETURNED not in r.stdout, r.stdout


def test_the_hop_hands_the_child_x_utf8_ahead_of_the_script(tmp_path):
    """`-X utf8` has to reach the INTERPRETER, not the script."""
    said = _drive(tmp_path).stdout
    argv = said.split()

    assert "-X" in argv, said
    assert "utf8" in argv, said
    assert argv.index("-X") == argv.index("utf8") - 1, said
    assert argv.index("utf8") < argv.index(ENTRY), said
    assert "selftest" in argv, said


def test_an_interpreter_already_in_utf8_mode_does_not_hop(tmp_path):
    """THE NO-OP CONTROL, and it is what makes this change free on POSIX."""
    r = _drive(tmp_path, hostile=False)

    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert MARKER not in r.stdout, r.stdout
    assert RETURNED in r.stdout, (r.stdout, r.stderr)


def test_the_loop_guard_is_armed_before_the_child_starts(tmp_path):
    """Not infinite, in the only place it can be observed from outside."""
    said = _drive(tmp_path).stdout

    assert "GUARD=set" in said, (
        f"the hop did not arm {GUARD}, so a child that drops "
        f"`-X utf8` hops again for ever:\n{said}")


def test_a_preset_guard_suppresses_the_hop(tmp_path):
    """The guard read, with the hostile environment held."""
    r = _drive(tmp_path, guard_preset=True)

    assert MARKER not in r.stdout, r.stdout
    assert RETURNED in r.stdout, (r.stdout, r.stderr)


def test_dash_o_survives_the_hop(tmp_path):
    """`-O` is forwarded, because the selftest refuses to run under it."""
    argv = _drive(tmp_path, opt=True).stdout.split()

    assert "-O" in argv, argv
    assert argv.index("utf8") < argv.index("-O"), argv
    assert argv.index("-O") < argv.index(ENTRY), argv
    assert "-O" not in _drive(tmp_path, opt=False).stdout.split()


def test_the_real_tool_runs_under_a_non_utf8_locale():
    """End to end, no injection: the selftest under an ASCII locale."""
    cmd = [sys.executable, ENTRY, "selftest"]
    hostile = subprocess.run(
        cmd, capture_output=True, text=True, env=_env(hostile=True))
    ordinary = subprocess.run(
        cmd, capture_output=True, text=True, env=_env(hostile=False))

    assert "Traceback" not in hostile.stderr, hostile.stderr
    assert hostile.returncode == ordinary.returncode == 0, (
        hostile.returncode, ordinary.returncode, hostile.stderr)
    last = hostile.stdout.strip().splitlines()[-1]
    assert last == ordinary.stdout.strip().splitlines()[-1], (
        last, ordinary.stdout.strip().splitlines()[-1])


@posix_only
def test_the_guard_is_what_stops_a_second_hop():
    """With the guard preset the hop is skipped, and the ASCII locale bites."""
    r = subprocess.run(
        [sys.executable, ENTRY, "selftest"], capture_output=True, text=True,
        env=_env(hostile=True, **{GUARD: "1"}))
    assert r.returncode == 1, (r.returncode, r.stderr[-2000:])
    assert "UnicodeDecodeError" in r.stderr or \
           "UnicodeEncodeError" in r.stderr, r.stderr[-2000:]
