"""The agent fallback chain, the argv each agent gets, and `--no-reorder`."""
import hashlib
import inspect
import os
import re
import sys

import pytest

from conftest import run_tool



@pytest.fixture(autouse=True)
def _all_installed(kv, monkeypatch):
    """Every local agent is installed unless a test says otherwise."""
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE",
                        {"claude": True, "codex": True, "agy": True})


def test_the_chain_leads_with_the_callers_own_backend(kv):
    assert kv.agent_chain("codex")[0] == "codex"
    assert kv.agent_chain("agy")[0] == "agy"


def test_the_chain_never_repeats_a_backend(kv):
    for named in ("claude", "codex", "agy"):
        chain = kv.agent_chain(named)
        assert len(chain) == len(set(chain)), chain
        assert chain[0] == named, chain


def test_the_fallbacks_are_the_other_installed_agents_in_order(kv):
    assert kv.agent_chain("codex") == ["codex", "claude", "agy"]
    assert kv.agent_chain("agy") == ["agy", "claude", "codex"]


def test_an_agent_that_is_not_installed_is_never_a_fallback(kv, monkeypatch):
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    assert kv.agent_chain("codex") == ["codex"]


def test_the_callers_own_agent_leads_even_when_not_installed(kv, monkeypatch):
    """Its failure is the one reported, so it is tried, not skipped."""
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"agy": True})
    assert kv.agent_chain("codex") == ["codex", "agy"]


def test_an_avoided_agent_drops_out(kv):
    assert kv.agent_chain("codex", avoid=("codex",)) == ["claude", "agy"]


def test_the_first_backends_error_is_the_one_returned(kv, monkeypatch):
    said = []
    monkeypatch.setattr(kv, "_call_one",
                        lambda _p, who, _t: ("", f"{who} said no"))
    out, err = kv.call_agent("p", "codex", 600, said.append)
    assert out == ""
    assert err == "codex said no", err
    assert any("claude" in s for s in said), said
    assert any("agy" in s for s in said), said


def test_a_fallback_that_answers_is_named(kv, monkeypatch):
    def one(_p, who, _t):
        return ("{}", None) if who == "claude" else ("", f"{who} said no")

    said = []
    monkeypatch.setattr(kv, "_call_one", one)
    out, err = kv.call_agent("p", "codex", 600, said.append)
    assert (out, err) == ("{}", None)
    joined = " ".join(said)
    assert "codex failed" in joined and "answered by claude" in joined, said


def test_the_first_backend_answering_says_nothing(kv, monkeypatch):
    said = []
    monkeypatch.setattr(kv, "_call_one", lambda _p, _w, _t: ("{}", None))
    out, err = kv.call_agent("p", "codex", 600, said.append)
    assert (out, err) == ("{}", None)
    assert said == [], said


def test_the_clock_is_shared_across_the_rungs(kv, monkeypatch):
    seen = []

    def one(_p, who, timeout):
        seen.append((who, timeout))
        kv.time.sleep(0.05)
        return "", f"{who} said no"

    monkeypatch.setattr(kv, "_call_one", one)
    kv.call_agent("p", "codex", 600, lambda _m: None)
    assert [w for w, _t in seen] == ["codex", "claude", "agy"], seen
    assert seen[1][1] <= seen[0][1] and seen[2][1] <= seen[1][1], seen


def test_a_rung_with_no_clock_left_is_not_sent(kv, monkeypatch):
    seen, said = [], []

    def one(_p, who, timeout):
        seen.append(who)
        kv.time.sleep(0.05)
        return "", f"{who} said no"

    monkeypatch.setattr(kv, "_call_one", one)
    out, err = kv.call_agent("p", "codex", 20, said.append)
    assert seen == ["codex"], seen
    assert err == "codex said no", err
    assert any("no clock left" in s for s in said), said


def test_a_wrong_backend_name_ends_the_chain_at_one_rung(kv, monkeypatch):
    seen = []

    def one(_p, who, _t):
        seen.append(who)
        raise kv.BackendUnusable(f"{who} is not usable: unknown agent")

    monkeypatch.setattr(kv, "_call_one", one)
    with pytest.raises(kv.BackendUnusable) as caught:
        kv.call_agent("p", "no-such-backend", 600, lambda _m: None)
    assert seen == ["no-such-backend"], seen
    said = str(caught.value)
    assert "not usable" in said and "no-such-backend" in said, said


def test_an_ordinary_failure_still_walks_the_whole_chain(kv, monkeypatch):
    seen = []
    monkeypatch.setattr(
        kv, "_call_one",
        lambda _p, who, _t: (seen.append(who), ("", f"{who} said no"))[1])
    kv.call_agent("p", "codex", 600, lambda _m: None)
    assert seen == ["codex", "claude", "agy"], seen


