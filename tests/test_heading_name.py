"""A heading's NAME, as against whatever bytes were on its line."""
from __future__ import annotations

import argparse
import contextlib
import io

import pytest

from conftest import run_canned

FILLER = ("The team reviewed the window and recorded what it found in the log "
          "so a later reader can check the numbers against the run that made "
          "them and decide whether the window was the right one to pick. ")

SECTIONS = ((8, "What to change, and why"),
            (15, "The window, and who owns it"),
            (3, "Where the numbers came from"))


def _doc(summary_body):
    out = ["# The window report\n", "## Summary\n", summary_body, ""]
    for n, title in SECTIONS:
        out += [f"## {n}. {title}\n", FILLER * 14, ""]
    return "\n".join(out) + "\n"


WRAPPED = ("The run found two things (15. \n"
           "The window, and who owns it) and (8. What to change, and \n"
           "why) needs a decision, as does (3. Where the numbers came from).")

CLEAN = ("The run found two things (15. The window, and who owns it) and\n"
         "(8. What to change, and why) needs a decision, as does\n"
         "(3. Where the numbers came from).")

ABSENT = ("The run found two things (15. The window, and who owns it) and\n"
          "(Where nobody wrote anything up, and \n"
          "why) needs a decision.")


def _verify(kv, tmp_path, edited, original=None):
    o = tmp_path / "o.md"
    n = tmp_path / "n.md"
    o.write_text(_doc(original if original is not None else CLEAN))
    n.write_text(_doc(edited))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(o), edited=str(n), chat=False,
            content_edit=False, exempt=[]))
    return rc, buf.getvalue()



def test_a_pointer_wrapped_over_a_trailing_space_is_not_a_ghost(kv, tmp_path):
    """The reported failure, through the real command."""
    rc, out = _verify(kv, tmp_path, WRAPPED)
    assert "summary pointers" not in out, out
    assert "SUMMARY POINTERS BROKEN" not in out, out
    assert rc != 1, out


def test_a_the_control_a_pointer_naming_no_heading_still_fails(kv, tmp_path):
    """The gate, on the input it exists for."""
    rc, out = _verify(kv, tmp_path, ABSENT)
    assert "SUMMARY POINTERS BROKEN" in out, out
    assert "Where nobody wrote anything up, and why" in out, out
    assert rc == 1, (rc, out)
    assert "15. The window" not in out.split("summary pointers")[1], out


def test_a_whitespace_is_collapsed_on_both_sides_of_the_comparison(kv):
    """The unit, at both spellings that reach it."""
    heads = ["15. The window, and who owns it", "8. What to change, and why"]
    ok = "(8. What to change, and why)"
    for spelling in ("15.  The window, and who owns it",
                     "15. The window, and who owns it ",
                     "15. The window,\nand who owns it"):
        assert kv.ghost_pointers(f"See ({spelling}) and {ok}.", heads) \
            == ([], False), spelling
    miss, broken = kv.ghost_pointers(f"See (9. Nobody owns the window) {ok}.",
                                     heads)
    assert miss == ["9. Nobody owns the window"] and broken


def test_a_the_paraphrase_check_reads_a_doubled_pointer_as_the_name(kv):
    """The third reader of the same question, and the costlier one."""
    heads = ["The five clusters round two found", "Retry budget"]
    assert kv._paraphrased_pointers(
        "as listed (The five clusters  round two found)", heads) == set()
    assert kv._paraphrased_pointers(
        "as listed (the five clusters listed below)", heads) \
        == {"the five clusters listed below"}


def test_a_the_order_outline_names_headings_and_not_their_lines(kv):
    """`outline_of` feeds the one job whose answer is a line number."""
    doc = ("# T\n\n## The goal <!-- kv:keep -->\n\nSome prose.\n"
           "\n## Other\n\nMore prose.\n")
    prose, heads, _t, _q = kv.mask(doc)
    got = kv.outline_of(heads, doc.split("\n"), prose)
    assert "## The goal" in got, got
    assert "kv:keep" not in got, got


def test_a_heading_name_does_not_collapse_two_different_headings(kv):
    """The normaliser is whitespace and comments only."""
    assert kv.heading_name("8. What to change, and why") \
        != kv.heading_name("8. What to change, and when")



MARKED = ("# Marked report\n"
          "\n"
          "## The goal <!-- kv:keep -->\n"
          "\n"
          "This paragraph is ordinary prose that the specialists may rewrite "
          "however they like.\n"
          "\n"
          "The author protected this one themselves.  <!-- kv:keep -->\n"
          "\n"
          "## Definition of done\n"
          "\n"
          + FILLER * 4 + "\n")


