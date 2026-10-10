"""`refuse` is a NOTICE and nothing else: it prints one line and gets out of way."""
import json
from pathlib import Path

import pytest

from conftest import run_tool

DOC = "# Title\n\nThis is a document that is, in point of fact, quite verbose.\n"

REMOVED_SAMPLE = """\
# --- run, whole-tree declaration ---
safe mode: docs/note.md matched <whole tree> in <tree>/.killverbosity.json
kill-verbosity: <tree>/.killverbosity.json declares this tree — the trackers here are parsed line by line
kill-verbosity: SAFE MODE — this tree is declared as another tool's state, so the run is DOWNGRADED, not refused. Running: `noise`, `prose`, `summary`. Off: `structure`, so no section is moved, and reordering is off. What this GUARANTEES: no section moves, and no markdown link or code span is split across a newline (the measured hazard). What it does NOT guarantee: absolute line numbers. Paragraphs are re-wrapped, so lines shift — measured, 120 in and 129 out on a real tracker. If your consumer reads this file BY LINE NUMBER, safe mode is not enough: add `"freeze": {"paths": [...], "lines": [...]}` to the declaration, which blanks those lines out of the editable set instead. Writing to <tmp>; docs/note.md is not written by this command. KV_FORCE=1 runs the full pipeline instead.
kill-verbosity: <tree>/.killverbosity.json — specialists noise,prose,summary
no wrap margin found, so the lines go to the specialists as written
read as prose  ·  build <b>
config: <tree>/.killverbosity.json
kill-verbosity: SAFE MODE found nothing it can safely change in this file - noise: no shape it owns fired in this file; prose: no shape it owns fired in this file; summary: no shape it owns fired in this file. The full pipeline may still have work here (`structure` moves sections, which safe mode never does); KV_FORCE=1 runs it.

# --- plan, whole-tree declaration ---
refused: docs/note.md matched <whole tree> in <tree>/.killverbosity.json — this is `plan`, which writes nothing, so it runs
kill-verbosity: <tree>/.killverbosity.json refuses this tree — the trackers here are parsed line by line
To refuse only the hazardous files, give refuse the object form: {"refuse": {"paths": ["tracker*.md"], "reason": "..."}} — everything else then runs. An empty `.killverbosity.json` (`{}`) in a subdirectory does the same for that subtree, since the nearest one wins. One hazard per declaration: a second one wants a nested `.killverbosity.json` with its own reason, not a longer reason here. (KV_FORCE=1 runs here anyway, parsed files included.)
kill-verbosity: run and accept are refused for this file; plan is not. Nothing below can be applied to docs/note.md — take it to whatever writes this file, or to the tool that owns it.
no wrap margin found, so the lines go to the specialists as written
config: <tree>/.killverbosity.json

# --- plan, scoped declaration ---
refused: state/ledger.md matched state/*.md in <tree>/.killverbosity.json — this is `plan`, which writes nothing, so it runs
kill-verbosity: <tree>/.killverbosity.json refuses state/*.md — the trackers here are parsed line by line
KV_FORCE=1 runs on this one anyway; the tree's owner declared this, so scoping it is theirs to change and not the reader's.
This file only: every file in this tree that matches no declared pattern runs normally.
kill-verbosity: run and accept are refused for this file; plan is not. Nothing below can be applied to state/ledger.md — take it to whatever writes this file, or to the tool that owns it.
no wrap margin found, so the lines go to the specialists as written
config: <tree>/.killverbosity.json

# --- accept, scoped declaration ---
safe mode: state/ledger.md matched state/*.md in <tree>/.killverbosity.json
kill-verbosity: <tree>/.killverbosity.json declares state/*.md — the trackers here are parsed line by line
kill-verbosity: SAFE MODE — `state/*.md` is declared as another tool's state, so the run is DOWNGRADED, not refused. Running: `noise`, `prose`, `summary`. Off: `structure`, so no section is moved, and reordering is off. What this GUARANTEES: no section moves, and no markdown link or code span is split across a newline (the measured hazard). What it does NOT guarantee: absolute line numbers. Paragraphs are re-wrapped, so lines shift — measured, 120 in and 129 out on a real tracker. If your consumer reads this file BY LINE NUMBER, safe mode is not enough: add `"freeze": {"paths": [...], "lines": [...]}` to the declaration, which blanks those lines out of the editable set instead. KV_FORCE=1 runs the full pipeline instead.
kill-verbosity: <tree>/.killverbosity.json — specialists noise,prose,summary
kill-verbosity: no run output at state/ledger.kv.md. Run it first.
"""

