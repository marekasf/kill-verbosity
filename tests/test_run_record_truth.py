"""What the run record says about what the run actually DID."""
import json
import shutil
import subprocess

import pytest

from conftest import run_canned, run_tool
from killverbosity.runrecord import run_record_path

ROW = "| C1 | done | 2026-09-01 | owner | ref | note |"
DOC = ("# Title\n\nThis is a document that is, in point of fact, quite "
       "verbose.\n\n| id | flag | when | who | ref | note |\n"
       "|---|---|---|---|---|---|\n" + ROW + "\n")

ALL = [r"^.*\S"]
ROWS_ONLY = [r"^\s*\|"]


def _tree(tmp_path, lines, doc=DOC, name="note.md"):
    (tmp_path / ".killverbosity.json").write_text(json.dumps({"freeze": {
        "lines": lines,
        "reason": "rows are split on | and must keep exactly 6 cells"}}))
    (tmp_path / name).write_text(doc)
    return tmp_path / name


def _record(out):
    return json.loads(run_record_path(out).read_text())



def test_a_fully_frozen_run_does_not_report_pass(tmp_path):
    doc = _tree(tmp_path, ALL)
    r = run_tool("run", doc, "--no-agents", "-o", tmp_path / "out.md")
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "NOTHING IN PLAY" in r.stdout, r.stdout
    assert "NOTHING WAS IN PLAY" in r.stdout, r.stdout
    assert "PASS —" not in r.stdout, r.stdout


def test_a_partly_frozen_run_still_passes(tmp_path):
    """The control, and it is the whole decision."""
    doc = _tree(tmp_path, ROWS_ONLY)
    r = run_tool("run", doc, "--no-agents", "-o", tmp_path / "out.md")
    assert "NOTHING IN PLAY" not in r.stdout, r.stdout
    assert "NOTHING WAS IN PLAY" not in r.stdout, r.stdout
    assert "frozen: 3 of " in r.stderr, r.stderr


def test_a_file_with_no_declaration_at_all_is_untouched(tmp_path):
    """The second control: the unfrozen run must be what it was."""
    (tmp_path / "note.md").write_text(DOC)
    r = run_tool("run", tmp_path / "note.md", "--no-agents",
                 "-o", tmp_path / "out.md")
    assert "NOTHING WAS IN PLAY" not in r.stdout, r.stdout
    assert "frozen:" not in r.stderr, r.stderr


def test_verify_alone_says_it_too(tmp_path):
    """The derived arm, which has no record to read."""
    orig = _tree(tmp_path, ALL)
    edited = tmp_path / "note.kv.md"
    edited.write_text(DOC)
    r = run_tool("verify", orig, edited)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "NOTHING IN PLAY" in r.stdout, r.stdout
    assert "counted here from the original" in r.stdout, r.stdout
    assert "5 of 7 line(s) are frozen" in r.stdout, r.stdout


def test_a_record_from_a_build_that_did_not_count_falls_back(tmp_path):
    """ABSENT is not zero, and the fallback is what makes that safe."""
    from killverbosity.runrecord import write_run_record

    orig = _tree(tmp_path, ALL)
    out = tmp_path / "note.kv.md"
    out.write_text(DOC)
    write_run_record(out, agent="codex", incomplete=[])
    r = run_tool("verify", orig, out)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "counted here from the original" in r.stdout, r.stdout


def test_the_run_says_whose_numbers_they_are(tmp_path):
    """The other half of that pair, or the phrase is a constant."""
    doc = _tree(tmp_path, ALL)
    r = run_tool("run", doc, "--no-agents", "-o", tmp_path / "out.md")
    assert "counted by the run" in r.stdout, r.stdout
    assert "counted here from the original" not in r.stdout, r.stdout


def test_a_file_with_nothing_editable_is_not_blamed_on_the_freeze(tmp_path):
    """The two zeros, and this is the one the freeze did not cause."""
    fenced = "```\nnot prose, and no specialist may touch it\n```\n"
    doc = _tree(tmp_path, [r"^```"], doc=fenced)
    r = run_tool("run", doc, "--no-agents", "-o", tmp_path / "out.md")
    assert "frozen: 2 of " in r.stderr, r.stderr
    assert "NOTHING WAS IN PLAY" not in r.stdout, r.stdout
    assert "It holds no prose" in r.stdout, r.stdout
    assert "are frozen by" not in r.stdout, r.stdout


def test_a_fully_frozen_run_names_the_freeze_in_its_unsent_line(tmp_path):
    """The pair to the case above: same zero, other cause, other sentence."""
    doc = _tree(tmp_path, ALL)
    r = run_tool("run", doc, "--no-agents", "-o", tmp_path / "out.md")
    assert "are frozen by" in r.stdout, r.stdout
    assert "It holds no prose" not in r.stdout, r.stdout


