"""Round 4 findings."""

import os
import time
from conftest import run_canned
from killverbosity import protected, reply, rerun
from killverbosity import _legacy as kv
from killverbosity.wrapping import rewrap_prose, wrap_width


def _mask(text):
    return kv.mask(text, "t.md")


def _doc(*paragraphs):
    return "\n\n".join(paragraphs) + "\n"


BODY = _doc(
    "The run reads the file and reports every shape that it found, and a\n"
    "note on the ordering is printed beside the list so a reader knows.",
    "The list is ordered by line so that a reader can walk the file from\n"
    "the top to the bottom holding the printed report beside it.",
    "The second pass over the same output was measured across nine runs\n"
    "and bought very little, so the tool does not offer a revision pass.",
    "Every gate matches text rather than meaning, so a sentence turned\n"
    "around keeps all of its words and passes each of the checks.",
    "A reader who wants the short version can read the header line, which\n"
    "names the count and the cost, and then decide about the rest.")

URL = ("https://console.cloud.google.com/vertex-ai/model-garden/foo/bar/"
       "baz-qux-quux?project=acme-demo-d-c5i0&tab=overview&page=1")


def test_one_bare_url_does_not_take_the_file_out_of_the_fold():
    """A URL cannot be wrapped shorter, so it is not evidence of no margin."""
    plain = BODY.split("\n")
    assert wrap_width(plain, _mask) is not None, "fixture stopped wrapping"

    with_url = (BODY + "\n" + URL + "\n").split("\n")
    assert len(URL) > 100, len(URL)
    assert wrap_width(with_url, _mask) == wrap_width(plain, _mask)


def test_a_soft_wrapped_file_still_says_it_has_no_margin():
    """One paragraph per line, each far past any margin. Nothing to read off."""
    soft = _doc(*["A paragraph the editor soft-wraps, so it is one very long "
                  "line in the file and no margin can be read off it at all."
                  for _ in range(20)])

    assert wrap_width(soft.split("\n"), _mask) is None


def test_lines_that_merely_sit_together_are_not_a_wrapped_paragraph():
    """A block of short entries has continuation lines and no margin."""
    block = "\n".join(f"row {i}" for i in range(20))

    assert wrap_width((BODY + "\n" + block + "\n").split("\n"), _mask) is None


def test_one_line_paragraphs_do_not_dilute_the_margin_test():
    """A file of bullets beside wrapped prose still folds."""
    bullets = "\n\n".join(f"- entry number {i}" for i in range(30))
    doc = (BODY + "\n\n" + bullets + "\n").split("\n")

    assert wrap_width(doc, _mask) is not None


def test_a_url_line_is_not_rewrapped():
    """Rewrapping a line no margin can shorten only reflows what is round it."""
    lines = (BODY + "\n" + URL + "\n").split("\n")
    assert rewrap_prose(lines, lines, _mask) == lines


def test_a_journal_turns_the_overwrite_refusal_into_a_resume(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("one\n")
    out = tmp_path / "in.kv.md"
    out.write_text("two\n")
    later = src.stat().st_mtime + 10
    os.utime(out, (later, later))

    assert rerun.verdict(out, src, "one\n", {"k": "v"}) == rerun.RESUME
    assert rerun.verdict(out, src, "one\n", {}) == rerun.REFUSE


def test_the_overwrite_refusal_names_both_mtimes_and_the_gap():
    """The verdict is one mtime against another, so the message prints both."""
    said = rerun.refusal("in.kv.md", 1_700_000_090.0, 1_700_000_000.0)

    assert "90s apart" in said
    for t in (1_700_000_090.0, 1_700_000_000.0):
        assert time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) in said


def test_an_output_older_than_its_input_is_not_in_the_way(tmp_path):
    src = tmp_path / "in.md"
    out = tmp_path / "in.kv.md"
    out.write_text("two\n")
    src.write_text("one\n")

    assert rerun.verdict(out, src, "one\n", {}) == rerun.PROCEED


def test_an_output_identical_to_the_input_is_not_in_the_way(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("one\n")
    out = tmp_path / "in.kv.md"
    out.write_text("one\n")

    assert rerun.verdict(out, src, "one\n", {}) == rerun.PROCEED


THINKING = '''Here's a thinking process:

1.  **Understand the Task**: I need to act as a specialist in a pipeline
    that simplifies a document. The shape is {"edits": [...]}.

Now the answer:

{"edits": [{"line": 4, "old": "a", "new": "b", "why": "shorter"}],
 "notes": []}
'''


def test_a_reasoning_preamble_no_longer_kills_the_span():
    payload, err = reply.payload(THINKING)

    assert err is None, err
    assert payload["edits"][0]["line"] == 4


def test_an_example_object_in_the_preamble_loses_to_the_real_answer():
    raw = 'The shape is {"foo": 1}. My answer:\n{"edits": [], "notes": ["x"]}'
    payload, err = reply.payload(raw)

    assert err is None, err
    assert payload["notes"] == ["x"]


def test_a_fenced_answer_still_wins():
    raw = 'noise {"edits": [{"line": 9}]}\n```json\n{"edits": [], "notes": []}\n```'
    payload, _err = reply.payload(raw)

    assert payload["edits"] == []


def test_a_brace_inside_a_string_does_not_end_the_object():
    raw = '{"edits": [], "notes": ["a } brace in prose"]}'
    payload, err = reply.payload(raw)

    assert err is None, err
    assert payload["notes"] == ["a } brace in prose"]


def test_an_answer_with_no_object_still_names_what_came_back():
    payload, err = reply.payload("I could not do that.")

    assert payload is None
    assert "no JSON object" in err


PROTECTED_DOC = """# Platform notes

Ordinary prose that any specialist may rewrite as it likes.

## NOTE FOR AGENTS: what this report has to contain

Ten things are required. A rewrite that drops any of them is a regression.

### The ten

That section is marked do-not-modify. Read it, do not edit it.

## Exit codes

Read the exit code off a command that is not piped anywhere.
"""


def test_a_do_not_edit_section_is_dropped_from_the_editable_set():
    prose, headings, tables, quotes = _mask(PROTECTED_DOC)
    ok = kv.editable_lines(prose, tables, headings, quotes)

    assert 3 in ok, "ordinary prose stopped being editable"
    for line in (5, 7, 9, 11):
        assert line not in ok, line
    assert 13 in ok, "the next section at the same level is still editable"


def test_a_heading_about_the_marker_is_not_itself_frozen():
    assert not protected.is_marker("What NOTE FOR AGENTS means")
    assert protected.is_marker("NOTE FOR AGENTS: what this must contain")
    assert protected.is_marker("Do not edit")
    assert protected.is_marker("do-not-modify")
    assert not protected.is_marker("Exit codes")


def test_no_specialist_is_sent_into_a_protected_section(tmp_path, kv,
                                                        monkeypatch):
    doc = tmp_path / "p.md"
    doc.write_text(PROTECTED_DOC)
    out = tmp_path / "p.kv.md"
    asked = []

    def reply_fn(who, lo, hi):
        asked.append((who, lo, hi))
        return []

    run_canned(kv, monkeypatch, doc, out, reply_fn)

    for who, lo, hi in asked:
        if who in ("structure", "summary"):
            continue
        assert not (lo <= 7 <= hi), (who, lo, hi)
