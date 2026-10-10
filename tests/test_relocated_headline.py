"""A relocation must not be reported under the clean-pass headline."""

from conftest import run_tool

CLEAN = "no token was lost and no shape was added"

_RELOCATED_BEFORE = """# Doc

## Setup

You must never delete the run record beside the output file.

Some other prose sits here to give the section a body.

## Appendix

You must never delete the run record beside the output file.

More prose lives under the appendix heading as well.
"""

_RELOCATED_AFTER = """# Doc

## Setup

Some other prose sits here to give the section a body.

## Appendix

You must never delete the run record beside the output file.

More prose lives under the appendix heading as well.
"""

_CLEAN_BEFORE = """# Doc

## Setup

It should be noted that the nightly build runs at 02:00 UTC.

You must never delete the run record beside the output file.
"""

_CLEAN_AFTER = """# Doc

## Setup

The nightly build runs at 02:00 UTC.

You must never delete the run record beside the output file.
"""


def _verify(tmp_path, before, after):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(before)
    b.write_text(after)
    return run_tool("verify", a, b)


def test_a_relocation_is_not_reported_as_a_clean_pass(tmp_path):
    """The deleted rule matches a pre-existing sentence under another heading."""
    r = _verify(tmp_path, _RELOCATED_BEFORE, _RELOCATED_AFTER)

    assert "rules that changed section" in r.stdout, r.stdout
    assert CLEAN not in r.stdout, (
        "the clean-pass headline was printed over a relocation:\n" + r.stdout)
    assert "under a different heading" in r.stdout, r.stdout


def test_the_clean_headline_still_prints_when_nothing_relocated(tmp_path):
    """The control, and the reason it is here."""
    r = _verify(tmp_path, _CLEAN_BEFORE, _CLEAN_AFTER)

    assert "rules that changed section" not in r.stdout, r.stdout
    assert CLEAN in r.stdout, (
        "the control lost the clean headline, so the fix is too wide:\n"
        + r.stdout)
