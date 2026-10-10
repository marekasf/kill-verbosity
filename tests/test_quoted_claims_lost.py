"""a deleted quotation must be a hard failure, the same class as
TOKENS LOST, and must not fire on an edit that only reflows one.
"""

import json

import pytest
from conftest import run_tool

pytestmark = pytest.mark.regression

QUOTE_ORIG = """# Four Proposals

## Background

This document compares four different approaches teams considered for the
metrics dashboard, after two independent engineers each spent a week
prototyping a fix.

## Findings

**Both models found the hole, separately.**

Nobody had noticed the finish-line problem until both engineers flagged it in
the same week, working from different starting points and different data.

In their words — *"a precise number built on the wrong finish line is worse"* than a blank,
and *"a misleading number encourages teams to generate unhelpful code."*

The team agreed to ship the blank rather than the wrong number, and to revisit
once the finish line is well defined.

## Next steps

Pick one of the four proposals above and file a ticket for it before the next
planning cycle starts.
"""

QUOTE_EDIT = """# Four Proposals

## Background

This document compares four different approaches teams considered for the
metrics dashboard, after two independent engineers each spent a week
prototyping a fix.

## Findings

Nobody had noticed the finish-line problem until both engineers flagged it in
the same week, working from different starting points and different data.

The team agreed to ship the blank rather than the wrong number, and to revisit
once the finish line is well defined.

## Next steps

Pick one of the four proposals above and file a ticket for it before the next
planning cycle starts.
"""

REFLOW_EDIT = """# Four Proposals

## Background

This document compares four different approaches teams considered for the
metrics dashboard, after two independent engineers each spent a week
prototyping a fix.

## Findings

**Both models found the hole, separately.**

Nobody had noticed the finish-line problem until both engineers flagged it in
the same week, working from different starting points and different data.

In their words, both engineers agreed on the same two points independently:
*"a precise number built on the wrong finish
line is worse"* than a blank, and *"a misleading
number encourages teams to generate unhelpful code."*

The team agreed to ship the blank rather than the wrong number, and to revisit
once the finish line is well defined.

## Next steps

Pick one of the four proposals above and file a ticket for it before the next
planning cycle starts.
"""

MOVE_ORIG = """# Report

## Findings

*"a precise number built on the wrong finish line is worse"* than a blank.

## Next steps

File a ticket.
"""

MOVE_EDIT = """# Report

## Next steps

File a ticket. *"a precise number built on the wrong finish line is worse"* \
than a blank.
"""


def _verify(tmp_path, orig, edit, name="new.md"):
    o, n = tmp_path / "orig.md", tmp_path / name
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_a_deleted_quoted_judgement_is_a_hard_failure(tmp_path):
    r = _verify(tmp_path, QUOTE_ORIG, QUOTE_EDIT)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout
    assert ("a precise number built on the wrong finish line is worse"
            in r.stdout), r.stdout
    assert ("a misleading number encourages teams to generate unhelpful "
            "code." in r.stdout), r.stdout
    assert "L16" in r.stdout, r.stdout
    assert "L17" in r.stdout, r.stdout


def test_reflowing_a_quote_across_lines_is_not_a_failure(tmp_path):
    """Both quotations survive verbatim; only their line wrap changed."""
    r = _verify(tmp_path, QUOTE_ORIG, REFLOW_EDIT)

    assert r.returncode != 1, r.stdout
    assert "QUOTATIONS LOST" not in r.stdout, r.stdout


def test_a_quote_moved_whole_to_another_section_is_not_a_failure(
        tmp_path):
    r = _verify(tmp_path, MOVE_ORIG, MOVE_EDIT)

    assert r.returncode != 1, r.stdout
    assert "QUOTATIONS LOST" not in r.stdout, r.stdout


def test_a_quote_inside_a_code_fence_is_not_tracked(tmp_path):
    """A quoted example in a fence is code, not a claim on the prose."""
    orig = """# Doc

```text
log.info("a precise number built on the wrong finish line is worse")
```
"""
    edit = """# Doc

```text
log.info("ok")
```
"""
    r = _verify(tmp_path, orig, edit)

    assert "QUOTATIONS LOST" not in r.stdout, r.stdout


def test_the_runs_own_kvrun_exempt_list_pardons_a_dropped_quote(
        tmp_path):
    """The existing pardon mechanism, not a new one."""
    o = tmp_path / "orig.md"
    n = tmp_path / "new.md"
    o.write_text(QUOTE_ORIG)
    n.write_text(QUOTE_EDIT)
    quote_a = ('"a precise number built on the wrong finish line is '
               'worse"')
    quote_b = ('"a misleading number encourages teams to generate '
               'unhelpful code."')
    (tmp_path / "new.md.kvrun").write_text(json.dumps(
        {"exempt": [quote_a, quote_b]}))

    r = run_tool("verify", o, n)

    assert r.returncode != 1, r.stdout
    assert "QUOTATIONS LOST" not in r.stdout, r.stdout
