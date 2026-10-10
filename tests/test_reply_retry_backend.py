"""A reply the parser rejected is re-asked SOMEWHERE ELSE, not again."""

from __future__ import annotations

import inspect
import json
import sys

import pytest


@pytest.fixture(autouse=True)
def _all_installed(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        dict.fromkeys(kv.LOCAL_AGENTS, True))

def test_the_chain_is_unchanged_when_nothing_is_avoided(kv):
    """The control, and it is the one that matters most: this parameter is on
    the path every first ask takes, so a default that alters the chain would
    change every run in the tool."""
    assert kv.agent_chain("codex") == kv.agent_chain("codex", ())
    assert kv.agent_chain("codex")[0] == "codex"


def test_an_avoided_head_drops_out_and_the_rest_survives(kv):
    chain = kv.agent_chain("codex", ("codex",))
    assert "codex" not in chain, chain
    assert chain, "every rung dropped -- the exclusion took the whole chain"
    assert chain == [b for b in kv.LOCAL_AGENTS if b != "codex"], chain


def test_an_avoided_fallback_drops_out_too(kv):
    """The head is not the only rung that can answer badly: the run may
    already be on rung 2 when the reply is rejected."""
    chain = kv.agent_chain("codex", ("claude",))
    assert "claude" not in chain, chain
    assert chain[0] == "codex", chain


def test_avoiding_every_rung_leaves_nothing_and_says_so(kv, monkeypatch):
    """An empty chain must NOT read as an empty answer. A span that needed no
    edit and a span nobody could be asked about are the same bytes otherwise,
    which is this repository's own absent-versus-unlooked-at rule."""
    monkeypatch.setattr(kv, "_call_one",
                        lambda *a, **k: pytest.fail("nothing should be sent"))
    out, err = kv.call_agent("p", "codex", 60,
                             avoid=tuple(kv.LOCAL_AGENTS))
    assert out == "", out
    assert err and "none left to ask" in err, err
    assert "codex" in err, err



def test_a_three_argument_launcher_is_not_handed_the_new_argument(kv):
    """`_accepts` is what keeps the seam honest. A stub that swallowed an
    unexpected keyword would make every case below pass against a launcher
    that ignores the exclusion entirely."""
    assert kv._accepts(kv.call_agent, "avoid")
    assert kv._accepts(kv.call_agent, "say")
    assert not kv._accepts(lambda prompt, agent, timeout: None, "avoid")
    assert not kv._accepts(lambda prompt, agent, timeout: None, "say")
    assert not kv._accepts(lambda prompt, *_: None, "avoid")


def test_takes_say_still_answers_what_it_always_did(kv):
    """The control for expressing the old helper through the new one."""
    assert kv._takes_say(kv.call_agent)
    assert not kv._takes_say(lambda prompt, agent, timeout: None)



DOC = "\n".join(
    ["# Queue notes", ""]
    + [f"It should be noted that the worker, in point of fact, retries job "
       f"{i} and records the outcome in the store for the purposes of a "
       f"later inspection by whichever operator happens to be on call."
       for i in range(1, 8)])


def _canned(kv, monkeypatch, tmp_path, garbage_until_avoided, bad_for=None,
            transport_fail=None, three_arg=False):
    """The pipeline with a launcher that answers badly on the head rung."""
    src = tmp_path / "doc.md"
    src.write_text(DOC + "\n")
    calls = []
    real_prompt = kv.job_prompt

    def spy(job, *a, **k):
        real_prompt(job, *a, **k)
        return f"@@{job['specialist']}|{job['lo']}|{job['hi']}@@ {job['unit']}"

    def answer(prompt, avoid):
        who, lo, hi = prompt.split("@@")[1].split("|")
        calls.append({"who": who, "lo": int(lo), "avoid": tuple(avoid)})
        if transport_fail is not None and who == transport_fail:
            return "", "codex exited 1"
        if (garbage_until_avoided and not avoid
                and (bad_for is None or who == bad_for)):
            return '{"edits": [{"line": 3, "new": "shorter"', None
        return json.dumps({"edits": [], "notes": []}), None

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        return answer(prompt, avoid)

    def narrow(prompt, agent, timeout):
        return answer(prompt, ())

    if three_arg:
        launcher = narrow

    monkeypatch.setattr(kv, "job_prompt", spy)
    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit as e:
        return calls, e.code
    return calls, 0


def test_the_retry_goes_to_another_backend_after_a_rejected_reply(
        kv, monkeypatch, tmp_path):
    calls, _ = _canned(kv, monkeypatch, tmp_path, garbage_until_avoided=True)
    assert calls, "EMPTY: no job was dispatched, so nothing below is a test"
    retries = [c for c in calls if c["avoid"]]
    assert retries, (
        "no ask carried an exclusion, so the retry re-asked the backend that "
        f"had just answered badly: {calls}")
    assert calls[0]["avoid"] == (), calls[0]


def test_a_healthy_run_never_excludes_anything(kv, monkeypatch, tmp_path):
    """The control. Every assertion above is satisfied by a tool that excludes
    the head rung unconditionally, which would silently move every run in this
    repository off the backend the caller named."""
    calls, _ = _canned(kv, monkeypatch, tmp_path, garbage_until_avoided=False)
    assert calls, "EMPTY: no job was dispatched"
    assert all(c["avoid"] == () for c in calls), (
        [c for c in calls if c["avoid"]])


def test_the_exclusion_is_per_job_and_not_latched_for_the_run(
        kv, monkeypatch, tmp_path):
    """One bad reply must not move the whole run off the caller's backend."""
    calls, _ = _canned(kv, monkeypatch, tmp_path, garbage_until_avoided=True,
                        bad_for="prose")
    excluded = {c["who"] for c in calls if c["avoid"]}
    assert excluded == {"prose"}, calls
    assert {c["who"] for c in calls} - {"prose"}, calls


def test_a_transport_failure_is_retried_on_the_same_backend(
        kv, monkeypatch, tmp_path):
    """Nothing came back is not answered badly, so nothing is excluded."""
    calls, _ = _canned(kv, monkeypatch, tmp_path, garbage_until_avoided=False,
                       transport_fail="prose")
    asked = [c for c in calls if c["who"] == "prose"]
    assert len(asked) >= 2, (
        "EMPTY: the transport failure was never retried, so this case cannot "
        f"see whether the retry carried an exclusion -- calls={calls}")
    assert all(c["avoid"] == () for c in asked), asked


def test_the_call_site_honours_the_seam_and_not_just_the_helper(
        kv, monkeypatch, tmp_path):
    """A three-argument launcher must survive a rejected reply."""
    calls, code = _canned(kv, monkeypatch, tmp_path,
                          garbage_until_avoided=True, three_arg=True)
    assert calls, "EMPTY: no job was dispatched, so nothing reached the gate"
    assert isinstance(code, int), code