def test_a_missing_cli_still_reaches_the_next_agent(kv, monkeypatch):
    seen = []

    def one(_p, who, _t):
        seen.append(who)
        if who == "agy":
            return "{}", None
        return "", kv._LaunchError(f"could not run {who}: not found")

    monkeypatch.setattr(kv, "_call_one", one)
    out, err = kv.call_agent("p", "codex", 600, lambda _m: None)
    assert seen == ["codex", "claude", "agy"], seen
    assert (out, err) == ("{}", None)


def test_a_missing_cli_is_reported_and_not_raised(kv, monkeypatch):
    def gone(*a, **k):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(kv.spawn, "run_tree", gone)
    got, err = kv._call_one("p", "codex", 5)
    assert got == ""
    assert isinstance(err, kv._LaunchError), err
    assert "could not run codex" in err, err


def test_only_a_claude_flag_failure_is_unusable(kv):
    src = inspect.getsource(kv._call_one)
    assert src.count('if agent == "claude" and claude_flag_missing(') == 1, src
    assert src.count("raise BackendUnusable") == 1, src


def test_every_agent_gets_the_prompt_on_stdin(kv):
    for agent in kv.LOCAL_AGENTS:
        cmd, stdin = kv.agent_command(agent, [agent], "THE PROMPT", 60)
        assert "THE PROMPT" not in " ".join(cmd), (agent, cmd)
        assert "THE PROMPT" in stdin, (agent, stdin)


DOC = """# Title

It is worth noting that this opening paragraph is here so that the document has an actual body and the pipeline has something at all that it can route to a specialist for consideration.

## History

We basically tried three different things before this one and none of them really worked out in the end, which is probably worth recording somewhere but is not the thing a reader opens this document in order to find.

## Decision

At the end of the day we are going with the second option, for the reason that it is the only one of them that does not need a migration of any kind.

## Background

The system has four parts and each one of them was added for its own reason, none of which is particularly load-bearing as of today.

## Rollout

The rollout is going to happen in two stages and the second stage is gated on the first one having been observed for a week.

## Open questions

Nobody has yet decided who owns the second stage, and that needs an answer before the first stage is signed off on.
"""


def test_plan_and_run_both_take_the_flag(tmp_path):
    f = tmp_path / "d.md"
    f.write_text(DOC)
    r = run_tool("plan", f, "--no-reorder")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "usage" not in r.stderr.lower(), r.stderr
    d = run_tool("run", f, "--no-reorder", "--dry-run", "-o",
                 str(tmp_path / "o.md"))
    assert d.returncode == 0, d.stderr + d.stdout
    assert "unrecognized" not in d.stderr, d.stderr


def test_the_order_job_is_not_scheduled_under_the_flag(tmp_path):
    f = tmp_path / "d.md"
    f.write_text(DOC)
    out = tmp_path / "o.md"
    on = run_tool("run", f, "--dry-run", "-o", str(out))
    off = run_tool("run", f, "--no-reorder", "--dry-run", "-o", str(out))
    assert on.returncode == off.returncode == 0, (on.stderr, off.stderr)
    assert "order" in on.stdout, on.stdout
    assert "order" not in off.stdout, off.stdout


def test_merge_refuses_a_move_under_the_flag(kv):
    lines = DOC.split("\n")
    prose, headings, tables, quotes = kv.mask(DOC, "d")
    ed = kv.editable_lines(prose, tables, headings, quotes)
    hist = next(i for i, l in enumerate(lines, 1) if l == "## History")
    openq = next(i for i, l in enumerate(lines, 1) if l == "## Open questions")
    res = [{"specialist": "structure",
            "edits": [{"op": "move", "line": openq, "to": hist,
                       "why": "the open questions before the history"}]}]

    _m, applied, no, _d = kv.merge(list(lines), res, ed,
                                   {l for l, _ in quotes}, headings,
                                   reorder=False)
    assert applied == [], applied
    assert no and "--no-reorder" in no[0][2], no

    _m2, applied2, no2, _d2 = kv.merge(list(lines), res, ed,
                                       {l for l, _ in quotes}, headings)
    assert len(applied2) == 1, (applied2, no2)
    assert applied2[0][2] == "move", applied2


