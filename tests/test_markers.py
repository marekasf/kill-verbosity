"""A misspelled `kv:` marker is refused, and a quoted one is not."""

import pytest

from conftest import REPO, run_tool

REFUSED = 2


def _doc(tmp_path, text):
    p = tmp_path / "d.md"
    p.write_text(text)
    return p



@pytest.mark.parametrize("name,text", [
    ("prose", "# Doc\n\nReal prose here.  <!-- kv:kep -->\n"),
    ("heading", "# Doc  <!-- kv:kep -->\n\nProse.\n"),
    ("table cell", "# Doc\n\n| a | b |\n|---|---|\n| x <!-- kv:kep --> | 2 |\n"),
    ("blockquote", "# Doc\n\n> quoted  <!-- kv:kep -->\n"),
])
def test_a_typo_on_scanned_text_stops_the_run(tmp_path, name, text):
    res = run_tool("plan", _doc(tmp_path, text))

    assert res.returncode == REFUSED, (name, res.returncode, res.stdout)
    assert "kv:kep" in res.stderr, (name, res.stderr)



@pytest.mark.parametrize("name,text", [
    ("fenced block",
     "# Doc\n\nProse.\n\n```\nI think this is clean.  <!-- kv:kep -->\n```\n"),
    ("inline code span",
     "# Doc\n\nA span: `<!-- kv:kep -->` is a typo.\n"),
])
def test_a_typo_inside_code_is_an_example_and_is_read(tmp_path, name, text):
    res = run_tool("plan", _doc(tmp_path, text))

    assert res.returncode != REFUSED, (name, res.returncode, res.stderr)


def test_an_unclosed_fence_is_reported_before_the_marker(tmp_path):
    """Precedence, and the reason the check moved rather than grew a flag."""
    res = run_tool("plan", _doc(
        tmp_path, "# Doc\n\n```\nnever closed  <!-- kv:kep -->\n"))

    assert res.returncode == REFUSED, (res.returncode, res.stdout)
    assert "never closes" in res.stderr, res.stderr
