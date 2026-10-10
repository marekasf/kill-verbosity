"""A credit leaving its sentence is a finding with its line."""

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


HEADER = "credits that left their sentence — "

PRICING = ("# Pricing\n\nThe discount case rests on a benchmark the reseller "
           "commissioned last spring, across forty stores.\n\nThe discount "
           "applies to annual plans.\n")


def test_a_source_that_is_not_a_name_is_a_finding(kv, tmp_path):
    new = PRICING.replace("a benchmark the reseller commissioned",
                          "a commissioned benchmark")
    rc, out = _verify(kv, tmp_path, PRICING, new)
    assert rc == 3, out
    assert HEADER in out, out
    assert "reseller (commissioned) 1→0" in out, out
    assert "L3  The discount case rests on a benchmark the reseller" in out, out
    assert "credited names that went" in out, out


def test_a_named_credit_prints_its_line_not_only_a_count(kv, tmp_path):
    orig = ("# Notes\n\nPriya's review opened the thread.\n\n"
            "The retry cap was set per Priya's recap of the incident.\n\n"
            "Priya owns the rollback switch.\n")
    new = ("# Notes\n\nThe review opened the thread.\n\n"
           "The retry cap was set after the incident.\n\n"
           "Priya owns the rollback switch.\n")
    rc, out = _verify(kv, tmp_path, orig, new)
    assert HEADER in out, out
    assert "said fewer times than before: Priya 3→1" in out, out
    assert "L3  Priya's review opened the thread." in out, out
    noted = out.split(kv.NOTED_TITLE)[1] if kv.NOTED_TITLE in out else ""
    assert "Priya" not in noted, noted


def test_a_credit_kept_is_not_reported(kv, tmp_path):
    new = PRICING.replace("across forty stores", "over forty stores")
    rc, out = _verify(kv, tmp_path, PRICING, new)
    assert HEADER not in out, out