def test_a_move_that_lands_is_named_with_both_line_numbers(kv, monkeypatch,
                                                           tmp_path):
    from conftest import run_canned

    f = tmp_path / "d.md"
    f.write_text(DOC)
    out = tmp_path / "o.md"
    lines = DOC.split("\n")
    hist = next(i for i, l in enumerate(lines, 1) if l == "## History")
    openq = next(i for i, l in enumerate(lines, 1) if l == "## Open questions")

    def reply(who, _lo, hi):
        if who != "structure" or hi is not None:
            return []
        return [{"op": "move", "line": openq, "to": hist,
                 "why": "the open questions before the history"}]

    printed = []
    real = print

    def spy(*a, **k):
        printed.append(" ".join(str(x) for x in a))
        real(*a, **k)

    monkeypatch.setattr("builtins.print", spy)
    run_canned(kv, monkeypatch, f, out, reply)
    monkeypatch.undo()
    said = "\n".join(printed)
    assert "1 section moved" in said, said
    assert "moved —" in said, said
    assert "## Open questions" in said.split("moved —")[1], said
    _row = next(l for l in said.split("\n") if f"L{openq} → L" in l)
    _to = int(re.search(rf"L{openq} → L(\d+)", _row).group(1))
    assert _to != openq, _row
    assert out.read_text().split("\n")[_to - 1] == "## Open questions", _row



def _exe(cmd):
    return os.path.splitext(os.path.basename(cmd[0]))[0].lower()


def _cc_argv(kv, tmp_path, monkeypatch, backend):
    """The argv `crosscheck` would run, with nothing actually spawned."""
    orig = tmp_path / "a.md"
    orig.write_text("# T\n\nA sentence that says a thing.\n")
    edited = tmp_path / "b.md"
    edited.write_text("# T\n\nA sentence saying a thing.\n")
    seen = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, **kw):
        seen.setdefault("cmd", cmd)
        return _R()

    monkeypatch.setattr(kv.spawn, "run_tree", fake)
    args = kv.build_parser().parse_args(
        ["crosscheck", str(edited), str(orig), "--backend", backend])
    kv.cmd_crosscheck(args)
    return seen["cmd"]


def test_crosscheck_on_claude_runs_the_local_cli_in_print_mode(
        kv, tmp_path, monkeypatch):
    cmd = _cc_argv(kv, tmp_path, monkeypatch, "claude")
    assert _exe(cmd) == "claude" and cmd[1] == "-p", cmd


def test_crosscheck_on_codex_runs_a_read_only_sandbox(kv, tmp_path,
                                                      monkeypatch):
    cmd = _cc_argv(kv, tmp_path, monkeypatch, "codex")
    assert _exe(cmd) == "codex" and cmd[1] == "exec", cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only", cmd


def test_crosscheck_on_agy_runs_sandboxed(kv, tmp_path, monkeypatch):
    cmd = _cc_argv(kv, tmp_path, monkeypatch, "agy")
    assert _exe(cmd) == "agy" and "--sandbox" in cmd, cmd


def test_every_local_agent_is_offered_when_the_writer_is_unknown(kv):
    assert kv.crosscheck_offer(None) == list(kv.LOCAL_AGENTS)


def test_the_writers_own_family_is_not_offered(kv):
    offer = kv.crosscheck_offer("codex")
    assert "codex" not in offer and "claude" in offer, offer


_USAGE_DOC = "\n".join(
    ["# Platform notes", ""]
    + [f"The worker retries job {i} and records the outcome in Loki. "
       f"The retry budget is {i * 3} seconds and the operator is paged after "
       f"it, which is a thing the runbook says twice. "
       for i in range(1, 14)])


def _usage_run(kv, monkeypatch, tmp_path, reply):
    """Drive a whole `run` with one canned launcher. Returns the ask count."""
    src = tmp_path / "doc.md"
    src.write_text(_USAGE_DOC + "\n")
    calls = []

    def agent(prompt, *_a):
        calls.append(hashlib.sha1(prompt.encode()).hexdigest()[:12])
        return reply(prompt)

    monkeypatch.setattr(kv, "call_agent", agent)
    monkeypatch.setattr(kv, "JOBS", 1)
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "run", str(src),
                                      "-o", str(tmp_path / "out.md")])
    try:
        kv.main()
    except SystemExit:
        pass
    return calls


def test_a_usage_error_is_asked_once_and_not_once_per_job(kv, monkeypatch,
                                                          tmp_path, capsys):
    def boom(_p):
        raise kv.BackendUnusable("no-such-backend is not usable: exit 2")

    calls = _usage_run(kv, monkeypatch, tmp_path, boom)
    capsys.readouterr()
    assert calls == calls[:1], calls
    assert len(calls) == 1, len(calls)


def test_an_ordinary_failure_is_still_asked_for_every_job_and_retried(
        kv, monkeypatch, tmp_path, capsys):
    calls = _usage_run(kv, monkeypatch, tmp_path,
                       lambda _p: ("", "codex exited 1"))
    said = capsys.readouterr()
    assert "retry" in (said.out + said.err).lower()
    jobs = len(set(calls))
    assert jobs > 1, jobs
    assert len(calls) == jobs * 2, (len(calls), jobs)


