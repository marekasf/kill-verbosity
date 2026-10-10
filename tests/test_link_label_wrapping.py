"""A markdown link label must not be broken across a newline by re-wrapping."""
import re
import textwrap

from killverbosity import wrapping as w

LINK = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)")
REAL = ('bound-group refusal to raise on `vwap_session` against six-field '
        'synthetic arrays, so [`if t == "unknown"`](bt/tape.py#L225) returns '
        'early at the top of the function.')


def _wrap(text, width, protect):
    if not protect:
        return textwrap.wrap(text, width=width, break_long_words=False,
                             break_on_hyphens=False)
    safe, toks = w._protect_tokens(text)
    return [w._restore_tokens(x, toks)
            for x in textwrap.wrap(safe, width=width, break_long_words=False,
                                   break_on_hyphens=False)]


def test_the_measured_line_keeps_its_link_whole():
    out = "\n".join(_wrap(REAL, 95, protect=True))
    assert LINK.search(out), out
    assert '[`if t == "unknown"`](bt/tape.py#L225)' in out, out


def test_the_unprotected_wrap_really_does_break_it():
    out = "\n".join(_wrap(REAL, 95, protect=False))
    assert not LINK.search(out), out


def test_no_word_is_lost_or_invented():
    out = " ".join(" ".join(_wrap(REAL, 95, protect=True)).split())
    assert out == " ".join(REAL.split()), out


def test_a_token_carrying_a_backreference_is_restored_verbatim():
    text = r'see [`a b`](x/\1\\y.md#L2) now, and it must survive the wrap'
    out = "\n".join(_wrap(text, 20, protect=True))
    assert r'[`a b`](x/\1\\y.md#L2)' in out, out


def test_a_token_with_no_space_is_left_untouched():
    _safe, toks = w._protect_tokens("see [label](a/b.md) here")
    assert toks == [], toks


def test_two_adjacent_protected_tokens_both_come_back():
    text = '[`a b`](x.md#L1) [`c d`](y.md#L2) and some following words here'
    out = "\n".join(_wrap(text, 24, protect=True))
    assert '[`a b`](x.md#L1)' in out and '[`c d`](y.md#L2)' in out, out



def _mask(text):
    """The narrowest stand-in that satisfies rewrap_prose: everything is prose."""
    lines = text.split("\n")
    return lines, [], [], []


def _wrapped_body():
    """A body that ESTABLISHES a margin, which is what rewrap_prose needs."""
    body = []
    for i in range(6):
        body += [(f"w{i} " * 18).rstrip(), (f"m{i} " * 18).rstrip(),
                 (f"t{i} " * 18).rstrip(), ""]
    return body


def test_rewrap_prose_itself_keeps_the_link_whole():
    body = _wrapped_body()
    out = w.rewrap_prose(body, body + [REAL], _mask)
    joined = "\n".join(out)
    assert '[`if t == "unknown"`](bt/tape.py#L225)' in joined, joined


def test_rewrap_prose_still_wraps_the_line_it_was_given():
    body = _wrapped_body()
    out = w.rewrap_prose(body, body + [REAL], _mask)
    assert len(out) > len(body) + 1, out


def test_the_placeholder_is_padded_so_the_width_stays_honest():
    line = 'a [`b c d e f`](some/target.md#L9) z'
    safe, toks = w._protect_tokens(line)
    assert toks, "nothing was protected, so this asserts nothing"
    assert len(safe) == len(line), safe


def test_a_protected_line_is_not_pushed_over_the_margin():
    body = _wrapped_body()
    out = w.rewrap_prose(body, body + [REAL], _mask)
    width = w.wrap_width(body, _mask)
    assert width, "no margin, so this asserts nothing"
    link_lines = [ln for ln in out if "tape.py#L225" in ln]
    assert link_lines, out
    token = '[`if t == "unknown"`](bt/tape.py#L225)'
    assert len(link_lines[0]) <= max(width, len(token)) + len(token), link_lines[0]


PLAIN = ('The regression is described in [the unknown-tape reader notes]'
         '(bt/tape.py#L225) and nowhere else in the tree.')


def test_a_link_label_with_no_code_span_is_protected_too():
    body = _wrapped_body()
    out = w.rewrap_prose(body, body + [PLAIN], _mask)
    joined = "\n".join(out)
    assert "[the unknown-tape reader notes](bt/tape.py#L225)" in joined, joined
    assert len(out) > len(body) + 1, "the line was not wrapped, so this asserts nothing"
