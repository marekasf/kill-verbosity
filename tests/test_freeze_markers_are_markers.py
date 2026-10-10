"""The block form
`<!-- kv:freeze -->` ... `<!-- kv:end -->` was added, and `mask()`'s marker validator
still listed only kv:keep, kv:allow and kv:allow-shape. So `plan` on any file
using the block exited 2 with "writes 'kv:freeze', which is not a marker and
protects nothing" -- nothing could be frozen at all.
"""

from __future__ import annotations

from conftest import run_tool

FRAME = "It is worth noting that the deployment finished on time."

DOC = (
    "# Rules\n\n"
    "## Working rules (verbatim)\n\n"
    "<!-- kv:freeze -->\n"
    f"{FRAME}\n"
    "\n"
    f"{FRAME}\n"
    "<!-- kv:end -->\n"
    "\n"
    "## Notes\n\n"
    f"{FRAME}\n"
)


def _hit_lines(out):
    """Line numbers of the rows `plan` prints under a chunk."""
    rows = []
    for ln in out.splitlines():
        parts = ln.split()
        if ln.startswith("   ") and parts and parts[0].isdigit():
            rows.append(int(parts[0]))
    return rows


def test_plan_accepts_a_freeze_block_and_protects_it(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "not a marker" not in r.stderr, r.stderr
    rows = _hit_lines(r.stdout)
    assert 13 in rows, r.stdout
    assert not {6, 8} & set(rows), r.stdout


def test_run_no_agents_accepts_a_freeze_block(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    r = run_tool("run", p, "--no-agents")
    assert r.returncode != 2, (r.returncode, r.stdout, r.stderr)
    assert "not a marker" not in r.stderr, r.stderr
    out = tmp_path / "doc.kv.md"
    assert out.read_text() == DOC


def test_a_misspelled_freeze_marker_is_still_refused(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC.replace("kv:freeze", "kv:freez"))
    r = run_tool("plan", p)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "'kv:freez', which is not a marker" in r.stderr, r.stderr
    assert "kv:freeze" in r.stderr.split("They are", 1)[-1], r.stderr
    assert "kv:end" in r.stderr.split("They are", 1)[-1], r.stderr
