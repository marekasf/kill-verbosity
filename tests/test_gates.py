"""A tree's own structural checks, run inside `verify`."""
import ast
import json
import os
import stat
import sys

import pytest

from conftest import run_tool
from killverbosity import gates
from killverbosity.runrecord import write_run_record

DOC = ("# Notes\n\n| id | state |\n|---|---|\n| C1 | done |\n\n"
       "This paragraph is, in point of fact, considerably longer than it "
       "strictly needs to be.\n")
READS = "import sys; open(sys.argv[1]).read()"

SHORT = DOC.replace("This paragraph is, in point of fact, considerably longer "
                    "than it strictly needs to be.",
                    "This paragraph is too long.")


@pytest.fixture(autouse=True)
def _own_trust_store(tmp_path, monkeypatch):
    """The trust store must never be the developer's own."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def _gate(tmp_path, argv, name="cells", timeout=30):
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps(
        {"gates": [{"name": name, "argv": argv, "timeout": timeout}]}))
    return tmp_path / ".killverbosity.gates.json"


def _pair(tmp_path, edited=SHORT):
    (tmp_path / "note.md").write_text(DOC)
    (tmp_path / "note.kv.md").write_text(edited)
    return tmp_path / "note.md", tmp_path / "note.kv.md"


def _ready(tmp_path, **kw):
    """A pair `accept` will look at."""
    orig, edited = _pair(tmp_path, **kw)
    write_run_record(edited, agent="codex", incomplete=[])
    return orig, edited


def _script(tmp_path, body, name="gate.py"):
    p = tmp_path / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _trusted(tmp_path, argv, **kw):
    g = _gate(tmp_path, argv, **kw)
    r = run_tool("trust", g)
    assert r.returncode == 0, r.stdout + r.stderr
    return g



def test_an_untrusted_declaration_executes_nothing(tmp_path):
    """The declaration is found by walking UP from the document."""
    _gate(tmp_path, [sys.executable, "-c",
                     "open('RAN','w').write('x')", "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "no acknowledgement in" in r.stderr, r.stderr
    assert str(gates.trust_store()) in r.stderr, r.stderr
    assert "kill-verbosity trust" in r.stderr, r.stderr
    assert not (tmp_path / "RAN").exists(), "the gate executed anyway"


def test_editing_a_trusted_declaration_untrusts_it(tmp_path):
    """Keyed on path AND content hash, the shape `direnv allow` has."""
    g = _trusted(tmp_path, [sys.executable, "-c", READS, "{edited}"])
    orig, edited = _pair(tmp_path)
    assert "no acknowledgement in" not in run_tool("verify", orig,
                                                   edited).stderr
    g.write_text(g.read_text().replace(READS, READS + " "))
    r = run_tool("verify", orig, edited)
    assert "no acknowledgement in" in r.stderr, r.stderr


def test_trust_refuses_a_declaration_that_cannot_run(tmp_path):
    """Recording an approval for bytes nobody has seen work banks nothing."""
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps(
        {"gates": [{"name": "x", "argv": ["true"], "timeout": 5}]}))
    r = run_tool("trust", tmp_path / ".killverbosity.gates.json")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "{edited}" in r.stderr, r.stderr


def test_trust_takes_only_the_one_filename(tmp_path):
    other = tmp_path / "something.json"
    other.write_text("{}")
    r = run_tool("trust", other)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "only a file named" in r.stderr, r.stderr



def test_a_gate_that_cannot_see_the_edit_is_refused_before_it_runs(tmp_path):
    """No `{edited}` means the same verdict for ever."""
    _gate(tmp_path, [sys.executable, "-c", READS, "{original}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "cannot see the edit" in r.stderr, r.stderr
    assert "GATES" not in r.stdout, r.stdout
    assert "cannot fail" in r.stderr, r.stderr
    assert "TAKE A PATH" in r.stderr, r.stderr


def test_a_fixed_path_gate_is_the_shape_this_refusal_exists_for(tmp_path):
    """The real input, not a synthetic one."""
    _gate(tmp_path, [sys.executable, "-c",
                     "open('RAN','w').write('x')"], name="tracker-columns")
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "tracker-columns" in r.stderr, r.stderr
    assert "cannot see the edit" in r.stderr, r.stderr
    assert not (tmp_path / "RAN").exists(), "a gate that cannot fail ran"
    assert "declared check" not in r.stdout, r.stdout


def test_a_gate_with_no_timeout_is_refused(tmp_path):
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps(
        {"gates": [{"name": "x", "argv": ["echo", "{edited}"]}]}))
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "timeout" in r.stderr and "hangs" in r.stderr, r.stderr


def test_a_command_line_in_one_string_is_refused(tmp_path):
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps(
        {"gates": [{"name": "x", "argv": "echo {edited}", "timeout": 5}]}))
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "non-empty list of strings" in r.stderr, r.stderr



def test_a_passing_gate_is_reported_and_blocks_nothing(tmp_path):
    _trusted(tmp_path, [sys.executable, "-c", READS, "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "1 declared check passed (cells via " in r.stdout, r.stdout
    assert f"(cells via {sys.executable})" in r.stdout, r.stdout
    assert r.returncode in (0, 3), (r.returncode, r.stdout)


def test_a_gate_the_edit_breaks_fails_the_verify(tmp_path):
    g = _script(tmp_path, "import sys\n"
                          "sys.exit(0 if 'in point of fact' in "
                          "open(sys.argv[1]).read() else 7)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "GATES BROKEN" in r.stdout, r.stdout
    assert "exited 7" in r.stdout, r.stdout


def test_a_gate_already_red_on_the_original_refuses_and_names_itself(tmp_path):
    """A red baseline cannot attribute anything, and delta-scoring cannot save
    it: shorten an over-budget cell to 790 while dropping a pipe elsewhere and
    the failure count goes 1 -> 1, so any count comparison passes it."""
    g = _script(tmp_path, "import sys\nsys.exit(9)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "GATES ALREADY RED" in r.stdout, r.stdout
    assert "KV_GATE_OK=cells" in r.stdout, r.stdout
    assert "Not KV_FORCE=1" in r.stdout, r.stdout


def test_the_acknowledgement_excuses_that_gate_and_says_it_did(tmp_path,
                                                               monkeypatch):
    g = _script(tmp_path, "import sys\nsys.exit(9)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    monkeypatch.setenv("KV_GATE_OK", "cells")
    r = run_tool("verify", orig, edited)
    assert "GATES ALREADY RED" not in r.stdout, r.stdout
    assert "excused by KV_GATE_OK" in r.stdout, r.stdout
    assert r.returncode in (0, 3), (r.returncode, r.stdout)


def test_a_different_name_excuses_nothing(tmp_path, monkeypatch):
    g = _script(tmp_path, "import sys\nsys.exit(9)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    monkeypatch.setenv("KV_GATE_OK", "some-other-gate")
    r = run_tool("verify", orig, edited)
    assert "GATES ALREADY RED" in r.stdout, r.stdout
    assert r.returncode == 1, (r.returncode, r.stdout)


def test_a_gate_that_prints_a_warning_and_exits_zero_is_passing(tmp_path):
    """Classified on exit status only, never on stderr content."""
    g = _script(tmp_path, "import sys\n"
                          "open(sys.argv[1]).read()\n"
                          "print('DeprecationWarning: old api', "
                          "file=sys.stderr)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES BROKEN" not in r.stdout, r.stdout
    assert "GATES ALREADY RED" not in r.stdout, r.stdout
    assert "1 declared check passed" in r.stdout, r.stdout


def test_a_gate_that_cannot_be_launched_is_listed_and_is_not_a_verdict(
        tmp_path):
    """UNRUNNABLE and no new exit code."""
    _trusted(tmp_path, ["kv-no-such-interpreter-xyz", "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES UNRUNNABLE" in r.stdout, r.stdout
    assert "not a verdict about the document" in r.stdout, r.stdout
    assert r.returncode in (0, 3), (r.returncode, r.stdout)


def test_a_gate_that_times_out_is_broken_and_not_unrunnable(tmp_path):
    """The one genuine refusal of the cross-check round."""
    g = _script(tmp_path, "import time\ntime.sleep(30)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"], timeout=1)
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES UNRUNNABLE" not in r.stdout, r.stdout
    assert "timed out after 1s" in r.stdout, r.stdout
    assert "Raise this gate's `timeout`" in r.stdout, r.stdout



def test_a_gate_that_ignores_the_path_it_is_given_is_refused(tmp_path):
    """The hole the declare-time check could not close, and it is the common
    shape rather than a corner.
    """
    fixed = tmp_path / "tracker.md"
    fixed.write_text("the gate's own idea of what to read\n")
    g = _script(tmp_path, "import sys\n"
                          "open('tracker.md').read()\n"
                          "sys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{original}", "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" in r.stdout, r.stdout
    assert "cells:" in r.stdout, r.stdout
    assert "declared check passed" not in r.stdout, r.stdout


def test_a_blind_gate_is_not_a_verdict_about_the_document(tmp_path):
    """Loud, and deliberately NOT `hard`."""
    g = _script(tmp_path, "import sys\nsys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" in r.stdout, r.stdout
    assert r.returncode in (0, 3), (r.returncode, r.stdout)


def test_a_good_gate_beside_a_blind_one_prints_no_clean_sweep(tmp_path):
    """Two gates, and the mutation audit is what asked for this case."""
    good = _script(tmp_path, "import sys\nopen(sys.argv[1]).read()\n",
                   name="good.py")
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps({"gates": [
        {"name": "reads-it", "argv": [sys.executable, str(good), "{edited}"],
         "timeout": 30},
        {"name": "wrapper", "argv": [sys.executable, str(blind), "{edited}"],
         "timeout": 30}]}))
    assert run_tool("trust", tmp_path / ".killverbosity.gates.json"
                    ).returncode == 0
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" in r.stdout, r.stdout
    assert "wrapper" in r.stdout, r.stdout
    assert "declared check passed" not in r.stdout, r.stdout


def _two_gates(tmp_path, second):
    """One gate that reads {edited}, plus whatever `second` is."""
    good = _script(tmp_path, "import sys\nopen(sys.argv[1]).read()\n",
                   name="good.py")
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps({"gates": [
        {"name": "reads-it", "argv": [sys.executable, str(good), "{edited}"],
         "timeout": 30}, second]}))
    assert run_tool("trust", tmp_path / ".killverbosity.gates.json"
                    ).returncode == 0
    return _pair(tmp_path)


def test_the_blind_block_states_how_much_coverage_is_real(tmp_path):
    """Binance 1 asked for this against a tree declaring five checks."""
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    orig, edited = _two_gates(tmp_path, {
        "name": "wrapper", "argv": [sys.executable, str(blind), "{edited}"],
        "timeout": 30})
    r = run_tool("verify", orig, edited)
    assert "1 of 2 declared checks read the edit." in r.stdout, r.stdout
    assert "declared check passed" not in r.stdout, r.stdout


def test_one_blind_gate_alone_says_none_of_them_read_it(tmp_path):
    """The control for the numerator. `1 of 2` is satisfied by a ratio that
    counts gates rather than READING gates, and with one gate that mistake
    prints `1 of 1` -- the reassuring direction, on the tree with no coverage
    at all."""
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    _trusted(tmp_path, [sys.executable, str(blind), "{edited}"], name="only")
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "0 of 1 declared check read the edit." in r.stdout, r.stdout


def test_a_gate_the_probe_never_reached_is_not_counted_as_reading(tmp_path):
    """The denominator is the PROBED population, not every declared gate."""
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    red = _script(tmp_path, "import sys\nsys.exit(9)\n", name="red.py")
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / ".killverbosity.gates.json").write_text(json.dumps({"gates": [
        {"name": "wrapper", "argv": [sys.executable, str(blind), "{edited}"],
         "timeout": 30},
        {"name": "was-red", "argv": [sys.executable, str(red), "{edited}"],
         "timeout": 30}]}))
    assert run_tool("trust", tmp_path / ".killverbosity.gates.json"
                    ).returncode == 0
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert ("0 of the 1 check that reached the probe read the edit; the other "
            "1 of this tree's 2 never reached it") in r.stdout, r.stdout
    assert "0 of 2" not in r.stdout, r.stdout


def test_the_excused_line_carries_the_ratio_too(tmp_path, monkeypatch):
    """Excusing a blind gate by name says the reader knows about that one. It
    does not tell them how much of the declared coverage survives it, and that
    number is the same number whether the gate is excused or not."""
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    orig, edited = _two_gates(tmp_path, {
        "name": "wrapper", "argv": [sys.executable, str(blind), "{edited}"],
        "timeout": 30})
    monkeypatch.setenv("KV_GATE_BLIND_OK", "wrapper")
    r = run_tool("verify", orig, edited)
    assert "excused by KV_GATE_BLIND_OK" in r.stdout, r.stdout
    assert "1 of 2 declared checks read the edit." in r.stdout, r.stdout


def test_the_blind_remedy_names_the_symlink_trap(tmp_path):
    """A DECLARED LIMIT, asserted, or the next reader reads it as covered."""
    blind = _script(tmp_path, "import sys\nsys.exit(0)\n", name="blind.py")
    _trusted(tmp_path, [sys.executable, str(blind), "{edited}"], name="only")
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "CLONE the directory holding the check" in r.stdout, r.stdout
    assert "resolves back out" in r.stdout, r.stdout


def test_a_refused_declaration_says_the_verdict_does_not_cover_it(tmp_path):
    """The refusal goes to stderr and the verdict goes to stdout."""
    _gate(tmp_path, [sys.executable, "-c", READS, "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "no declared check ran" in r.stderr, r.stderr
    assert "says nothing about this tree's own checks" in r.stderr, r.stderr


def test_a_tree_that_declares_nothing_says_nothing_about_gates(tmp_path):
    """The control for the sentence above, and it is what keeps it narrow."""
    (tmp_path / ".killverbosity.json").write_text("{}")
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "no declared check ran" not in r.stderr, r.stderr


def test_accept_refuses_a_blind_gate_where_verify_reads_on(tmp_path):
    """The two commands are different questions, and the peer who owns such a
    tree is who settled it.
    """
    g = _script(tmp_path, "import sys\nsys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _ready(tmp_path)
    assert run_tool("verify", orig, edited).returncode in (0, 3)
    r = run_tool("accept", orig, edited)
    assert r.returncode == 1, (r.returncode, r.stdout + r.stderr)
    assert "never read the edit" in r.stderr or "have never judged this edit" \
        in r.stderr, r.stderr
    assert "KV_GATE_BLIND_OK=cells" in r.stderr, r.stderr
    assert orig.read_text() == DOC, "accept copied anyway"


def test_the_blind_acknowledgement_is_its_own_variable(tmp_path, monkeypatch):
    """NOT `KV_GATE_OK`, and the distinction is the point."""
    g = _script(tmp_path, "import sys\nsys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _ready(tmp_path)
    monkeypatch.setenv("KV_GATE_BLIND_OK", "cells")
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" not in r.stdout, r.stdout
    assert "excused by KV_GATE_BLIND_OK" in r.stdout, r.stdout
    assert run_tool("accept", orig, edited).returncode in (0, 3)


def test_the_document_acknowledgement_does_not_excuse_a_blind_gate(tmp_path,
                                                                   monkeypatch):
    """The control, and it is what makes the two variables worth having."""
    g = _script(tmp_path, "import sys\nsys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _ready(tmp_path)
    monkeypatch.setenv("KV_GATE_OK", "cells")
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" in r.stdout, r.stdout
    assert run_tool("accept", orig, edited).returncode == 1


def test_forcing_past_a_blind_gate_records_what_was_overruled(tmp_path,
                                                              monkeypatch):
    """KV_FORCE takes the output as it is, and says what it took it past."""
    g = _script(tmp_path, "import sys\nsys.exit(0)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _ready(tmp_path)
    monkeypatch.setenv("KV_FORCE", "1")
    r = run_tool("accept", orig, edited)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "KV_FORCE overruled" in r.stdout, r.stdout
    assert "never read the edit" in r.stdout and "cells" in r.stdout, r.stdout


def test_accept_is_unaffected_when_every_gate_reads_the_edit(tmp_path):
    """The other control. A refusal that fires on a correct run is one the
    first person it annoys switches off."""
    _trusted(tmp_path, [sys.executable, "-c", READS, "{edited}"])
    orig, edited = _ready(tmp_path)
    r = run_tool("accept", orig, edited)
    assert r.returncode in (0, 3), (r.returncode, r.stdout + r.stderr)
    assert "KV_GATE_BLIND_OK" not in r.stderr, r.stderr


def test_a_gate_that_does_read_the_file_is_not_called_blind(tmp_path):
    """The control, and it is what stops the probe refusing every gate."""
    _trusted(tmp_path, [sys.executable, "-c", READS, "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES NOT READING THE EDIT" not in r.stdout, r.stdout
    assert f"1 declared check passed (cells via {sys.executable})" in r.stdout, r.stdout


def test_the_probe_is_skipped_for_a_gate_that_already_has_a_verdict(tmp_path):
    """A gate that is red needs no probe: a blind gate cannot be red."""
    g = _script(tmp_path, "import sys\n"
                          "open('RUNS','a').write('x')\n"
                          "sys.exit(7)\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "GATES ALREADY RED" in r.stdout, r.stdout
    assert (tmp_path / "RUNS").read_text() == "xx", \
        (tmp_path / "RUNS").read_text()



def test_the_gate_never_learns_the_sidecar_s_name(tmp_path):
    """Fixed BY CONSTRUCTION for a gate that reads its own arguments."""
    g = _script(tmp_path, "import sys\n"
                          "open(sys.argv[1]).read()\n"
                          "open('SAW','a').write(sys.argv[1] + '\\n')\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    run_tool("verify", orig, edited)
    saw = (tmp_path / "SAW").read_text().split()
    assert len(saw) == 2, saw
    assert not any("note.kv.md" in s for s in saw), saw
    assert all(s.endswith("note.md") for s in saw), saw
    assert all(os.path.isabs(s) and "kv-gates-" in s for s in saw), saw
    assert saw[0] != saw[1], saw


def test_an_argument_carrying_shell_metacharacters_stays_one_argument(
        tmp_path):
    """A declared argv list, never a shell string."""
    g = _script(tmp_path, "import sys\n"
                          "open(sys.argv[2]).read()\n"
                          "open('ARGS','w').write(repr(sys.argv[1:]))\n")
    _trusted(tmp_path, [sys.executable, str(g), "a & b ; c", "{edited}"])
    orig, edited = _pair(tmp_path)
    run_tool("verify", orig, edited)
    got = ast.literal_eval((tmp_path / "ARGS").read_text())
    assert got[0] == "a & b ; c", got
    assert len(got) == 2, got


def test_the_original_is_passed_too_so_a_gate_can_compare(tmp_path):
    g = _script(tmp_path, "import sys\n"
                          "a = open(sys.argv[1]).read()\n"
                          "b = open(sys.argv[2]).read()\n"
                          "open('BOTH','w').write('same' if a == b else 'diff')\n")
    _trusted(tmp_path, [sys.executable, str(g), "{original}", "{edited}"])
    orig, edited = _pair(tmp_path)
    run_tool("verify", orig, edited)
    assert (tmp_path / "BOTH").read_text() == "diff"


def test_the_sidecar_is_named_in_the_environment_for_tree_walking_gates(
        tmp_path):
    """The DECLARED LIMIT, asserted rather than left as prose."""
    g = _script(tmp_path, "import os, sys\n"
                          "open(sys.argv[1]).read()\n"
                          "open('ENV','w').write(os.environ.get("
                          "'KV_SIDECAR', 'MISSING'))\n")
    _trusted(tmp_path, [sys.executable, str(g), "{edited}"])
    orig, edited = _pair(tmp_path)
    run_tool("verify", orig, edited)
    assert (tmp_path / "ENV").read_text().endswith("note.kv.md"), \
        (tmp_path / "ENV").read_text()


def test_the_declaration_is_read_beside_the_winning_config_only(tmp_path):
    """One walk, one winner."""
    deep = tmp_path / "docs"
    deep.mkdir()
    _trusted(tmp_path, [sys.executable, "-c",
                        "import sys; open(sys.argv[1]).read(); "
                        "open('ROOT_RAN','w').write('x')", "{edited}"])
    (deep / ".killverbosity.json").write_text("{}")
    (deep / "note.md").write_text(DOC)
    (deep / "note.kv.md").write_text(SHORT)
    r = run_tool("verify", deep / "note.md", deep / "note.kv.md")
    assert str(deep / ".killverbosity.json") in r.stderr, r.stderr
    assert not (tmp_path / "ROOT_RAN").exists(), \
        "a shadowed config's gates ran"
    orig, edited = _pair(tmp_path)
    run_tool("verify", orig, edited)
    assert (tmp_path / "ROOT_RAN").exists(), "the winning config's gates "\
        "did not run either"


def test_no_declaration_means_no_mention_of_gates_at_all(tmp_path):
    (tmp_path / ".killverbosity.json").write_text("{}")
    orig, edited = _pair(tmp_path)
    r = run_tool("verify", orig, edited)
    assert "gates" not in r.stdout.lower(), r.stdout
    assert "GATES" not in r.stderr, r.stderr



def test_resolved_falls_back_to_uvx_when_bare_ruff_is_missing(monkeypatch):
    monkeypatch.setattr(
        gates.shutil, "which",
        lambda name, path=None: "/fake/bin/uvx" if name == "uvx" else None)
    assert gates.resolved("ruff") == ["/fake/bin/uvx", "ruff"]


def test_resolved_stays_unrunnable_when_uvx_is_also_missing(monkeypatch):
    monkeypatch.setattr(gates.shutil, "which", lambda name, path=None: None)
    assert gates.resolved("ruff") == ["ruff"]


def test_resolved_never_touches_uvx_for_a_name_that_is_not_ruff(monkeypatch):
    monkeypatch.setattr(
        gates.shutil, "which",
        lambda name, path=None: "/fake/bin/uvx" if name == "uvx" else None)
    assert gates.resolved("make") == ["make"]


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_the_lint_gate_actually_spawns_uvx_ruff_when_bare_ruff_is_missing(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        gates.shutil, "which",
        lambda name, path=None: "/fake/bin/uvx" if name == "uvx" else None)
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(gates.spawn, "run_tree", fake_run)
    orig, edited = _pair(tmp_path)
    gate = {"name": "lint", "argv": ["ruff", "check", "{edited}"],
            "timeout": 30}
    status, said = gates._run_one(gate, tmp_path, orig, edited, None)
    assert status == gates.OK, said
    assert captured["argv"][:2] == ["/fake/bin/uvx", "ruff"], captured["argv"]


def test_the_lint_gate_stays_unrunnable_when_neither_ruff_nor_uvx_exist(
        tmp_path, monkeypatch):
    monkeypatch.setattr(gates.shutil, "which", lambda name, path=None: None)

    def fake_run(argv, **kw):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(gates.spawn, "run_tree", fake_run)
    orig, edited = _pair(tmp_path)
    gate = {"name": "lint", "argv": ["ruff", "check", "{edited}"],
            "timeout": 30}
    status, said = gates._run_one(gate, tmp_path, orig, edited, None)
    assert status == gates.UNRUNNABLE, said
    assert "could not be launched" in said, said
