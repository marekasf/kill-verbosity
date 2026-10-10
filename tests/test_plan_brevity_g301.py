"""`plan`'s four fixed-reasoning messages print one line by default."""

from __future__ import annotations

from conftest import run_tool

LEDE = (
    "This document records how the gateway resolves a request, which "
    "services it consults in order, and what each failure mode looks like "
    "from the caller's side so an operator can tell them apart without "
    "reading the code. It is scope and not summary: every stage below is "
    "described where it runs, and nothing here restates a result."
)

TABLE = (
    "| # | Task | Status |\n|---|---|---|\n"
    "| 1 | Fix the retry budget | open |\n"
    "| 2 | Update the docs | done |\n"
)

BODY = "".join(
    f"\n## Section {i}\n\n"
    + "".join(
        f"The resolver consults stage {i} step {j} and records the outcome "
        f"with its duration, so a later reader can reconstruct which "
        f"branch was taken and why the answer took as long as it did.\n"
        for j in range(1, 9)
    )
    for i in range(1, 7)
)

TAIL = "\nThe round-8 failure was never explained anywhere. The round-3 failure likewise.\n"

DOC = f"# Gateway resolution notes\n\n{LEDE}\n\n{TABLE}\n{BODY}{TAIL}"


def test_all_four_messages_print_one_line_by_default(doc):
    out = run_tool("plan", doc(DOC)).stdout

    assert "3 table rows: cell text is scanned and editable" in out, out
    assert "1 table here carry a Status/State column" in out, out
    assert "opening summary: UNHEADED — 57 words of prose sit" in out, out
    assert "the 2 `bare internal id` hits above are matched" in out, out

    lines = out.splitlines()
    table_line = next(l for l in lines if l.strip().startswith("3 table rows"))
    status_line = next(l for l in lines if "Status/State column" in l)
    summary_line = next(l for l in lines if l.startswith("opening summary:"))
    idfam_line = next(l for l in lines if "bare internal id` hits" in l)
    for line in (table_line, status_line, summary_line, idfam_line):
        assert "--full" in line, line

    assert "another tool's state" not in out, out
    assert "a tracker, a monitor, a queue" not in out, out
    assert "give it a heading with the word Summary" not in out, out
    assert "Gloss the id or override the line" not in out, out


def test_the_same_four_messages_print_their_reasoning_under_full(doc):
    out = run_tool("plan", doc(DOC), "--full").stdout

    assert ("cell text IS scanned" in out
            and "another tool's state" in out), out
    assert ("usually another tool's parsed state" in out
            and "a tracker, a monitor, a queue" in out), out
    assert ("give it a heading with the word Summary" in out
            and "say in your report that it is none of the three" in out), out
    assert ("Gloss the id or override the line" in out
            and "resolves against that file" in out), out

    assert "3 table rows:" in out, out
    assert "1 table here carry a Status/State column" in out, out
    assert "opening summary: UNHEADED — 57 words of prose sit" in out, out
    assert "the 2 `bare internal id` hits above are matched" in out, out


def test_full_and_default_reach_the_same_exit_code_and_work_list(doc):
    p = doc(DOC)
    short = run_tool("plan", p)
    full = run_tool("plan", p, "--full")
    assert short.returncode == full.returncode == 0, (short, full)
    chunks = lambda out: [l for l in out.stdout.splitlines() if l.startswith("── chunk")]
    assert chunks(short) == chunks(full), (chunks(short), chunks(full))
