"""`run --no-agents`: everything except the specialists."""

import json
import stat
import sys

from conftest import run_tool
from killverbosity.runrecord import run_record_path

DOC = ("# Notes\n\n| id | state |\n|---|---|\n| C1 | done |\n\n"
       "This paragraph is, in point of fact, considerably longer than it "
       "strictly needs to be, and it leverages a number of things.\n")


def _doc(tmp_path):
    (tmp_path / ".killverbosity.json").write_text("{}")
    (tmp_path / "note.md").write_text(DOC)
    return tmp_path / "note.md"


def _script(tmp_path, body, name):
    p = tmp_path / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _gates(tmp_path, *gates):
    (tmp_path / ".killverbosity.gates.json").write_text(
        json.dumps({"gates": list(gates)}))
    assert run_tool("trust", tmp_path / ".killverbosity.gates.json"
                    ).returncode == 0


def _blind_gate(tmp_path):
    b = _script(tmp_path, "import sys\nsys.exit(0)\n", "blind.py")
    _gates(tmp_path, {"name": "wrapper",
                      "argv": [sys.executable, str(b), "{edited}"],
                      "timeout": 30})


def test_no_agents_writes_a_record_and_leaves_the_text_alone(tmp_path):
    src = _doc(tmp_path)
    r = run_tool("run", src, "--no-agents")
    assert r.returncode in (0, 3), (r.returncode, r.stdout, r.stderr)
    out = tmp_path / "note.kv.md"
    assert out.read_text() == DOC, "the output is the input, byte for byte"
    rec = json.loads(run_record_path(out).read_text())
    assert rec["no_agents"] is True, rec


def test_nothing_is_dispatched(tmp_path):
    """The control, and the only one that can say the flag WORKS."""
    src = _doc(tmp_path)
    r = run_tool("run", src, "--no-agents", "--agent", "agy")
    assert r.returncode in (0, 3), (r.returncode, r.stdout, r.stderr)
    assert (tmp_path / "note.kv.md").read_text() == DOC
    said = r.stdout + r.stderr
    for bad in ("could not be launched", "asking once more", "never edited",
                "unusable", "jobs failed"):
        assert bad not in said, (bad, said)
    assert "--no-agents sends none" in said, said
    assert "against agy" not in said, said


def test_no_journal_is_written(tmp_path):
    """A journal holds answers already paid for. Banking an empty one would
    make the next real run replay `no edits` as a bought answer."""
    src = _doc(tmp_path)
    run_tool("run", src, "--no-agents")
    assert not list(tmp_path.glob("*.kvjournal")), list(tmp_path.iterdir())


def test_verify_says_the_pass_covers_no_edit(tmp_path):
    src = _doc(tmp_path)
    run_tool("run", src, "--no-agents")
    r = run_tool("verify", src, tmp_path / "note.kv.md")
    assert "called no specialist" in r.stdout, r.stdout
    assert "says nothing about any edit" in r.stdout, r.stdout


def test_an_ordinary_record_says_none_of_that(tmp_path):
    """The control for the notice. A line that prints on every run is one the
    reader stops seeing, and this one has to mean something when it appears."""
    from killverbosity.runrecord import write_run_record
    src = _doc(tmp_path)
    out = tmp_path / "note.kv.md"
    out.write_text(DOC)
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("verify", src, out)
    assert "called no specialist" not in r.stdout, r.stdout


def test_the_accept_blind_refusal_is_now_reachable_without_a_dispatch(tmp_path):
    """The whole point. This is the case the peer could not run."""
    src = _doc(tmp_path)
    _blind_gate(tmp_path)
    run_tool("run", src, "--no-agents")
    before = src.read_text()
    r = run_tool("accept", src)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "not accepted" in r.stderr, r.stderr
    assert "wrapper" in r.stderr, r.stderr
    assert src.read_text() == before, "the input was replaced by a refusal"


def test_a_clean_tree_reaches_the_last_refusal_and_keeps_the_file(tmp_path):
    """With every gate happy, `accept` still refuses -- and it refuses for the
    right reason, which is the assertion that matters.
    """
    src = _doc(tmp_path)
    good = _script(tmp_path, "import sys\nopen(sys.argv[1]).read()\n", "g.py")
    _gates(tmp_path, {"name": "reads-it",
                      "argv": [sys.executable, str(good), "{edited}"],
                      "timeout": 30})
    run_tool("run", src, "--no-agents")
    r = run_tool("accept", src)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "called no specialist" in r.stderr, r.stderr
    assert "nothing here to accept" in r.stderr, r.stderr
    assert src.read_text() == DOC
    assert (tmp_path / "note.kv.md").exists(), "a refusal cleared the sidecar"


def test_the_no_agents_refusal_comes_LAST(tmp_path):
    """The control, and the whole reason the new refusal sits where it sits."""
    src = _doc(tmp_path)
    _blind_gate(tmp_path)
    run_tool("run", src, "--no-agents")
    r = run_tool("accept", src)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "wrapper" in r.stderr, r.stderr
    assert "never read the edit" in r.stderr or "does not exist" in r.stderr, \
        r.stderr
    assert "nothing here to accept" not in r.stderr, \
        "the no-agents refusal shadowed the gate refusal it exists to expose"


def test_forcing_past_it_copies_the_file_and_says_what_it_forced(tmp_path):
    src = _doc(tmp_path)
    run_tool("run", src, "--no-agents")
    r = run_tool("accept", src, force=True)
    assert src.read_text() == DOC
    assert "nothing to accept" in r.stdout + r.stderr, (r.stdout, r.stderr)
