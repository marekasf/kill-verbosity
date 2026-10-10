"""A block that FAILS the run said "A list to read, not a failure." """

import argparse
import contextlib
import inspect
import io
import re


VERDICT_LINES = {"FAIL", "PASS", "REVIEW", "NOTHING IN PLAY",
                 "NOTHING WAS IN PLAY"}

UPPERCASE_ADVISORY = {"NEW LONG SENTENCES"}

ADVISORY_SENTENCE = "not a failure"


def _headers_and_hard(kv):
    """Every block header in `cmd_verify`, and every name it registers hard."""
    src = inspect.getsource(kv.cmd_verify)
    headers = {h for h in re.findall(r'print\(\s*f?"(?:\\n)*([^"{]*?) — ', src)
               if h and not h.startswith(" ")}
    hard = set(re.findall(r'_failed_block\("([^"]+)"\)', src))
    return headers, hard


def _verify(kv, original, edited):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(original), edited=str(edited), chat=False,
            content_edit=False, exempt=[]))
    return rc, buf.getvalue()


def test_every_hard_block_header_is_uppercase_and_no_lowercase_one_is_hard(kv):
    headers, hard = _headers_and_hard(kv)
    upper = {h for h in headers if h[:1].isupper()}
    lower = {h for h in headers if h[:1].islower()}

    assert len(hard) == 18, (
        "the hard-block population moved (%d): re-derive it, and give any new "
        "block a header sentence that says it fails the run — %s"
        % (len(hard), sorted(hard)))
    assert len(lower) == 16, (
        "the lowercase-header population moved (%d): %s"
        % (len(lower), sorted(lower)))

    assert not [h for h in hard if not h[:1].isupper()], (
        "a hard block has a lowercase header, which every other lowercase "
        "header in this report means is advisory: %s"
        % sorted(h for h in hard if not h[:1].isupper()))
    assert not (lower & hard), (
        "lowercase => advisory no longer holds: %s" % sorted(lower & hard))

    assert VERDICT_LINES <= upper, (
        "a declared verdict-line exclusion is no longer found by the scan, so "
        "its reason now covers nothing: %s" % sorted(VERDICT_LINES - upper))
    assert UPPERCASE_ADVISORY <= upper, (
        "the declared uppercase-advisory block is gone from the scan: %s"
        % sorted(UPPERCASE_ADVISORY - upper))
    assert not (UPPERCASE_ADVISORY & hard), (
        "%s became a hard block — its 'A list to read, not a failure.' is now "
        "false and this file's control has inverted" % sorted(UPPERCASE_ADVISORY))


def test_a_hard_block_does_not_tell_the_reader_it_is_not_a_failure(kv, tmp_path):
    """`TOKENS EDITED` — exit 1, and it used to say it was not a failure."""
    orig = tmp_path / "o.md"
    edit = tmp_path / "e.md"
    orig.write_text("# Runner\n\nThe runner reads `config_alpha` at startup "
                    "and refuses when it is absent.\n")
    edit.write_text("# Runner\n\nThe runner reads `config_beta` at startup "
                    "and refuses when it is absent.\n")

    rc, out = _verify(kv, orig, edit)

    assert rc == 1, "TOKENS EDITED no longer fails the run (rc=%d):\n%s" % (rc, out)
    failed = next((l for l in out.splitlines()
                   if l.startswith("FAILED the run:")), None)
    assert failed and "TOKENS EDITED" in failed, (
        "the FAIL verdict does not name the block:\n%s" % out)

    block = next((l for l in out.splitlines()
                  if l.startswith("TOKENS EDITED — ")), None)
    assert block, "no TOKENS EDITED header in:\n%s" % out
    assert ADVISORY_SENTENCE not in block, (
        "a block that fails the run tells the reader it is not a failure, one "
        "paragraph above %r:\n  %s" % (failed, block))
    assert "FAILS the run" in block, (
        "the header does not say the block fails the run:\n  %s" % block)


def test_the_advisory_block_still_says_it_is_not_a_failure(kv, tmp_path):
    """The control. Without it the assertion above is a ban on the phrase."""
    orig = tmp_path / "o.md"
    edit = tmp_path / "e.md"
    orig.write_text("# Notes\n\nShort line here.\n")
    long_one = " ".join(["alpha bravo charlie delta echo foxtrot golf hotel "
                         "india juliet"] * 6)
    edit.write_text("# Notes\n\nShort line here.\n\n%s.\n" % long_one)

    rc, out = _verify(kv, orig, edit)

    assert rc == 3, (
        "NEW LONG SENTENCES is meant to be advisory (rc=%d) — if it now fails "
        "the run, its sentence is false too:\n%s" % (rc, out))
    block = next((l for l in out.splitlines()
                  if l.startswith("NEW LONG SENTENCES — ")), None)
    assert block, "no NEW LONG SENTENCES header in:\n%s" % out
    assert ADVISORY_SENTENCE in block, (
        "the advisory block stopped saying it is not a failure, so nothing "
        "now separates it from a hard one:\n  %s" % block)
