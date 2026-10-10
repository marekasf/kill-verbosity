"""`freeze`: the hazard is a LINE, and `refuse` could only name a file."""
import json

from conftest import REPO, run_canned, run_tool
from killverbosity.runrecord import write_run_record

ROW = "| C1 | done | 2026-09-01 | owner | ref | note |"
DOC = ("# Title\n\nThis is a document that is, in point of fact, quite "
       "verbose.\n\n| id | state | when | who | ref | note |\n"
       "|---|---|---|---|---|---|\n" + ROW + "\n")


def _tree(tmp_path, **over):
    decl = {"paths": ["*.md"], "lines": [r"^\s*\|"],
            "reason": "rows are split on | and must keep exactly 6 cells"}
    decl.update(over)
    (tmp_path / ".killverbosity.json").write_text(
        json.dumps({"freeze": decl}))
    (tmp_path / "note.md").write_text(DOC)
    return tmp_path / "note.md"


def test_a_freeze_holds_the_declared_lines_and_the_rest_runs(tmp_path):
    r = run_tool("plan", _tree(tmp_path))
    assert r.returncode == 0, r.stderr + r.stdout
    assert "frozen: 3 of " in r.stderr, r.stderr
    assert "the rest runs normally" in r.stderr
    assert "byte-identical" in r.stderr
    assert "must keep exactly 6 cells" in r.stderr
    assert "shapes:" in r.stdout, r.stdout


def test_the_table_caveat_stops_naming_rows_the_freeze_holds(tmp_path):
    r = run_tool("plan", _tree(tmp_path))
    assert "table row" not in r.stdout, r.stdout

    (tmp_path / ".killverbosity.json").write_text("{}")
    r2 = run_tool("plan", tmp_path / "note.md")
    assert "2 table rows:" in r2.stdout, r2.stdout


def test_a_freeze_that_matches_no_line_says_so_loudly(tmp_path):
    r = run_tool("plan", _tree(tmp_path, lines=[r"^NOTHING MATCHES THIS$"]))
    assert r.returncode == 0, r.stderr
    assert "freeze matched nothing" in r.stderr, r.stderr
    assert "NOTHING in this file is protected" in r.stderr
    assert "the rest runs normally" not in r.stderr


def test_a_freeze_outside_its_paths_is_not_applied(tmp_path):
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "note.md").write_text(DOC)
    _tree(tmp_path, paths=["state/*.md"])
    r = run_tool("plan", tmp_path / "other" / "note.md")
    assert r.returncode == 0, r.stderr
    assert "frozen:" not in r.stderr
    assert "2 table rows:" in r.stdout, r.stdout


def test_a_malformed_freeze_names_the_half_that_is_wrong(tmp_path):
    (tmp_path / "note.md").write_text(DOC)
    for decl, needle in (
            ({"reason": "x"}, "freeze.lines must be a non-empty list"),
            ({"lines": [], "reason": "x"}, "freeze.lines must be a non-empty"),
            ({"lines": [r"^\s*("], "reason": "x"}, "is not a regex"),
            ({"lines": [r"^\|"]}, "freeze.reason must be"),
            ({"lines": [r"^\|"], "reason": "x", "linez": []},
             "keys this build does not know"),
            ("a sentence", "freeze must be an object")):
        (tmp_path / ".killverbosity.json").write_text(
            json.dumps({"freeze": decl}))
        r = run_tool("plan", tmp_path / "note.md")
        assert r.returncode == 2, (decl, r.stderr)
        assert needle in r.stderr, (decl, r.stderr)



def _pair(tmp_path, edited_doc):
    _tree(tmp_path)
    (tmp_path / "note.kv.md").write_text(edited_doc)
    return tmp_path / "note.md", tmp_path / "note.kv.md"


REWORDED = "| C1 | complete | 2026-09-01 | owner | ref | note |"


def test_verify_fails_when_a_frozen_row_was_reworded(tmp_path):
    r = run_tool("verify", *_pair(tmp_path, DOC.replace(ROW, REWORDED)))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FROZEN LINES CHANGED" in r.stdout, r.stdout
    assert "TABLE BROKEN" not in r.stdout, r.stdout
    assert "C1 | done" in r.stdout
    assert "must keep exactly 6 cells" in r.stdout


