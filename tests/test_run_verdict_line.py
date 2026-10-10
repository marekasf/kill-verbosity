"""`run --agent claude` exited 3 REVIEW with words 1871 -> 1864
(-0.4%), shapes 5 -> 4 and "over target 1.99x". Every number was printed, on
three different lines hundreds of lines apart, so a skim could not tell a
partial pass from one that did nothing.
"""

from __future__ import annotations

import json
import re
import sys

LINES = [f"It should be noted that the worker, in point of fact, retries job "
         f"{i} and records the outcome in the store for the purposes of a "
         f"later inspection by whichever operator happens to be on call."
         for i in range(1, 8)]
DOC = "\n".join(["# Notes", "", "This paragraph wraps across",
                 "two full lines on purpose.", ""] + LINES)
FIRST = 6


def _run(kv, monkeypatch, tmp_path, capsys, edits):
    src, out = tmp_path / "doc.md", tmp_path / "out.md"
    src.write_text(DOC + "\n")

    def launcher(prompt, agent, timeout, say=None, avoid=()):
        mine = edits if f"L{FIRST}" in prompt or LINES[0][:40] in prompt else []
        return json.dumps({"edits": mine, "notes": []}), None

    monkeypatch.setattr(kv, "call_agent", launcher)
    monkeypatch.setattr(sys, "argv",
                        ["kill-verbosity", "run", str(src), "-o", str(out)])
    try:
        rc = kv.main()
    except SystemExit as e:
        rc = e.code
    return rc, capsys.readouterr().out


def _verdict_and_tally(out):
    rows = out.splitlines()
    verdicts = [i for i, r in enumerate(rows)
                if re.match(r"(PASS|REVIEW|FAIL) — \d+ of \d+ shapes? fixed", r)]
    assert len(verdicts) == 1, f"expected one verdict line, got {verdicts}:\n{out}"
    head = rows.index("── verify ──")
    assert verdicts[0] < head, "the verdict line is not above the verify block"
    tally = re.search(r"^shapes (\d+) → (\d+) \((\d+) new shapes?, (\d+) carried "
                      r"over\)", out, re.M)
    assert tally, out
    return rows[verdicts[0]], tuple(int(x) for x in tally.groups())


def test_a_pass_that_did_nothing_says_zero_fixed_and_the_target_in_one_line(
        kv, monkeypatch, tmp_path, capsys):
    rc, out = _run(kv, monkeypatch, tmp_path, capsys, edits=[])
    line, (o, n, new, carried) = _verdict_and_tally(out)

    assert rc == 3, (rc, out)
    assert line.startswith("REVIEW — "), line
    assert f"0 of {o} shapes fixed, {carried} carried over, {new} new" in line
    assert "words 263 → 263 (+0.0%)" in line, line
    assert re.search(r"still \d+\.\d\dx the length target", line), line


def test_a_partial_pass_says_how_many_it_fixed(kv, monkeypatch, tmp_path,
                                               capsys):
    fix = [{"line": FIRST, "old": LINES[0],
            "new": "The worker retries job 1 and records the outcome in the "
                   "store for a later inspection by the operator on call.",
            "why": "hedge"}]
    rc, out = _run(kv, monkeypatch, tmp_path, capsys, edits=fix)
    line, (o, n, new, carried) = _verdict_and_tally(out)

    fixed = o - carried
    assert fixed >= 1, f"the fixture fixed nothing, so it cannot test this:\n{out}"
    assert f"{fixed} of {o} shapes fixed, {carried} carried over, {new} new" \
        in line, line
    assert re.search(r"words 263 → \d+ \(-\d+\.\d%\)", line), line
