"""A tracker cell that loses its evidence clause AND its row citations."""
from conftest import run_tool

HEAD = """# Decision tracker

The rows below are the decisions this round took, with the cross-check that
produced each one cited beside it so a reader can go back to the transcript.

| id | goal | owner | status |
|---|---|---|---|
"""
D4 = ("| D4 | Keep the fixture corpus in the repository so a reviewer can "
      "re-run it, rather than regenerating it per run | ana | open |\n")
D5 = ("| D5 | A DECORATOR ALONE IS NOT ENOUGH FOR PARAMETRISED FIXTURES, AND "
      "THE CROSS-REVIEW PROVED IT (C270) (C316) | ana | open |\n")
D6 = ("| D6 | Retire the second runner once the first has been green for a "
      "fortnight, and say so in the log | bo | open |\n")


def _pair(tmp_path, edited):
    o = tmp_path / "t.orig.md"
    n = tmp_path / "t.new.md"
    o.write_text(HEAD + D4 + D5 + D6)
    n.write_text(edited)
    return o, n


def test_the_amputated_cell_and_its_citations_are_reported(tmp_path):
    """The defect, end to end. On the shipped code this printed nothing."""
    gutted = ("| D5 | A DECORATOR ALONE IS NOT ENOUGH FOR PARAMETRISED "
              "FIXTURES. | ana | open |\n")
    o, n = _pair(tmp_path, HEAD + D4 + gutted + D6)
    r = run_tool("verify", o, n)
    assert "clause cut from the end" in r.stdout, r.stdout
    assert "L9" in r.stdout, r.stdout
    assert "cross-review proved it" in r.stdout.lower(), r.stdout
    assert "c270" in r.stdout.lower(), r.stdout
    assert "c316" in r.stdout.lower(), r.stdout


def test_the_token_gate_cannot_see_a_row_citation(kv):
    """Why this is a clause check and not a wider token shape."""
    got = kv.facts("| D5 | proved it (C270) in OPS-4125 over 42 rows |")
    assert "OPS-4125" in got["ticket"], dict(got)
    assert "42" in got["number"], dict(got)
    assert not any("C270" in v for vs in got.values() for v in vs), dict(got)


def test_a_clean_two_rows_into_one_fold_stays_silent(tmp_path):
    """CONTROL. Folding is legal and is what the file-wide search is for."""
    folded = ("| D4+D6 | Keep the fixture corpus in the repository so a "
              "reviewer can re-run it, rather than regenerating it per run. "
              "Retire the second runner once the first has been green for a "
              "fortnight, and say so in the log | ana | open |\n")
    o, n = _pair(tmp_path, HEAD + folded + D5)
    r = run_tool("verify", o, n)
    assert "clause cut from the end" not in r.stdout, r.stdout


def test_a_row_lifted_verbatim_into_the_prose_stays_silent(tmp_path):
    """CONTROL. Moving a row out of the table is legal, and it is what
    refuted the lineage pairing: that design fired on this with output
    byte-identical to a real deletion."""
    moved = (HEAD.replace(
        "| id | goal | owner | status |",
        "D5: A DECORATOR ALONE IS NOT ENOUGH FOR PARAMETRISED FIXTURES, AND "
        "THE CROSS-REVIEW PROVED IT (C270) (C316)\n\n"
        "| id | goal | owner | status |") + D4 + D6)
    o, n = _pair(tmp_path, moved)
    r = run_tool("verify", o, n)
    assert "clause cut from the end" not in r.stdout, r.stdout


def test_a_genuine_condensation_of_the_same_cell_stays_silent(tmp_path):
    """CONTROL, and it is the one that decides whether this ships."""
    condensed = ("| D5 | The decorator alone is not sufficient for "
                 "parametrised fixtures and the cross-review measured that "
                 "(C270) (C316) | ana | open |\n")
    o, n = _pair(tmp_path, HEAD + D4 + condensed + D6)
    r = run_tool("verify", o, n)
    assert "clause cut from the end" not in r.stdout, r.stdout


def test_an_untouched_table_stays_silent(tmp_path):
    """CONTROL. The passing case is what says the check can stay quiet."""
    o, n = _pair(tmp_path, HEAD + D4 + D5 + D6)
    r = run_tool("verify", o, n)
    assert "clause cut from the end" not in r.stdout, r.stdout