def test_the_report_says_the_spans_were_never_edited_not_that_it_died_twice(
        kv, monkeypatch, tmp_path, capsys):
    def boom(_p):
        raise kv.BackendUnusable("no-such-backend is not usable: exit 2")

    _usage_run(kv, monkeypatch, tmp_path, boom)
    said = capsys.readouterr()
    out = said.out + said.err
    assert "no-such-backend is not usable" in out, out[-2000:]
    assert "retry" not in out.lower(), out[-2000:]
    assert "--agent" in out, out[-2000:]
    assert "--timeout if the whole run needs longer" not in out, out[-2000:]
    assert "run the same command again" not in out.lower(), out[-2000:]


def test_a_clock_that_ran_out_still_gets_the_resume_advice(kv):
    from killverbosity import budget as kvb
    said = kvb.finish_advice(3, 0, "", 9, "d.kv.md", "d.kvjournal")
    assert "run the same command again" in said.lower(), said
    assert "--agent" not in said, said
    usage = kvb.finish_advice(3, 0, "", 9, "d.kv.md", "d.kvjournal",
                              unusable="no-such-backend is not usable: x")
    assert "--agent" in usage and "no-such-backend" in usage, usage
    assert "run the same command again" not in usage.lower(), usage



def _flagged(cmd, flag):
    """The value `flag` was given, or None, from the `--flag=VALUE` form."""
    hits = [a for a in cmd if a.startswith(flag + "=")]
    return hits[0][len(flag) + 1:] if hits else None


def test_the_crosscheck_reviewer_gets_the_read_tools_and_nothing_else(
        kv, tmp_path, monkeypatch):
    cmd = _cc_argv(kv, tmp_path, monkeypatch, "claude")
    assert "--restricted" in cmd, cmd
    tools = _flagged(cmd, "--tools")
    assert tools is not None, cmd
    assert "--tools" not in cmd, cmd
    got = set(tools.split(","))
    assert got == {"Read", "Grep", "Glob"}, got
    assert "Bash" not in got and "Write" not in got and "Edit" not in got, got


def test_a_specialist_on_the_local_cli_gets_no_tools_at_all(kv, monkeypatch):
    """A different set, and one list for both would be the wider of them."""
    seen = {}

    class _R:
        returncode, stdout, stderr = 0, '{"edits": [], "notes": []}', ""

    monkeypatch.setattr(kv.spawn, "run_tree",
                        lambda cmd, **kw: (seen.__setitem__("cmd", cmd), _R())[1])
    kv._call_one("a prompt", "claude", 10)
    cmd = seen["cmd"]
    assert "--restricted" in cmd, cmd
    assert _flagged(cmd, "--tools") == "", cmd
    assert "--tools" not in cmd, cmd


def test_every_other_backend_is_unaffected(kv, tmp_path, monkeypatch):
    """The control, and it is the whole decision."""
    cmd = _cc_argv(kv, tmp_path, monkeypatch, "codex")
    assert "--restricted" not in cmd, cmd
    assert not any(a.startswith("--tools") for a in cmd), cmd

    seen = {}

    class _R:
        returncode, stdout, stderr = 0, "{}", ""

    monkeypatch.setattr(kv.spawn, "run_tree",
                        lambda cmd, **kw: (seen.__setitem__("cmd", cmd), _R())[1])
    kv._call_one("a prompt", "codex", 10)
    assert "--restricted" not in seen["cmd"], seen["cmd"]
    assert not any(a.startswith("--tools") for a in seen["cmd"]), seen["cmd"]


def test_a_claude_too_old_for_the_flag_says_so_once_and_stops(kv, monkeypatch):
    """`--restricted` postdates some installed builds."""
    class _R:
        returncode = 1
        stdout = ""
        stderr = "error: unknown option '--restricted'"

    monkeypatch.setattr(kv.spawn, "run_tree", lambda cmd, **kw: _R())
    with pytest.raises(kv.BackendUnusable) as e:
        kv._call_one("a prompt", "claude", 10)
    said = str(e.value)
    assert "--restricted" in said, said
    assert "--agent codex" in said or "--agent agy" in said, said


def test_an_ordinary_claude_failure_is_still_an_ordinary_failure(kv,
                                                                 monkeypatch):
    """The control. Keyed on the flag name and on argparse-family wording, so
    a review that fails for its own reasons must NOT be given this remedy --
    including one whose own text happens to mention restrictions."""
    class _R:
        returncode = 1
        stdout = ""
        stderr = "the model refused: this content is restricted"

    monkeypatch.setattr(kv.spawn, "run_tree", lambda cmd, **kw: _R())
    got, err = kv._call_one("a prompt", "claude", 10)
    assert got == "" and err, (got, err)
    assert "Upgrade" not in err and "--agent codex" not in err, err
