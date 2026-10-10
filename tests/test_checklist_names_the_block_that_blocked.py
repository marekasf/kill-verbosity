"""`--verdict` off said "Nothing here blocks" over a run that returned 1."""

import argparse
import contextlib
import io

ORIGINAL = """# Runbook

The service is restarted by the operator after a configuration change.
Nothing else in the pipeline needs attention when this happens.
"""

ADDS_FACTS = """# Runbook

The service is restarted by the operator after a configuration change,
and the retry budget is 12 attempts against `/var/run/svc.sock`.
Nothing else in the pipeline needs attention when this happens.
"""

TIGHTENED = """# Runbook

The operator restarts the service after a configuration change.
Nothing else in the pipeline needs attention.
"""


def _verify_quiet(kv, tmp_path, original, edited):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(original)
    b.write_text(edited)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = kv.cmd_verify(argparse.Namespace(
            original=str(a), edited=str(b), chat=False,
            content_edit=False, exempt=[], verdict=False))
    line = next((l for l in buf.getvalue().splitlines() if "checklist done" in l), "")
    return rc, line, buf.getvalue()


def test_a_blocked_run_does_not_say_nothing_here_blocks(kv, tmp_path):
    rc, line, _ = _verify_quiet(kv, tmp_path, ORIGINAL, ADDS_FACTS)
    assert rc == 1, f"the fixture stopped hard-failing, so this asserts nothing: rc={rc}"
    assert line, "the checklist line is gone"
    assert "Nothing here blocks" not in line, line
    assert "things to read above" not in line, line


def test_a_blocked_run_names_the_block_that_blocked(kv, tmp_path):
    _, line, _ = _verify_quiet(kv, tmp_path, ORIGINAL, ADDS_FACTS)
    assert "TOKENS ADDED" in line, line
    assert "accept" in line, f"the reader is not told what this costs them: {line}"


def test_an_unblocked_run_still_gets_the_count_and_the_clearance(kv, tmp_path):
    rc, line, _ = _verify_quiet(kv, tmp_path, ORIGINAL, TIGHTENED)
    assert rc != 1, f"the control fixture became a hard failure: rc={rc}"
    assert "Nothing here blocks" in line, line
    assert "things to read above" in line or "thing to read above" in line, line
    assert "TOKENS ADDED" not in line, line


def test_the_empty_name_list_is_guarded(kv, tmp_path):
    import inspect
    src = inspect.getsource(kv.cmd_verify)
    guard = 'if hard_blocks else ""'
    assert src.count(guard) == 1, (
        "the empty-name guard on the checklist line moved or multiplied (%d)"
        % src.count(guard))
