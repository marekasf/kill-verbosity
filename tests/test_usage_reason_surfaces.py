"""What reason a failed agent call reports, and when a failure is unusable."""

from __future__ import annotations


class _FakeResult:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_streamed_failure_keeps_the_last_three_lines(kv):
    stderr = (
        "codex: starting up\n"
        "codex: loading workspace\n"
        "\n"
        "codex: 403 Blocked by policy\n"
    )
    assert kv._why_it_died(stderr) == (
        "codex: starting up · codex: loading workspace · "
        "codex: 403 Blocked by policy")


def test_only_the_tail_survives_a_long_banner(kv):
    stderr = "".join(f"banner line {i}\n" for i in range(10)) + "the reason\n"
    reason = kv._why_it_died(stderr)
    assert reason.endswith("the reason")
    assert "banner line 0" not in reason


def test_a_nonzero_exit_from_a_real_agent_is_an_ordinary_error(kv, monkeypatch):
    """Exit 2 from an installed agent is the agent refusing, not a bad name.
    It must come back as an error string the caller can fall back from."""
    def _run(*a, **k):
        return _FakeResult(2, stderr="quota exceeded\n")
    monkeypatch.setattr(kv.spawn, "run_tree", _run)
    out, err = kv._call_one("prompt", "codex", 5)
    assert out == ""
    assert "codex exited 2" in err and "quota exceeded" in err, err
    assert "is not usable" not in err, err


def test_an_unknown_agent_name_runs_as_a_custom_command(kv, monkeypatch):
    calls = []
    monkeypatch.setattr(kv.spawn, "run_tree",
                        lambda *a, **k: calls.append(a) or _FakeResult(0, "x"))
    out, err = kv._call_one("prompt", "soxed --flag", 5)
    assert err is None and out == "x", (out, err)
    assert calls and calls[0][0][1:] == ["--flag"], calls
