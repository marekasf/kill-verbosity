"""Each sentence of an ADDED summary is held to the body."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import time

HEADER = "summary sentences the body does not state — "

BODY = "".join(
    f"## Stage {i}\n\nThe ingest worker retries a failed batch at stage {i} "
    f"and records each outcome in the store, so the operator on call can "
    f"review the queue each morning before the next load starts.\n\n"
    for i in range(1, 31))
ORIG = "# Ingest worker\n\n" + BODY

BACKED = ("This guide covers how the ingest worker retries a failed batch and "
          "records each outcome in the store for the operator on call, who "
          "reviews the queue each morning before the next load starts.")
UNBACKED = ("The worker processed 9150 batches after Marisol approved the "
            "INC-7730 change.")


def _verify(kv, tmp_path, new):
    a, b = tmp_path / "o.md", tmp_path / "n.md"
    a.write_text(ORIG)
    b.write_text(new)
    kv.write_run_record(b, inserted=True)
    os.utime(kv.run_record_path(b), (time.time() + 5,) * 2)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(a), edited=str(b), chat=False, content_edit=False,
            exempt=[]))
    return rc, buf.getvalue()


def test_a_summary_sentence_the_body_does_not_state_is_flagged(kv, tmp_path):
    new = ("# Ingest worker\n\n## Summary\n\n" + BACKED + " " + UNBACKED
           + "\n\n" + BODY)
    rc, out = _verify(kv, tmp_path, new)
    assert rc == 3, out
    assert HEADER in out, out
    block = out.split(HEADER, 1)[1]
    assert "not in the body: 9150, INC-7730, Marisol" in block, block
    assert "This guide covers" not in block.split("\n\n", 1)[0], block
    assert "summary sentences the body does not state" in out.split(
        "REVIEW", 1)[1], out


def test_a_summary_the_body_backs_is_not_flagged(kv, tmp_path):
    new = "# Ingest worker\n\n## Summary\n\n" + BACKED + "\n\n" + BODY
    rc, out = _verify(kv, tmp_path, new)
    assert HEADER not in out, out
