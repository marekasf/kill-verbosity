"""A table row is its own claim, and a gutted cell is no longer silent."""
import pytest

from conftest import run_tool

HEAD = """# Findings

Some ordinary prose sits here so the document is not only a table.

| id | verdict | note |
|---|---|---|
"""
C1 = ("| c1 | keep | The retry loop never resets its backoff between attempts, "
      "so a transient failure escalates to a hard timeout on the third try "
      "rather than recovering. |\n")
C2 = ("| c2 | drop | Nothing in this path reads the cached value, so the cache "
      "is write-only and the eviction policy is unreachable. |\n")
C3 = ("| c3 | keep | The reviewer disagreed with the disposition and asked "
      "that the row stay open until the owner replies. |\n")


def _pair(tmp_path, edited, name="t"):
    o = tmp_path / f"{name}.orig.md"
    n = tmp_path / f"{name}.new.md"
    o.write_text(HEAD + C1 + C2 + C3)
    n.write_text(edited)
    return o, n


def test_a_gutted_cell_is_reported(tmp_path):
    o, n = _pair(tmp_path, HEAD + C1 + "| c2 | drop | Cache unused. |\n" + C3)
    r = run_tool("verify", o, n)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "content dropped" in r.stdout, r.stdout
    assert "L8" in r.stdout, r.stdout


def test_the_same_deletion_in_prose_and_in_a_cell_score_the_same(tmp_path):
    o, n = _pair(tmp_path, HEAD + C1 + "| c2 | drop | Cache unused. |\n" + C3)
    cell = run_tool("verify", o, n)

    claim = ("Nothing in this path reads the cached value, so the cache is "
             "write-only and the eviction policy is unreachable.")
    po = tmp_path / "p.orig.md"
    pn = tmp_path / "p.new.md"
    po.write_text(f"# Findings\n\nSome ordinary prose here.\n\n{claim}\n")
    pn.write_text("# Findings\n\nSome ordinary prose here.\n\nCache unused.\n")
    prose = run_tool("verify", po, pn)

    assert cell.returncode == prose.returncode == 3, (cell.returncode,
                                                      prose.returncode)
    assert "content dropped" in cell.stdout and "content dropped" in prose.stdout


def test_a_cell_pruned_hard_but_honestly_still_passes(tmp_path):
    o, n = _pair(tmp_path, HEAD
                 + "| c1 | keep | The retry loop never resets its backoff, so "
                   "a transient failure times out hard on the third try. |\n"
                 + "| c2 | drop | The cache is write-only, so its eviction "
                   "policy is unreachable. |\n"
                 + "| c3 | keep | The reviewer disagreed and asked that the "
                   "row stay open until the owner replies. |\n")
    r = run_tool("verify", o, n)
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert "PASS" in r.stdout, r.stdout
    assert "content dropped" not in r.stdout, r.stdout


def test_an_untouched_table_says_nothing(tmp_path):
    o, n = _pair(tmp_path, HEAD + C1 + C2 + C3)
    r = run_tool("verify", o, n)
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert "content dropped" not in r.stdout, r.stdout


def test_one_gutted_row_among_many_is_still_reported(tmp_path):
    subjects = ["broker holds the partition until the session expires",
                "scheduler retries the shard on a cold replica",
                "planner picks the wider index and never re-costs it",
                "collector drops the oldest bucket before flushing",
                "resolver caches a negative answer for the whole window",
                "writer fsyncs once per batch and not per record",
                "loader skips a manifest whose checksum is absent",
                "reaper walks the tombstones in insertion order",
                "balancer counts a draining node as available",
                "gateway retries a non-idempotent call after a timeout",
                "indexer rebuilds from the snapshot and not the log",
                "auditor reads the mirror rather than the primary",
                "sweeper releases the lease before the handoff lands",
                "throttle measures bytes and the quota counts requests",
                "packer aligns to four kilobytes and wastes the tail",
                "watcher debounces the event that ends the run",
                "router prefers the stale route with the lower cost",
                "cutover keeps both writers live for one interval",
                "vacuum runs inside the transaction it is cleaning",
                "shipper compresses after encrypting, so nothing shrinks"]
    rows = [f"| r{i} | keep | The {s}. |\n"
            for i, s in enumerate(subjects, 1)]
    o = tmp_path / "big.orig.md"
    n = tmp_path / "big.new.md"
    o.write_text(HEAD + "".join(rows))
    gutted = list(rows)
    gutted[9] = "| r10 | keep | Retry issue. |\n"
    n.write_text(HEAD + "".join(gutted))
    r = run_tool("verify", o, n)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "content dropped" in r.stdout, r.stdout


def test_a_token_cut_from_a_row_that_stayed_is_still_a_hard_failure(tmp_path):
    o = tmp_path / "s.orig.md"
    n = tmp_path / "s.new.md"
    body = (HEAD + "| c1 | keep | See `retry.py` for the loop. The retry loop "
                   "never resets its backoff between attempts. |\n" + C3)
    o.write_text(body)
    n.write_text(body.replace("See `retry.py` for the loop. ", ""))
    r = run_tool("verify", o, n)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "TOKENS LOST" in r.stdout and "retry.py" in r.stdout, r.stdout


