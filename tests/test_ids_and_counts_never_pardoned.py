"""A deletion never pardons a ticket id or a count."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import time


def _verify(kv, tmp_path, orig, new, record=None):
    a, b = tmp_path / "o.md", tmp_path / "n.md"
    a.write_text(orig)
    b.write_text(new)
    if record is not None:
        kv.write_run_record(b, **record)
        os.utime(kv.run_record_path(b), (time.time() + 5,) * 2)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(a), edited=str(b), chat=False, content_edit=False,
            exempt=[]))
    return rc, buf.getvalue()


PROVENANCE = ("Three auditors opened 31 invoices and found 27 correct, "
              "recorded under Q417, `R552` and FIN-208.")
ORIG = ("# Audit\n\n## Checks\n\nRun the audit each quarter.\n\n"
        "## Provenance\n\n" + PROVENANCE + "\n\n## Next\n\nFile the report.\n")
NEW = ORIG.replace(PROVENANCE + "\n\n", "")


HEADER = "ids and counts in deleted text — "


def _block(out):
    assert HEADER in out, out
    return out.split(HEADER, 1)[1].split("\n\n", 1)[0]


def test_ids_and_counts_in_a_deleted_sentence_are_reported(kv, tmp_path):
    rc, out = _verify(kv, tmp_path, ORIG, NEW)
    assert rc == 3, out
    block = _block(out)
    for token in ("31", "27", "3", "Q417", "R552", "FIN-208"):
        assert token in block, (token, block)
    assert "lost and pardoned" not in out, out
    assert "ids and counts in deleted text" in out.split("REVIEW", 1)[1], out


def test_a_noise_exemption_does_not_pardon_them_either(kv, tmp_path):
    rc, out = _verify(kv, tmp_path, ORIG, NEW, record={
        "exempt": ["31", "27", "Q417", "R552", "FIN-208"]})
    assert rc == 3, out
    block = _block(out)
    assert "Q417" in block and "31" in block, block


def test_a_measurement_in_a_deleted_sentence_is_still_pardoned(kv, tmp_path):
    orig = ("# Build\n\n## Speed\n\nThe nightly build took 600s last week, "
            "which is slow.\n\n## Next\n\nCache the toolchain.\n")
    new = orig.replace("The nightly build took 600s last week, which is "
                       "slow.\n\n", "")
    rc, out = _verify(kv, tmp_path, orig, new)
    assert rc != 1 and "TOKENS LOST" not in out and HEADER not in out, out
    assert "600" in out.split("tokens in deleted sentences", 1)[1], out


def test_what_counts_as_an_id_or_a_count(kv):
    assert kv.BARE_ID.findall("Tracked as T221 since May.") == ["T221"]
    assert kv.never_pardon("ticket", "OPS-4471", "")
    assert kv.never_pardon("number", "20", "found 20 correct")
    assert kv.never_pardon("number", "2", "Two reviewers signed off")
    assert not kv.never_pardon("number", "403", "| 403 |")
    assert not kv.never_pardon("number", "11", "Decision 11 requires review")
