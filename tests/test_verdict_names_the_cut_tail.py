"""`verify`'s closing verdict line stepped over `cut_tails`."""

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

PASS_ORIG = """# Notes

The system logs every request and retries automatically, which keeps the
queue from stalling under load.

A second paragraph exists only so the document is not trivially short and so
surrounding structure checks have something ordinary to pass over quietly.
"""

PASS_EDIT = """# Notes

The system logs every request and retries automatically.

A second paragraph exists only so the document is not trivially short and so
surrounding structure checks have something ordinary to pass over quietly.
"""

REVIEW_HEAD = """# Decision tracker

The rows below are the decisions this round took, with the cross-check that
produced each one cited beside it so a reader can go back to the transcript.

| id | goal | owner | status |
|---|---|---|---|
"""
REVIEW_D4 = ("| D4 | Keep the fixture corpus in the repository so a reviewer "
             "can re-run it, rather than regenerating it per run | ana | "
             "open |\n")
REVIEW_D5 = ("| D5 | A DECORATOR ALONE IS NOT ENOUGH FOR PARAMETRISED "
             "FIXTURES, AND THE CROSS-REVIEW PROVED IT (C270) (C316) | ana "
             "| open |\n")
REVIEW_D6 = ("| D6 | Retire the second runner once the first has been green "
             "for a fortnight, and say so in the log | bo | open |\n")
REVIEW_D5_GUTTED = ("| D5 | A DECORATOR ALONE IS NOT ENOUGH FOR PARAMETRISED "
                    "FIXTURES. | ana | open |\n")


def _verify(tmp_path, orig, edit, name="t"):
    o, n = tmp_path / f"{name}.orig.md", tmp_path / f"{name}.new.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_pass_names_the_cut_tail(tmp_path):
    """The defect, isolated to the PASS branch. Prints the block, said nothing."""
    r = _verify(tmp_path, PASS_ORIG, PASS_EDIT, "pass_named")

    assert "clause cut from the end" in r.stdout, r.stdout
    assert r.stdout.count("clause cut from the end") >= 2, r.stdout


def test_the_pass_verdict_and_exit_code_do_not_change(tmp_path):
    """The reporting gap is fixed by naming, not by gating."""
    r = _verify(tmp_path, PASS_ORIG, PASS_EDIT, "pass_verdict")

    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "REVIEW" not in r.stdout, r.stdout
    assert "FAIL" not in r.stdout, r.stdout


def test_review_why_names_the_cut_tail(tmp_path):
    """The defect, isolated to the REVIEW branch: an existing trigger fires"""
    r = _verify(tmp_path, REVIEW_HEAD + REVIEW_D4 + REVIEW_D5 + REVIEW_D6,
                REVIEW_HEAD + REVIEW_D4 + REVIEW_D5_GUTTED + REVIEW_D6,
                "review_named")

    assert "REVIEW —" in r.stdout, r.stdout
    verdict_line = next(l for l in r.stdout.splitlines()
                        if l.startswith("REVIEW —"))
    assert "clause cut from the end" in verdict_line, verdict_line


def test_the_review_verdict_and_exit_code_do_not_change(tmp_path):
    """Same negative control, for the branch where REVIEW already fires."""
    r = _verify(tmp_path, REVIEW_HEAD + REVIEW_D4 + REVIEW_D5 + REVIEW_D6,
                REVIEW_HEAD + REVIEW_D4 + REVIEW_D5_GUTTED + REVIEW_D6,
                "review_verdict")

    assert r.returncode == 3, r.stdout
    assert "REVIEW" in r.stdout, r.stdout
    assert "FAIL" not in r.stdout, r.stdout
    assert "PASS" not in r.stdout, r.stdout