def _outline(kv, monkeypatch, tmp_path, text):
    """The outline block out of a real prompt, as a specialist receives it."""
    src = tmp_path / "d.md"
    src.write_text(text)
    seen = []
    real = kv.job_prompt

    def spy(job, *a, **k):
        p = real(job, *a, **k)
        seen.append(p)
        return f"@@{job['specialist']}|{job['lo']}|{job['hi']}@@ {job['unit']}"

    monkeypatch.setattr(kv, "job_prompt", spy)
    run_canned(kv, monkeypatch, src, tmp_path / "d.kv.md",
               lambda who, lo, hi: [])
    assert seen, "no job was dispatched, so no prompt was built"
    return "\n".join(seen), src


def test_b_the_outline_names_a_heading_without_its_protection_comment(
        kv, monkeypatch, tmp_path):
    """The heading's NAME reaches the specialist, not its line."""
    prompts, _src = _outline(kv, monkeypatch, tmp_path, MARKED)
    outline = prompts.split("outline (")[1].split("```````")[1]
    assert "The goal" in outline, outline
    assert "kv:keep" not in outline, outline


def test_b_the_control_a_marker_the_author_wrote_in_prose_survives(
        kv, monkeypatch, tmp_path):
    """The comment is a protection marker wherever the author put it."""
    prose, heads, tables, quotes = kv.mask(MARKED)
    marked = next(i + 1 for i, l in enumerate(MARKED.split("\n"))
                  if "author protected" in l)
    assert marked in kv.keep_lines(prose)
    assert marked not in kv.editable_lines(prose, tables, heads, quotes)

    prompts, src = _outline(kv, monkeypatch, tmp_path, MARKED)
    out = tmp_path / "d.kv.md"
    assert "kv:keep" in out.read_text()
    assert "The author protected this one themselves.  <!-- kv:keep -->" \
        in prompts


def test_b_a_pointer_that_copied_the_comment_still_resolves(kv):
    """The two halves meet here."""
    heads = ["The goal <!-- kv:keep -->", "Definition of done"]
    assert kv.ghost_pointers(
        "The backtesting workflow (The goal <!-- kv:keep -->) and "
        "(Definition of done) both hold.", heads) == ([], False)
    assert kv.ghost_pointers(
        "The backtesting workflow (The goal) and (Definition of done) "
        "both hold.", heads) == ([], False)


@pytest.mark.parametrize("trailing", ["", " ", "   "])
def test_c_a_folded_paragraph_does_not_duplicate_its_own_first_characters(
        kv, trailing):
    """`fold_paragraphs` sliced the indent by total whitespace, not leading."""
    from killverbosity import wrapping

    lines = [f"Alpha beta gamma delta{trailing}", "epsilon zeta eta theta."]
    folded = wrapping.fold_paragraphs(lines, lambda t: kv.mask(t))
    assert [t for t, _a, _b in folded] == \
        ["Alpha beta gamma delta epsilon zeta eta theta."], folded


def test_c_a_folded_paragraph_keeps_its_real_indent(kv):
    """The control: leading whitespace is still the indent it always was."""
    from killverbosity import wrapping

    folded = wrapping.fold_paragraphs(
        ["  Alpha beta gamma delta  ", "  epsilon zeta."],
        lambda t: kv.mask(t))
    assert [t for t, _a, _b in folded] == \
        ["  Alpha beta gamma delta epsilon zeta."], folded



from killverbosity import pointers

MARKED_HEAD = "The goal <!-- kv:keep -->"


def test_d_rename_map_keys_on_the_name(kv):
    """`(The goal)` is what a specialist writes once the outline is clean."""
    m = pointers.rename_map([(2, 2, MARKED_HEAD)], {3: "## The objective"})
    assert m == {"The goal": "The objective"}
    results = [{"specialist": "summary",
                "edits": [{"new": "the result. (The goal)"}]}]
    assert pointers.follow(results, m) == [("The goal", "The objective")]
    assert results[0]["edits"][0]["new"] == "the result. (The objective)"


def test_d_follow_still_moves_a_pointer_that_copied_the_comment(kv):
    """The other spelling, which used to work and must keep working."""
    m = pointers.rename_map([(2, 2, MARKED_HEAD)], {3: "## The objective"})
    results = [{"specialist": "summary",
                "edits": [{"new": f"the result. ({MARKED_HEAD})"}]}]
    assert pointers.follow(results, m) == [("The goal", "The objective")]
    assert results[0]["edits"][0]["new"] == "the result. (The objective)"


