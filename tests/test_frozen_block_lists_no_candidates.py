"""A `kv:freeze` ... `kv:end` block was only partly protected.
Shapes read off `find_shapes` skipped it, because that consults `keep_lines`,
while the candidates `plan` and `run` compute beside it -- length, em-dash
pressure, walls, list faults, repeated text -- only skipped
`protected.lines`. A 39-word sentence inside the block was still listed, and
SKILL.md says no specialist may edit or FLAG anything there.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re

from conftest import run_tool

LONG = ("The migration runner reads every table in the schema and copies each "
        "row into the new cluster while the old cluster keeps serving reads "
        "until the final cutover window closes at night.")
BLOCK = [
    "It is worth noting that the deployment finished on time.",
    "",
    LONG,
    "",
    "The last ruling on scope came from the review (D3).",
    "",
    "The job — which runs nightly — copies rows — then — verifies them — twice.",
]
DOC = "\n".join(
    ["# Doc", "", "## Frozen", "", "<!-- kv:freeze -->"]
    + BLOCK
    + ["<!-- kv:end -->", "", "## Open", ""]
    + BLOCK) + "\n"
FROZEN = set(range(5, 14))
OPEN = {"frame": 17, "long": 19, "bare internal id": 21, "em-dash": 23}


def _rows(out):
    """(line, text) for every candidate row `plan` prints under a chunk."""
    rows = []
    for ln in out.splitlines():
        m = re.match(r"^\s{3,}(\d+)\s{2}(\S.*)$", ln)
        if m:
            rows.append((int(m.group(1)), m.group(2)))
    return rows


def test_plan_lists_nothing_inside_a_freeze_block(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rows = _rows(r.stdout)
    inside = [(n, t) for n, t in rows if n in FROZEN]
    assert not inside, (inside, r.stdout)
    for kind, line in OPEN.items():
        assert any(n == line and t.startswith(kind) for n, t in rows), \
            (kind, line, r.stdout)
    for grp in re.findall(r"lines \[([\d, ]+)\]", r.stdout):
        assert not {int(x) for x in grp.split(",")} & FROZEN, r.stdout


def test_run_dispatches_no_job_for_a_frozen_section(kv, monkeypatch, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    monkeypatch.setattr(kv, "_INSTALLED_OVERRIDE", {"codex": True})
    ns = argparse.Namespace(
        file=str(p), out=None, agent="codex", chat=False, dry_run=True,
        job_timeout=30, no_budget=True, only=None, timeout=60,
        full=False, profile=None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = kv.cmd_run(ns, launcher=lambda *a, **k: (None, "unused"))
    assert rc == 0, (rc, out.getvalue(), err.getvalue())
    jobs = [l for l in out.getvalue().splitlines() if " hits " in l]
    assert jobs, out.getvalue()
    assert not [j for j in jobs if "· Frozen" in j], out.getvalue()
    assert [j for j in jobs if "· Open" in j], out.getvalue()
