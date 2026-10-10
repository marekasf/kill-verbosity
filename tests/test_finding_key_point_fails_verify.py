"""`verify` said REVIEW ("no token was lost") when the dropped
sentence was a finding's key point -- it carries no number, path, ticket or
rule word, so the token gate and the rule gate are both blind to it, and
ordinary "content dropped" is REVIEW, which `accept` takes unforced.
"""

from __future__ import annotations

from conftest import run_tool

ORIG = """# Findings

1. The cache eviction races with a concurrent write and serves stale data under load.
   **Fix:** Take the write lock before eviction begins.

2. The retry loop never resets its backoff between attempts.
   **Fix:** Reset backoff to the base value after every success.
"""

NEW_KEY_POINT_LOST = """# Findings

1. Sometimes there is a small problem here worth looking at closely.
   **Fix:** Take the write lock before eviction begins.

2. The retry loop never resets its backoff between attempts.
   **Fix:** Reset backoff to the base value after every success.
"""

ORIG_PLAIN_PROSE = """# Notes

The cache eviction races with a concurrent write and serves stale data
under load. It has been that way for a while.
"""

NEW_PLAIN_PROSE_LOST = """# Notes

Sometimes there is a small problem here worth looking at closely. It has
been that way for a while.
"""


def _pair(tmp_path, orig, new, name="t"):
    o = tmp_path / f"{name}.orig.md"
    n = tmp_path / f"{name}.new.md"
    o.write_text(orig)
    n.write_text(new)
    return o, n


def test_a_lost_finding_key_point_fails_verify(tmp_path):
    o, n = _pair(tmp_path, ORIG, NEW_KEY_POINT_LOST)
    r = run_tool("verify", o, n)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "FINDING LOST" in r.stdout, r.stdout
    assert "L3" in r.stdout, r.stdout


def test_the_same_sentence_lost_from_ordinary_prose_stays_review(tmp_path):
    o, n = _pair(tmp_path, ORIG_PLAIN_PROSE, NEW_PLAIN_PROSE_LOST, name="p")
    r = run_tool("verify", o, n)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "FINDING LOST" not in r.stdout, r.stdout
    assert "content dropped" in r.stdout, r.stdout
