"""Run a child process and, on timeout, kill its whole process tree."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and every process it started.

    An agent CLI starts helpers of its own, and `Popen.kill()` reaches only the
    direct child: the helpers keep the output pipes open, so a timed-out call
    would still hang the caller. The child is started in its own session (POSIX)
    or process group (Windows), so the whole group can be killed at once.
    """
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def run_tree(cmd, timeout=None, input=None, cwd=None, env=None):  # noqa: A002
    """`subprocess.run(cmd, capture_output=True, text=True)` with a tree kill.

    Raises `subprocess.TimeoutExpired` after killing the tree, and `OSError`
    when the program cannot be started, exactly as `subprocess.run` does.
    """
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=5)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