REMOVED = (
    "safe mode",
    "SAFE MODE",
    "refused: ",
    "DOWNGRADED, not refused",
    "run and accept are refused for this file",
    "To refuse only the hazardous files",
    "KV_FORCE=1 runs on this one anyway",
    "matches no declared pattern runs normally",
    "KV_FORCE=1 runs the full pipeline",
    "is not written by this command",
    "— specialists ",
)

NOTE = "A note, not a gate: nothing here is refused, restricted or relocated."


def _no_removed_vocabulary(stderr, where=""):
    """Every string the removed mechanism used to print, absent."""
    for dead in REMOVED:
        assert dead not in stderr, (where, dead, stderr)


def _notice(stderr, target: Path, matched: str, config: Path, reason: str,
            where=""):
    """The whole notice, in both directions."""
    first = stderr.splitlines()[0] if stderr else ""
    assert first.startswith(f"declared: {target} matched {matched} in "
                            f"{config} — {reason}."), (where, first)
    assert NOTE in first, (where, first)
    assert f"`accept` keeps a numbered copy of {target.name} before it writes." \
        in first, (where, first)
    _no_removed_vocabulary(stderr, where)


def _tree(tmp_path):
    """A whole-tree declaration: the bare-string form of `refuse`."""
    (tmp_path / ".killverbosity.json").write_text(
        json.dumps({"refuse": "the trackers here are parsed line by line"}))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(DOC)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ledger.md").write_text(DOC)
    return tmp_path


def _scoped(tmp_path):
    """The object form: only `state/*.md` is named."""
    (tmp_path / ".killverbosity.json").write_text(json.dumps(
        {"refuse": {"paths": ["state/*.md"],
                    "reason": "the trackers here are parsed line by line"}}))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(DOC)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ledger.md").write_text(DOC)
    return tmp_path


REASON = "the trackers here are parsed line by line"


def test_the_declaration_prints_the_notice_and_the_run_completes(tmp_path):
    """The whole new contract on the command the old one stopped: `run`."""
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"

    r = run_tool("run", doc, "--no-agents")
    _notice(r.stderr, doc, "<whole tree>", root / ".killverbosity.json",
            REASON, where="run")
    assert r.returncode == 0, r.stderr + r.stdout


def test_the_declared_run_is_not_relocated_and_not_restricted(tmp_path):
    """INVERTED from the three tests that pinned the forced `-o`."""
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"

    r = run_tool("run", doc, "--no-agents")
    assert r.returncode == 0, r.stderr + r.stdout
    assert (root / "docs" / "note.kv.md").is_file(), \
        f"the sidecar did not land beside the input:\n{r.stderr}"
    assert (root / "docs" / "note.orig.md").is_file(), \
        f"the baseline did not land beside the input:\n{r.stderr}"
    assert "Writing to " not in r.stderr, \
        f"the output is still being relocated:\n{r.stderr}"
    assert "structure" in r.stderr, \
        f"`structure` was not dispatched, so the set is still cut:\n{r.stderr}"
    _no_removed_vocabulary(r.stderr, "run")


def test_an_undeclared_tree_gets_the_same_files(tmp_path):
    """CONTROL for the test above: this is what "as in any other tree" means."""
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "note.md"
    doc.write_text(DOC)

    r = run_tool("run", doc, "--no-agents")
    assert r.returncode == 0, r.stderr + r.stdout
    assert (tmp_path / "docs" / "note.kv.md").is_file(), r.stderr
    assert (tmp_path / "docs" / "note.orig.md").is_file(), r.stderr
    assert "structure" in r.stderr, r.stderr


