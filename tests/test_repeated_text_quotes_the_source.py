"""`plan` printed a repeated-text finding as "that is
the same the eval case expects an agent to name", a string that exists nowhere
in the document; grep returned 0 hits raw and unwrapped. The finding was true.
The real text is "That is the same `ModelFinder` the `locate-moving-object`
eval case expects an agent to name".
"""

from __future__ import annotations

import re
import sys

SENT = ("That is the same `ModelFinder` the `locate-moving-object` eval case "
        "expects an agent to name when it reads the tree.")
DOC = f"""# Finder notes

## First

{SENT}

## Second

Later on we say it again. {SENT}
"""


def _plan(kv, monkeypatch, capsys, path):
    monkeypatch.setattr(sys, "argv", ["kill-verbosity", "plan", str(path)])
    try:
        kv.main()
    except SystemExit:
        pass
    return capsys.readouterr().out


def test_plan_quotes_a_repeat_as_the_author_wrote_it(kv, monkeypatch, capsys,
                                                    tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(DOC)
    out = _plan(kv, monkeypatch, capsys, p)

    row = next((r for r in out.splitlines()
                if re.match(r"\s+lines \[5, 9\]\s+\d+w\s", r)), None)
    assert row, out
    quote = re.sub(r"^\s+lines \[5, 9\]\s+\d+w\s+", "", row)
    quote = quote.split("  · ")[0].rstrip("…")
    assert "`ModelFinder`" in quote, row
    assert quote in DOC, (
        f"the printed repeat is not text the document contains: {quote!r}")


def test_a_wrapped_copy_quotes_its_own_lines_joined(kv):
    lines = ["# T", "", "That is the same `ModelFinder` the",
             "`locate-moving-object` eval case expects an agent to name here.",
             "", "Again: That is the same `ModelFinder` the",
             "`locate-moving-object` eval case expects an agent to name here."]
    prose = kv.mask("\n".join(lines))[0]
    [d] = [d for d in kv.duplicates(prose, src=lines) if d["lines"][0] == 3]

    unwrapped = " ".join(ln.strip() for ln in lines)
    assert d["said"] in unwrapped, d["said"]
    assert d["said"].startswith("That is the same `ModelFinder`"), d["said"]


def test_the_match_key_is_still_the_normalised_words(kv):
    """Control: `repeat_delta` and every run-to-run comparison key on `text`.
    Putting the source text there would make a reworded code span a new
    cluster, so the key must stay the masked, lower-cased words."""
    lines = DOC.split("\n")
    prose = kv.mask(DOC)[0]
    [d] = kv.duplicates(prose, src=lines)

    assert d["text"].startswith("that is the same the eval case"), d["text"]
    assert kv.duplicates(prose)[0]["text"] == d["text"]