def test_nothing_in_play_does_not_shadow_a_real_failure(tmp_path):
    """Branch order, typed rather than reasoned about."""
    orig = _tree(tmp_path, ALL)
    edited = tmp_path / "note.kv.md"
    edited.write_text(DOC.replace(
        ROW, "| C1 | complete | 2026-09-01 | owner | ref | note |"))
    r = run_tool("verify", orig, edited)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "FROZEN LINES CHANGED" in r.stdout, r.stdout
    assert "NOTHING IN PLAY —" not in r.stdout, r.stdout
    assert "NOTHING WAS IN PLAY" in r.stdout, r.stdout


def test_accept_still_takes_a_fully_frozen_run(tmp_path):
    """Why this is rc 3 and not rc 1, executed."""
    doc = _tree(tmp_path, ALL)
    out = tmp_path / "out.md"
    run_tool("run", doc, "--no-agents", "-o", out)
    r = run_tool("accept", doc, out, force=True)
    assert "verify says something broke" not in r.stdout + r.stderr, r.stdout
    assert doc.read_text() == DOC, "accept refused a run it should have taken"



def test_the_record_counts_the_frozen_lines(tmp_path):
    doc = _tree(tmp_path, ROWS_ONLY)
    out = tmp_path / "out.md"
    run_tool("run", doc, "--no-agents", "-o", out)
    rec = _record(out)
    assert rec["frozen_lines"] == 3, rec
    assert rec["document_lines"] == 7, rec
    assert rec["editable"] == 2, rec
    assert rec["editable_unfrozen"] == 4, rec


def test_the_record_writes_a_zero_rather_than_omitting_it(tmp_path):
    """A count is not a partition."""
    (tmp_path / "note.md").write_text(DOC)
    out = tmp_path / "out.md"
    run_tool("run", tmp_path / "note.md", "--no-agents", "-o", out)
    rec = _record(out)
    for k in ("frozen_lines", "document_lines", "editable",
              "editable_unfrozen"):
        assert k in rec, (k, sorted(rec))
    assert rec["frozen_lines"] == 0, rec
    assert rec["editable"] == rec["editable_unfrozen"] == 4, rec


def test_verify_reads_the_records_numbers_over_its_own(tmp_path):
    """Precedence, and it is a claim a mutation can see."""
    doc = _tree(tmp_path, ALL)
    out = tmp_path / "out.md"
    run_tool("run", doc, "--no-agents", "-o", out)
    rec = _record(out)
    rec["editable_unfrozen"] = 4321
    run_record_path(out).write_text(json.dumps(rec))
    r = run_tool("verify", doc, out)
    assert "4321 line(s) a specialist" in r.stdout, r.stdout



def test_the_record_names_the_input_digest_at_both_ends(tmp_path):
    (tmp_path / "note.md").write_text(DOC)
    out = tmp_path / "out.md"
    r = run_tool("run", tmp_path / "note.md", "--no-agents", "-o", out)
    rec = _record(out)
    assert "source" in rec and "source_at_finish" in rec, sorted(rec)
    assert rec["source"] == rec["source_at_finish"], rec
    assert "INPUT MOVED" not in r.stderr + r.stdout, r.stderr


def test_a_write_to_the_input_mid_run_is_named(kv, monkeypatch, tmp_path,
                                                capsys):
    """The reported state, reproduced rather than described."""
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    out = tmp_path / "out.md"
    drifted = DOC.replace("quite verbose.", "quite verbose. Added by someone "
                                            "else while this run was out.")

    def reply(_who, _lo, _hi):
        doc.write_text(drifted)
        return []

    run_canned(kv, monkeypatch, doc, out, reply)
    said = capsys.readouterr()
    assert "INPUT MOVED UNDER THIS RUN" in said.err, said.err
    rec = _record(out)
    assert rec["source"] != rec["source_at_finish"], rec
    assert rec["source_at_finish"] == kv.source_fingerprint(drifted), rec
    assert rec["source"][:12] in said.err, said.err
    assert rec["source_at_finish"][:12] in said.err, said.err


@pytest.mark.skipif(shutil.which("diff") is None,
                    reason="no diff on PATH (stock Windows): the notice names diff")
def test_the_two_diffs_the_drift_notice_prints_actually_run(kv, monkeypatch,
                                                             tmp_path,
                                                             capsys):
    """A remedy inside a message is on no executed path."""
    doc = tmp_path / "note.md"
    doc.write_text(DOC)
    out = tmp_path / "out.md"

    def reply(_who, _lo, _hi):
        doc.write_text(DOC.replace("quite verbose.", "quite verbose. Added."))
        return []

    run_canned(kv, monkeypatch, doc, out, reply)
    said = capsys.readouterr()
    cmds = [ln.strip() for ln in said.err.splitlines()
            if ln.strip().startswith("diff ")]
    assert len(cmds) == 2, said.err
    for c in cmds:
        rc = subprocess.run(c.split()[:3], cwd=tmp_path,
                            capture_output=True, text=True).returncode
        assert rc in (0, 1), (c, rc)


def test_a_clean_run_prints_no_diff_advice(tmp_path):
    """The control for the case above, and it is the one that decides it."""
    (tmp_path / "note.md").write_text(DOC)
    r = run_tool("run", tmp_path / "note.md", "--no-agents",
                 "-o", tmp_path / "out.md")
    assert "diff note.orig.md" not in r.stderr, r.stderr