def test_no_notice_at_all_when_nothing_is_declared(tmp_path):
    """CONTROL. The notice must be a consequence of the DECLARATION."""
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "note.md"
    doc.write_text(DOC)

    r = run_tool("plan", doc)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "declared:" not in r.stderr, r.stderr
    assert NOTE not in r.stderr, r.stderr
    assert "keeps a numbered copy" not in r.stderr, r.stderr
    _no_removed_vocabulary(r.stderr, "undeclared plan")


def test_plan_is_unaffected_and_still_produces_the_work_list(tmp_path):
    """`plan` was never downgraded and still is not -- but it used to be told
    so in the vocabulary of an exemption from a gate ("this is `plan`, which
    writes nothing, so it runs"). There is no gate to be exempt from now, so
    the notice reads the same on every command and `plan` is held to the same
    line as `run`.
    """
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"

    r = run_tool("plan", doc)
    _notice(r.stderr, doc, "<whole tree>", root / ".killverbosity.json",
            REASON, where="plan")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "shapes:" in r.stdout, r.stdout


def test_verify_is_unaffected_and_still_reaches_a_verdict(tmp_path):
    """`verify` writes nothing and was already exempt; it must stay exempt, and
    it must still be given the declaration so `freeze` can be honoured.
    """
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"
    edited = root / "docs" / "note.kv.md"
    edited.write_text("# Title\n\nThis is short.\n")

    r = run_tool("verify", doc, edited)
    _notice(r.stderr, doc, "<whole tree>", root / ".killverbosity.json",
            REASON, where="verify")
    assert any(v in r.stdout for v in ("PASS", "REVIEW", "FAIL")), r.stdout


def test_a_scoped_declaration_names_the_pattern_and_not_the_tree(tmp_path):
    """The scope arithmetic, untouched by the ruling and still worth pinning:
    the object form claims its globs and nothing else.
    """
    root = _scoped(tmp_path)
    ledger = root / "state" / "ledger.md"

    r = run_tool("run", ledger, "--no-agents")
    _notice(r.stderr, ledger, "state/*.md", root / ".killverbosity.json",
            REASON, where="scoped run")
    assert "this tree" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stderr + r.stdout


def test_a_scoped_declaration_is_silent_on_a_file_it_does_not_name(tmp_path):
    """CONTROL for the scope. Without it, a matcher that fired on everything
    passes the test above."""
    r = run_tool("plan", _scoped(tmp_path) / "docs" / "note.md")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "declared:" not in r.stderr, r.stderr
    _no_removed_vocabulary(r.stderr, "scoped, unnamed file")


def test_the_whole_tree_form_still_claims_the_whole_tree(tmp_path):
    """The other half of the scope pair: a bare string means the tree."""
    root = _tree(tmp_path)
    r = run_tool("run", root / "state" / "ledger.md", "--no-agents")
    assert "matched <whole tree>" in r.stderr, r.stderr
    assert r.returncode == 0, r.stderr + r.stdout


def test_the_nearest_killverbosity_json_wins(tmp_path):
    """The one claim that survives from the deleted remedy test."""
    root = _tree(tmp_path)
    (root / "docs" / ".killverbosity.json").write_text("{}")

    near = run_tool("plan", root / "docs" / "note.md")
    assert near.returncode == 0, near.stderr + near.stdout
    assert "declared:" not in near.stderr, near.stderr

    far = run_tool("plan", root / "state" / "ledger.md")
    assert far.returncode == 0, far.stderr + far.stdout
    assert "declared:" in far.stderr, far.stderr
    assert "matched <whole tree>" in far.stderr, far.stderr


def test_accept_reaches_its_own_precondition_and_not_a_declaration_refusal(
        tmp_path):
    """`accept` is the command that replaces the original -- the one the
    declaration used to stop outright, and then to decline.
    """
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"

    r = run_tool("accept", doc)
    _notice(r.stderr, doc, "<whole tree>", root / ".killverbosity.json",
            REASON, where="accept")
    assert r.returncode == 2, r.stderr
    assert "no run output" in r.stderr, r.stderr
    assert doc.read_text() == DOC, "accept wrote a file it had nothing for"



_CLOCK = ("Tail:", "this run may take up to")


def _steady(err):
    """Every stderr line whose content cannot move between two identical runs."""
    return [ln for ln in err.splitlines()
            if not ln.lstrip().startswith(_CLOCK)]


