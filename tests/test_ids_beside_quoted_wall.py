"""`plan` on a bulleted out-of-scope list read
"shapes: wall 1" and listed no `bare internal id` for `(D13)` on the
wrapped SUPERSEDED item, nor for `(D3)`/`(D4)` one sibling bullet later,
while the paragraph wall the same span holds was still found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_tool

FIXTURE = (
    "**Out of scope** (sticky — leaves only when the user names it):\n"
    '- Modifying router4. Cite: "CRITICAL! do not modify router4 yet! it is '
    'handling production"\n'
    "  **SUPERSEDED ONCE, 2026-09-12, for one named edit only.** User: "
    '"this one is\n'
    '  approved tempporairly for this single edit" and "do it now - I will '
    "step in if\n"
    '  any problems". Scope of the withdrawal: `/etc/dhcp/dhcpd.conf` on '
    "router4,\n"
    '  adding the `failover peer "dhcp-failover"` block and the `pool {}` '
    "wrapper\n"
    "  (D13). Nothing else on router4 was touched and the entry stays in "
    "force for\n"
    "  everything else. Undo tracked as row 11.\n"
    "- Enabling HTB shaping (D3). Enabling the DDNS updater before cutover "
    "(D4).\n"
    "- T153 / the wire misrouting defect — the transport layer owns it and "
    "asked us out.\n"
    "\n"
)

_HIT_ROW = re.compile(r"^\s*(\d+)\s+([a-z][a-z0-9 ()]*?)\s{2,}")


def _rows(out):
    """(line, shape_name) for every candidate row `plan` prints."""
    hits = []
    for ln in out.splitlines():
        m = _HIT_ROW.match(ln)
        if m:
            hits.append((int(m.group(1)), m.group(2).strip()))
    return hits


def test_plan_lists_ids_beside_the_wall_they_sit_next_to(tmp_path):
    p = tmp_path / "fx2.md"
    p.write_text(FIXTURE)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)

    m = re.search(r"^shapes: (.+)$", r.stdout, re.M)
    assert m, r.stdout
    shapes_line = m.group(1)
    assert "bare internal id 3" in shapes_line, shapes_line
    assert "wall" in shapes_line, shapes_line

    rows = _rows(r.stdout)
    id_lines = sorted(ln for ln, name in rows if name == "bare internal id")
    assert id_lines == [7, 9, 9], rows
    assert "(D13)" in r.stdout, r.stdout
    assert "(D3)" in r.stdout, r.stdout
    assert "(D4)" in r.stdout, r.stdout

    assert any(name.startswith("wall") for _ln, name in rows), rows


def test_no_id_hit_where_there_is_no_id(tmp_path):
    """Negative control: line 10 names no decision and gets no hit."""
    p = tmp_path / "fx2.md"
    p.write_text(FIXTURE)
    r = run_tool("plan", p)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)

    rows = _rows(r.stdout)
    id_lines = {ln for ln, name in rows if name == "bare internal id"}
    assert 10 not in id_lines, rows