def test_d_the_control_a_rename_that_only_moves_a_comment_is_no_rename(kv):
    """The normaliser must not invent a rename either."""
    assert pointers.rename_map([(2, 2, MARKED_HEAD)], {3: "## The goal"}) == {}
    assert kv.renamed_headings([(2, 2, MARKED_HEAD)], {3: "## The goal"}) \
        == set()
    assert kv.renamed_headings([(2, 2, MARKED_HEAD)],
                               {3: "## The objective"}) == {"The goal"}


def test_d_heads_after_finds_a_marked_headings_own_entry(kv):
    """`heads_after` looks the heading up in `rename_map`'s keys."""
    m = pointers.rename_map([(2, 2, MARKED_HEAD)], {3: "## The objective"})
    assert kv.heads_after([(2, 2, MARKED_HEAD)], m) == ["The objective"]


def _merge_summary_pointer(kv, pointer):
    """`merge`, with `structure` deleting the marked heading under a pointer."""
    lines = ["# T", "", f"## {MARKED_HEAD}", "",
             f"The result is in. ({pointer})", "", "## Other", "",
             "Body text here."]
    results = [
        {"specialist": "structure",
         "edits": [{"line": 3, "old": lines[2], "new": ""}]},
        {"specialist": "summary",
         "edits": [{"line": 5, "old": lines[4],
                    "new": f"The result. ({pointer})"}]}]
    prose, heads, tables, quotes = kv.mask("\n".join(lines))
    _got, _ok, refused, _d = kv.merge(
        lines, results, kv.editable_lines(prose, tables, heads, quotes),
        headings=heads)
    return refused


def test_d_merge_still_refuses_a_pointer_at_a_heading_being_deleted(kv):
    """`merge`'s own copy of the question, on both spellings of the bracket."""
    for pointer in ("The goal", "The  goal"):
        why = [w for _ln, _who, w in _merge_summary_pointer(kv, pointer)]
        assert why == ["it points at The goal, renamed by another "
                       "specialist in this run"], (pointer, why)


def test_d_the_control_a_pointer_at_a_live_heading_is_not_refused(kv):
    """The gate, silent where it should be."""
    why = [w for _ln, _who, w in _merge_summary_pointer(kv, "Other")]
    assert why == [], why


RENAME_DOC = ("# Marked report\n\n"
              f"## {MARKED_HEAD}\n\n" + FILLER * 18 + "\n\n"
              "## Other\n\n" + FILLER * 18 + "\n")


def _canned_rename_run(kv, monkeypatch, tmp_path, pointer):
    src = tmp_path / "x.md"
    src.write_text(RENAME_DOC)
    head_line = next(i for i, l in enumerate(RENAME_DOC.split("\n"), 1)
                     if l.startswith("## The goal"))

    def reply(who, lo, hi):
        if who == "structure":
            return [{"op": "replace", "line": head_line,
                     "old": f"## {MARKED_HEAD}", "new": ""}]
        if who == "summary":
            return [{"op": "insert", "line": 2,
                     "new": "## Summary\n\nThe result is in and it is "
                            f"short. ({pointer})\n"}]
        return []

    return run_canned(kv, monkeypatch, src, tmp_path / "x.kv.md", reply)


def test_d_the_retry_names_a_dead_pointer_whatever_its_whitespace(
        kv, monkeypatch, tmp_path, capsys):
    """The list that spends a retry, on the bracket a wrap produced."""
    jobs = _canned_rename_run(kv, monkeypatch, tmp_path, "The  goal")
    err = capsys.readouterr().err
    assert "asking once more: It points at The goal, which another " \
           "specialist renames in this same run" in err, err
    assert jobs.count(("summary", "document")) == 2, jobs


def test_d_the_control_a_live_pointer_buys_no_retry(kv, monkeypatch, tmp_path,
                                                    capsys):
    """The same run, the bracket naming the section nothing touches."""
    jobs = _canned_rename_run(kv, monkeypatch, tmp_path, "Other")
    assert "asking once more" not in capsys.readouterr().err
    assert jobs.count(("summary", "document")) == 1, jobs


def test_b_the_control_a_marked_heading_keeps_its_shape_exemption(kv):
    """The over-reach the normaliser's own docstring refuses."""
    words = "## This is a very robust and clean approach"
    marked = kv.mask(f"# T\n\n{words}  <!-- kv:keep -->\n\nBody prose.\n")
    bare = kv.mask(f"# T\n\n{words}\n\nBody prose.\n")

    def on_the_heading(masked):
        prose, headings, tables, quotes = masked
        return [h for h in kv.find_shapes(prose, tables, headings, quotes)
                if h[0] == 3]

    assert on_the_heading(marked) == []
    assert on_the_heading(bare), "the shapes are not reported without the marker"