def test_verify_does_not_fire_when_only_the_prose_moved(tmp_path):
    ok = DOC.replace("This is a document that is, in point of fact, quite "
                     "verbose.", "This document is verbose.")
    r = run_tool("verify", *_pair(tmp_path, ok))
    assert "FROZEN LINES CHANGED" not in r.stdout, r.stdout


def test_verify_compares_the_row_and_not_its_line_number(tmp_path):
    moved = DOC.replace("# Title\n", "# Title\n\nAn inserted paragraph.\n")
    r = run_tool("verify", *_pair(tmp_path, moved))
    assert "FROZEN LINES CHANGED" not in r.stdout, r.stdout


def test_accept_refuses_a_frozen_row_that_changed(tmp_path):
    """The peer's actual ask, executed rather than reasoned about."""
    src, out = _pair(tmp_path, DOC.replace(ROW, REWORDED))
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("accept", src, out)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "FROZEN LINES CHANGED" in r.stdout, r.stdout
    assert src.read_text() == DOC, "accept replaced the file it refused"


def test_accept_still_takes_a_run_whose_frozen_rows_are_intact(tmp_path):
    ok = DOC.replace("This is a document that is, in point of fact, quite "
                     "verbose.", "This document is verbose.")
    src, out = _pair(tmp_path, ok)
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("accept", src, out)
    assert "FROZEN LINES CHANGED" not in r.stdout, r.stdout
    assert src.read_text() == ok, (r.returncode, r.stdout, r.stderr)



def test_merge_refuses_an_edit_that_lands_on_a_frozen_line(kv):
    """The primary gate, driven at `merge` the way the do-not-edit section is."""
    body = DOC.rstrip("\n").split("\n")
    prose, headings, tables, quotes = kv.mask(DOC, "d.md")
    row = next(i for i, ln in enumerate(body, 1) if ln == ROW)

    open_ = kv.editable_lines(prose, tables, headings, quotes)
    assert row in open_, "a table row is editable, which is why freeze exists"

    frozen = kv.freeze_lines(body, [r"^\s*\|"])
    held = kv.editable_lines(prose, tables, headings, quotes, frozen)
    assert row not in held, "the freeze never reached the editable set"

    edit = [{"specialist": "prose", "lo": 1, "hi": len(body),
             "edits": [{"line": row, "old": body[row - 1], "new": REWORDED}]}]
    out, applied, refused, _ = kv.merge(list(body), edit, held, (), headings,
                                        held=frozen)
    assert not applied and out[row - 1] == body[row - 1], applied
    assert refused[0][2] == "line is frozen by .killverbosity.json", refused

    out2, applied2, _r2, _ = kv.merge(list(body), edit, open_, (), headings)
    assert applied2 and out2[row - 1] == REWORDED, (applied2, out2[row - 1])


def test_a_frozen_line_is_not_scanned_for_shapes(tmp_path):
    """`blank_frozen`, on a frozen line that is NOT a table row."""
    verbose = ("Falsifier: the design is solid and the approach is robust, "
               "which is a very good outcome.\n")
    (tmp_path / "note.md").write_text("# Title\n\n" + verbose)

    (tmp_path / ".killverbosity.json").write_text("{}")
    loud = run_tool("plan", tmp_path / "note.md")
    assert "shapes: none" not in loud.stdout, loud.stdout

    (tmp_path / ".killverbosity.json").write_text(json.dumps({"freeze": {
        "lines": [r"^Falsifier:"],
        "reason": "read by a bare startswith, so bolding the key un-declares "
                  "the field"}}))
    quiet = run_tool("plan", tmp_path / "note.md")
    assert quiet.returncode == 0, quiet.stderr
    assert "frozen: 1 of " in quiet.stderr, quiet.stderr
    assert "shapes: none" in quiet.stdout, quiet.stdout
    assert "scanned" in quiet.stdout or "none scanned" in quiet.stdout, \
        quiet.stdout


def test_the_declaration_skill_md_prints_is_the_one_that_runs(tmp_path):
    """The documented example, typed."""
    md = (REPO / "SKILL.md").read_text()
    block = md.split("### `freeze`: when the hazard is a line")[1]
    decl = block.split("```json")[1].split("```")[0]
    json.loads(decl)
    (tmp_path / ".killverbosity.json").write_text(decl)
    doc = tmp_path / "status.md"
    doc.write_text("# T\n\n## Section\n\nsome prose here, quite verbose.\n\n"
                   "| a | b |\n|---|---|\n| 1 | 2 |\n")
    r = run_tool("plan", doc)
    assert r.returncode == 0, r.stderr
    assert "frozen: 4 of " in r.stderr, r.stderr


