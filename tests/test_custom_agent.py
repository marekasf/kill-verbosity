"""Any agent CLI works: a command that is not claude/codex/agy runs as given."""

import shlex
import sys

import pytest


@pytest.fixture
def nothing_installed(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {})
    monkeypatch.delenv("KV_AGENT", raising=False)


def test_custom_agent_answers_from_stdout(kv, tmp_path, nothing_installed):
    script = tmp_path / "agent.py"
    script.write_text("import sys\nsys.stdin.read()\n"
                      "print('{\"edits\": [], \"notes\": []}')\n")
    quote = str if sys.platform == "win32" else shlex.quote  # non-posix split keeps quotes
    agent = kv.agent_name(f"{quote(sys.executable)} {quote(str(script))}")
    assert kv.is_custom_agent(agent) and kv.agent_installed(agent)
    out, err = kv.call_agent("PROMPT", agent, 60)
    assert err is None, err
    payload, perr = kv.parse_reply(out)
    assert perr is None and payload == {"edits": [], "notes": []}, (out, perr)


def test_no_agent_names_both_remedies(kv, nothing_installed):
    with pytest.raises(kv.UsageError) as e:
        kv.default_agent()
    assert "install one of claude/codex/agy" in str(e.value)
    assert "--agent '<your agent command>'" in str(e.value)