def _declared_line(err):
    """The `declared:` line, wherever it sits."""
    found = [ln for ln in err.splitlines() if ln.startswith("declared: ")]
    assert len(found) == 1, f"expected one declared: line, got {len(found)}:\n{err}"
    return found[0]


def test_KV_FORCE_is_no_longer_part_of_the_declaration(tmp_path):
    """The ruling's own words: no `KV_FORCE` requirement, in either direction."""
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"

    plain = run_tool("run", doc, "--no-agents")
    assert plain.returncode == 0, plain.stderr + plain.stdout
    for gen in ("note.kv.md", "note.kv.md.kvrun", "note.orig.md"):
        (root / "docs" / gen).unlink(missing_ok=True)

    forced = run_tool("run", doc, "--no-agents", force=True)
    assert forced.returncode == 0, forced.stderr + forced.stdout

    said = _declared_line(plain.stderr), _declared_line(forced.stderr)
    assert said[0] == said[1], \
        f"KV_FORCE changed the notice:\n{said[0]}\n---\n{said[1]}"

    assert _steady(plain.stderr) == _steady(forced.stderr), \
        f"KV_FORCE changed the report:\n{plain.stderr}\n---\n{forced.stderr}"
    said = forced.stderr.replace(str(root), "<root>")
    named = [ln for ln in said.splitlines() if "KV_FORCE" in ln]
    assert not named, f"the run named the flag: {named}"

    assert (root / "docs" / "note.kv.md").is_file(), forced.stderr
    _no_removed_vocabulary(forced.stderr, "KV_FORCE run")


def test_a_malformed_scoped_refusal_says_which_half_is_wrong(tmp_path):
    """UNCHANGED by the ruling, and the reason it is not a contradiction of it."""
    (tmp_path / ".killverbosity.json").write_text(
        json.dumps({"refuse": {"paths": [], "reason": "x"}}))
    (tmp_path / "note.md").write_text(DOC)

    r = run_tool("run", tmp_path / "note.md")
    assert r.returncode == 2, r.stderr
    assert "refuse.paths must be a non-empty list" in r.stderr, r.stderr
    _no_removed_vocabulary(r.stderr, "malformed")


def test_freeze_still_parses_and_still_holds_beside_a_refuse(tmp_path):
    """`freeze` is untouched and is a DIFFERENT thing: it holds TEXT."""
    root = _tree(tmp_path)
    doc = root / "docs" / "note.md"
    doc.write_text(DOC + "\n| a | b |\n| - | - |\n")
    (root / ".killverbosity.json").write_text(json.dumps(
        {"refuse": REASON,
         "freeze": {"paths": ["docs/note.md"],
                    "lines": [r"^\| "],
                    "reason": "the table rows are read by line"}}))

    r = run_tool("run", doc, "--no-agents")
    assert r.returncode == 0, r.stderr + r.stdout
    _notice(r.stderr, doc, "<whole tree>", root / ".killverbosity.json",
            REASON, where="refuse+freeze")
    assert "frozen: 2 of" in r.stderr, r.stderr
    assert "the table rows are read by line" in r.stderr, r.stderr


def test_every_removed_needle_was_really_printed_by_the_removed_mechanism():
    """The non-vacuity guard, and the reason this file has a frozen corpus."""
    missing = [n for n in REMOVED if n not in REMOVED_SAMPLE]
    assert not missing, (
        f"these strings appear nowhere in the removed mechanism's own output, "
        f"so every `assert needle not in stderr` using them is vacuous: "
        f"{missing}")
    assert len(REMOVED) == 11, REMOVED


def test_the_helper_refuses_the_removed_mechanisms_output():
    """CONTROL for `_no_removed_vocabulary` itself."""
    with pytest.raises(AssertionError):
        _no_removed_vocabulary(REMOVED_SAMPLE, "the removed mechanism")
    _no_removed_vocabulary(
        "declared: docs/note.md matched <whole tree> in /t/.killverbosity.json "
        "— a reason. " + NOTE + " `accept` keeps a numbered copy of "
        "note.md before it writes.\n", "today's notice")
