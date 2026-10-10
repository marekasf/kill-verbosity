"""A paragraph wall was dropped
whole because ONE sentence inside it carried a supersede/withdraw
marker and happened to sit on the paragraph's first line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from conftest import run_tool

FIXTURE = (
    "The Q4 rollout plan was withdrawn (D15). This sentence adds no new "
    "claim, it\n"
    "is only here to pad the sentence count. This sentence restates the "
    "same idea\n"
    "a different way, again with no new claim. A third padding sentence "
    "sits here\n"
    "to keep the count well past the wall floor of four. A fourth padding\n"
    "sentence closes in on the count needed for a wall. This final "
    "sentence\n"
    "closes the wall with one more restatement of the same point, purely "
    "for\n"
    "padding.\n"
)


def test_no_kv_markers_in_fixture():
    """Control on the fixture itself: nothing here is an explicit marker."""
    assert "kv:freeze" not in FIXTURE
    assert "kv:keep" not in FIXTURE
    assert "<!--" not in FIXTURE


def test_wall_survives_a_kept_sentence_that_opens_it(tmp_path):
    p = tmp_path / "wall.md"
    p.write_text(FIXTURE)

    r = run_tool("plan", p, "--json")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    walls = [w for c in payload["chunks"] for w in c["wall_paragraphs"]]
    assert walls, "the wall was dropped whole: " + json.dumps(payload["chunks"])
    assert walls[0]["line"] == 1, walls
    assert walls[0]["sentences"] >= 4, walls

    r2 = run_tool("plan", p)
    assert r2.returncode == 0, (r2.returncode, r2.stdout, r2.stderr)
    m = re.search(r"^shapes: (.+)$", r2.stdout, re.M)
    assert m, r2.stdout
    assert "wall" in m.group(1), m.group(1)


def test_kept_sentence_itself_stays_silent(tmp_path):
    """The other requirement: no separate "not editable" finding on
    the kept sentence's own line -- silence there, not a candidate."""
    p = tmp_path / "wall.md"
    p.write_text(FIXTURE)

    r = run_tool("plan", p, "--json")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    for c in payload["chunks"]:
        assert not any(s["line"] == 1 for s in c["shapes"]), c["shapes"]
        assert not any(ls["line"] == 1 for ls in c["long_sentences"]), \
            c["long_sentences"]