def test_verify_finds_the_declaration_when_the_original_was_copied_away(
        tmp_path):
    """README's own documented invocation found no config at all."""
    orig, edited = _pair(tmp_path, DOC.replace(ROW, REWORDED))
    away = tmp_path.parent / "copied-away-orig.md"
    away.write_text(orig.read_text())
    r = run_tool("verify", away, edited)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FROZEN LINES CHANGED" in r.stdout, r.stdout


def test_a_declaration_beside_neither_file_is_still_not_invented(tmp_path):
    """The control, and it is what stops the fix becoming a wider search."""
    _pair(tmp_path, DOC.replace(ROW, REWORDED))
    away = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    away.mkdir(exist_ok=True)
    (away / "note.md").write_text(DOC)
    (away / "note.kv.md").write_text(DOC.replace(ROW, REWORDED))
    r = run_tool("verify", away / "note.md", away / "note.kv.md")
    assert "FROZEN LINES CHANGED" not in r.stdout, r.stdout



def test_verify_names_the_config_it_used(tmp_path):
    orig, edited = _pair(tmp_path, DOC)
    r = run_tool("verify", orig, edited)
    assert f"config: {tmp_path / '.killverbosity.json'}" in r.stderr, r.stderr


def test_verify_says_so_when_no_config_governs_either_file(tmp_path):
    (tmp_path / "note.md").write_text(DOC)
    (tmp_path / "note.kv.md").write_text(DOC)
    r = run_tool("verify", tmp_path / "note.md", tmp_path / "note.kv.md")
    assert "config: none declared" in r.stderr, r.stderr
    assert str(tmp_path) in r.stderr, r.stderr
    assert "config: none declared" not in run_tool(
        "verify", *_pair(tmp_path, DOC)).stderr


def test_accept_names_the_config_at_its_own_inner_call(tmp_path):
    src, out = _pair(tmp_path, DOC)
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("accept", src, out)
    assert f"config: {tmp_path / '.killverbosity.json'}" in r.stderr, r.stderr


def test_run_names_the_config_at_its_own_inner_call(kv, monkeypatch, tmp_path,
                                                    capsys):
    doc = _tree(tmp_path)
    run_canned(kv, monkeypatch, doc, tmp_path / "out.md", lambda *_: [])
    said = capsys.readouterr()
    assert f"config: {tmp_path / '.killverbosity.json'}" in said.err, said.err


def test_accept_states_the_zero_when_nothing_governs_the_pair(tmp_path):
    """The `searched` half, which the two tests above cannot reach."""
    src = tmp_path / "note.md"
    src.write_text(DOC)
    out = tmp_path / "note.kv.md"
    out.write_text(DOC)
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("accept", src, out)
    assert "config: none declared" in r.stderr, r.stderr
    assert str(tmp_path) in r.stderr, r.stderr


def test_run_states_the_zero_when_nothing_governs_the_file(kv, monkeypatch,
                                                           tmp_path, capsys):
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    run_canned(kv, monkeypatch, doc, tmp_path / "out.md", lambda *_: [])
    said = capsys.readouterr()
    assert "config: none declared" in said.err, said.err
    assert str(tmp_path) in said.err, said.err



def test_plan_states_the_zero_when_nothing_governs_the_file(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    r = run_tool("plan", doc)
    assert "config: none declared" in r.stderr, r.stderr
    assert str(tmp_path) in r.stderr, r.stderr


def test_plan_names_the_config_it_used(tmp_path):
    """The control, and the only half a mutation can see."""
    r = run_tool("plan", _tree(tmp_path))
    assert f"config: {tmp_path / '.killverbosity.json'}" in r.stderr, r.stderr
    assert "config: none declared" not in r.stderr, r.stderr


def test_dry_run_states_the_zero_before_anything_is_dispatched(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    r = run_tool("run", doc, "--dry-run")
    assert "config: none declared" in r.stderr, r.stderr
    assert str(tmp_path) in r.stderr, r.stderr
