"""A quotation that WRAPS is the author's words too."""
import pytest

from conftest import REPO, run_tool

QUOTED = ('the release is, in point of fact, considerably more flaky than '
          'anybody involved was really prepared to admit at the time')


def _plan(tmp_path, body, name="one.md"):
    (tmp_path / name).write_text(body)
    r = run_tool("plan", tmp_path / name)
    assert r.returncode in (0, 3), (r.returncode, r.stdout + r.stderr)
    return r.stdout


def _shapes(out):
    line = next((l for l in out.splitlines() if l.startswith("shapes:")), "")
    return line[len("shapes:"):].strip()


def test_the_same_quotation_scores_the_same_wrapped_or_not(tmp_path):
    """The whole finding, in one file."""
    half = QUOTED.index("flaky")
    wrapped = f'The reviewer wrote "{QUOTED[:half]}\n{QUOTED[half:]}" and left.'
    flat = f'The reviewer wrote "{QUOTED}" and left.'
    assert "\n" in wrapped and "\n" not in flat
    assert _shapes(_plan(tmp_path, f"# T\n\n{wrapped}\n")) == \
        _shapes(_plan(tmp_path, f"# T\n\n{flat}\n", "two.md"))


def test_a_wrapped_quotation_fires_nothing(tmp_path):
    half = QUOTED.index("flaky")
    out = _plan(tmp_path, f'# T\n\nThe reviewer wrote "{QUOTED[:half]}\n'
                          f'{QUOTED[half:]}" and left.\n')
    assert _shapes(out) == "none", out


def test_the_same_words_outside_a_quotation_still_fire(tmp_path):
    """The control, and it is what stops the fix being `blank everything`."""
    half = QUOTED.index("flaky")
    out = _plan(tmp_path, f"# T\n\nThe reviewer wrote {QUOTED[:half]}\n"
                          f"{QUOTED[half:]} and left.\n")
    assert _shapes(out) != "none", out



def test_a_quotation_wrapping_over_three_lines_is_blanked_throughout(kv):
    src = ('# T\n\nHe wrote "one part here and\nanother part here and\n'
           'a third part here" and stopped.\n')
    prose, _h, _t, _q = kv.mask(src)
    body = [p for p in prose if p.strip()]
    assert "another part here" not in " ".join(body), body
    assert "He wrote" in " ".join(body) and "and stopped" in " ".join(body)


def test_curly_quotes_wrap_too(kv):
    src = "# T\n\nHe wrote “one part here and\nanother part” then.\n"
    prose, _h, _t, _q = kv.mask(src)
    assert "another part" not in " ".join(prose), prose


def test_an_unpaired_quote_cannot_reach_past_its_own_paragraph(kv):
    """The cost of the carry, bounded and asserted."""
    src = '# T\n\nHe said "this never closes\nand nor does this.\n\nA second ' \
          'paragraph that is entirely ordinary prose.\n'
    prose, _h, _t, _q = kv.mask(src)
    joined = " ".join(prose)
    assert "never closes" not in joined, prose
    assert "A second paragraph" in joined, prose


def test_a_one_character_quotation_opens_nothing(kv):
    """`"a"` is too short for INLINE_QUOTE, which wants 2 to 400."""
    src = '# T\n\nThe column is "a" and the next line is ordinary prose\n' \
          'that must survive the mask entirely intact.\n'
    prose, _h, _t, _q = kv.mask(src)
    assert "must survive the mask" in " ".join(prose), prose


@pytest.mark.parametrize("line,carry,still_open", [
    ('He said "one two three and', "", '"'),
    ('four five six" then left.', '"', ""),
    ('nothing closes it here', '"', '"'),
    ('a "self contained one" here', "", ""),
    ("open “one two three and", "", "“"),
    ("four five” done.", "“", ""),
])
def test_the_carry_says_what_is_still_open(kv, line, carry, still_open):
    _masked, got = kv.mask_quotes(line, carry)
    assert got == still_open, (line, carry, got)


def test_a_carried_quotation_blanks_only_up_to_its_close(kv):
    got, still = kv.mask_quotes('four five six" then he left.', '"')
    assert still == ""
    assert got.strip() == "then he left."
    assert len(got) == len('four five six" then he left.')



def test_the_design_notes_still_parse_after_the_carry(kv):
    """A real document: the shipped design notes."""
    text = (REPO / "docs/how-it-works.md").read_text()
    prose, headings, _t, _q = kv.mask(text)
    assert headings, "no heading survived the mask"
    assert sum(1 for p in prose if p.strip()) > 100, "the file went dark"


def test_the_length_measure_still_sees_the_ENDS_of_a_wrapped_quotation(kv):
    """The DECLARED LIMIT, measured rather than assumed."""
    src = ('# T\n\nHe wrote "one part here and\nanother part here and\n'
           'a third part here" and stopped.\n')
    prose, _h, _t, _q = kv.mask(src)
    back = " ".join(kv.with_spans(prose, src))
    assert "another part here" not in " ".join(prose), prose
    assert "another part here" not in back, back
    assert "one part here" in back and "a third part here" in back, back
    assert "and stopped" in back, back