def test_a_whole_table_of_token_only_rows_deleted_is_pardoned(tmp_path):
    o = tmp_path / "d.orig.md"
    n = tmp_path / "d.new.md"
    o.write_text("# Request\n\nI need access.\n\n"
                 "| API | Result |\n|---|---|\n"
                 "| `dlp.googleapis.com/v2/content:inspect` | 403 DENIED |\n"
                 "| `modelarmor.googleapis.com/v1/templates` | 403 DENIED |\n")
    n.write_text("# Request\n\nI need access.\n")
    r = run_tool("verify", o, n)
    assert r.returncode != 1, (r.returncode, r.stdout)
    assert "TOKENS LOST" not in r.stdout, r.stdout





def test_each_table_row_is_its_own_span(kv):
    doc = HEAD + C1 + C2 + C3
    prose, _heads, tables, _quotes = kv.mask(doc, "t")
    txt = kv.with_table_text(prose, tables)
    rows = [ln for ln, _c in tables]
    spans = list(kv.sentence_spans(list(enumerate(txt, 1)), rows))
    body = [(a, b) for a, b, _s in spans if a in rows]
    assert body == [(r, r) for r in rows], body
    joined = [(a, b) for a, b, _s in
              kv.sentence_spans(list(enumerate(txt, 1))) if a in rows]
    assert joined != body, joined


def test_a_row_closes_its_unit_as_well_as_opening_one(kv):
    doc = HEAD + C1 + "\n" if False else HEAD + C1 + (
        "That is the whole of the finding list.\n")
    prose, _heads, tables, _quotes = kv.mask(doc, "t")
    txt = kv.with_table_text(prose, tables)
    rows = [ln for ln, _c in tables]
    spans = list(kv.sentence_spans(list(enumerate(txt, 1)), rows))
    tail = [s for _a, _b, s in spans if "whole of the finding list" in s]
    assert tail == ["That is the whole of the finding list."], spans


def test_a_deleted_row_does_not_buy_a_pardon_for_a_surgical_one(tmp_path):
    o = tmp_path / "m.orig.md"
    n = tmp_path / "m.new.md"
    o.write_text(
        "# Findings\n\nSome ordinary prose here.\n\n"
        "| id | note |\n|---|---|\n"
        "| c1 | See `retry.py` for the loop, which never resets its "
        "backoff between attempts. |\n"
        "| c2 | `dlp.googleapis.com/v2/content:inspect` returns 403. |\n")
    n.write_text(
        "# Findings\n\nSome ordinary prose here.\n\n"
        "| id | note |\n|---|---|\n"
        "| c1 | The loop never resets its backoff between attempts. |\n")
    r = run_tool("verify", o, n)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "TOKENS LOST" in r.stdout, r.stdout
    assert "retry.py" in r.stdout, r.stdout
    assert "dlp.googleapis.com" not in r.stdout.split("tokens in deleted")[0], \
        r.stdout


def test_the_survivor_side_row_set_is_declared_unheld(kv):
    """The n-side row set is passed and NO case distinguishes it. Declared."""
    import inspect

    src = inspect.getsource(kv.claims_lost)
    line = "    for _a, _b, s in sentence_spans(list(enumerate(n_prose, 1)), n_rows):"
    assert src.count(line) == 1, src.count(line)


def test_the_survivor_claims_its_own_row_and_not_the_first_one_free(tmp_path):
    o = tmp_path / "f.orig.md"
    n = tmp_path / "f.new.md"
    head = "# Findings\n\nOrdinary prose here.\n\n| id | note |\n|---|---|\n"
    o.write_text(head
                 + "| c1 | `dlp.googleapis.com/v2/content:inspect` returns "
                   "403 for the notebook identity. |\n"
                 + "| c2 | See `retry.py`, whose loop never resets its "
                   "backoff between attempts. |\n")
    n.write_text(head
                 + "| c2 | The loop never resets its backoff between "
                   "attempts. |\n")
    r = run_tool("verify", o, n)
    assert r.returncode == 1, (r.returncode, r.stdout)
    assert "retry.py" in r.stdout, r.stdout
    _hard = r.stdout.split("tokens in deleted sentences")[0]
    assert "dlp.googleapis.com" not in _hard, r.stdout
    assert "tokens in deleted sentences" in r.stdout, r.stdout
    assert "dlp.googleapis.com" in r.stdout.split(
        "tokens in deleted sentences")[1], r.stdout


def test_the_merge_gate_reads_a_row_as_its_own_rule(kv):
    """`rules_eaten` refuses the one edit that eats a cell's rule."""
    doc = ("# Findings\n\nOrdinary prose here.\n\n"
           "| id | note |\n|---|---|\n"
           "| c1 | Never retry a non-idempotent call after a timeout, because "
           "the broker may already have committed it. |\n"
           "| c2 | The planner recosts the wider index on every vacuum. |\n")
    lines = doc.split("\n")
    prose, _heads, tables, _quotes = kv.mask(doc, "t")
    target = next(i for i, l in enumerate(lines, 1) if l.startswith("| c1 "))
    result = {"edits": [{"line": target, "old": lines[target - 1],
                         "new": "| c1 | Retries are fine. |"}]}
    eaten = kv.rules_eaten(lines, result, prose, tables)
    assert target in eaten, eaten
    assert "non-idempotent" in eaten[target], eaten

    ok = {"edits": [{"line": target, "old": lines[target - 1],
                     "new": "| c1 | Never retry a non-idempotent call after a "
                            "timeout: the broker may already have committed "
                            "it. |"}]}
    assert kv.rules_eaten(lines, ok, prose, tables) == {}, \
        kv.rules_eaten(lines, ok, prose, tables)
