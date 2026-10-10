"""The verdict says plainly that a changed verb or cause is not
checked.
"""

from __future__ import annotations

import argparse
import contextlib
import io


def _verify(kv, tmp_path, orig, new):
    a, b = tmp_path / "o.md", tmp_path / "n.md"
    a.write_text(orig)
    b.write_text(new)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(a), edited=str(b), chat=False, content_edit=False,
            exempt=[]))
    return rc, buf.getvalue()


def test_review_says_verb_and_cause_changes_are_not_checked(kv, tmp_path):
    orig = ("# Ledger\n\n## Origin\n\nThe churn figure was already quoted in "
            "the board pack before the export existed, because it came from a "
            "planner's estimate.\n\n## Other\n\nThe export runs nightly.\n")
    new = ("# Ledger\n\nThe churn figure was produced before the export "
           "existed.\n\n## Other\n\nThe export runs nightly.\n")
    rc, out = _verify(kv, tmp_path, orig, new)
    assert rc == 3 and "REVIEW" in out, out[-500:]
    assert "main verb or stated" in out and "cause changed" in out, out[-400:]


def test_pass_says_it_too(kv, tmp_path):
    orig = ("# Runbook\n\nThe alert looks harmless but usually is not, so "
            "page the owner first.\n")
    new = orig.replace("but usually is not", "and usually is")
    rc, out = _verify(kv, tmp_path, orig, new)
    assert rc == 0 and "PASS" in out, out[-500:]
    assert "main verb or cause" in out, out[-400:]
