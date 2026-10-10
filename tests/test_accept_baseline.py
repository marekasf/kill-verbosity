"""`accept`: where the baseline is, what it says about it, and the copy it keeps."""

import io
import contextlib
import shlex

import pytest

GONE = "gone unless git has it"
DECL = '{"refuse": "this tree is a loop state: R10 is line-scoped."}'
DOC = ("# Retention\n\nSession rows are retained for twelve months in the "
       "primary store.\n\n## Storage\n\nThe utilisation of the archival tier "
       "enables the organisation to reduce costs in a manner that is both "
       "efficient and effective.\n")


def _baseline_clause(out: str) -> str:
    """The one sentence under test, isolated from the rest of the report."""
    line = next(l for l in out.splitlines() if "The text before the first run" in l)
    return line.split("The text before the first run:", 1)[1]


def _one_edit(kv):
    """Replace the padding sentence — the one edit no gate objects to."""
    def reply(who, lo, hi):
        if not (lo <= 7 and (hi is None or hi >= 7)):
            return []
        return [{"op": "replace", "line": 7,
                 "old": DOC.splitlines()[6],
                 "new": "The archival tier cuts cost."}]
    return reply


@pytest.fixture
def declared_run(kv, monkeypatch, tmp_path):
    """A declared tree, `run -o` outside it, one applied edit — no accept yet."""
    from conftest import run_canned
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / ".killverbosity.json").write_text(DECL + "\n")
    src = tree / "report.md"
    src.write_text(DOC, encoding="utf-8")
    out = tmp_path / "outside" / "report.kv.md"
    out.parent.mkdir()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        run_canned(kv, monkeypatch, src, out, _one_edit(kv))
    ran = buf.getvalue()
    assert out.is_file(), f"the declared run produced no output: {ran[-600:]}"
    assert out.read_text() != DOC, (
        "the canned edit never landed, so every assertion below compares the "
        "file with itself:\n" + ran[-600:])
    return src, out, ran


@pytest.fixture
def declared(declared_run):
    """The same tree with `accept` already run over it."""
    from conftest import run_tool
    src, out, ran = declared_run
    said = run_tool("accept", src, out).stdout
    return src, out, said, ran


def test_a_declared_run_puts_the_baseline_beside_the_output_and_names_it_in_full(
        declared, kv):
    """The baseline now follows `-o`, not the input."""
    src, out, said, _ran = declared
    base = kv.baseline_path(src, out, explicit_out=True)
    assert base.parent == out.parent, "baseline_path did not follow -o"
    assert base.is_file(), "the declared run wrote no baseline beside -o"
    assert not src.with_suffix(f".orig{src.suffix}").is_file(), \
        "the baseline is still being written beside the input"
    clause = _baseline_clause(said)
    assert str(base) in clause, \
        f"the relocated baseline is not named in full: {clause!r}"
    assert GONE not in clause, \
        f"accept calls a file it can see gone: {clause!r}"


def test_a_legacy_baseline_beside_the_input_is_still_found(kv, tmp_path):
    """The SECOND candidate of `cmd_accept`'s lookup, driven directly."""
    from conftest import run_tool
    src = tmp_path / "tree" / "report.md"
    src.parent.mkdir()
    src.write_text("# T\n\nThe room was warm and the window faced the garden, "
                   "and the afternoon went by slowly.\n")
    out = tmp_path / "outside" / "report.kv.md"
    out.parent.mkdir()
    out.write_text("# T\n\nThe room was warm.\n")
    base = src.with_suffix(f".orig{src.suffix}")
    base.write_text(src.read_text())
    kv.write_run_record(out)
    assert not kv.baseline_path(src, out, explicit_out=True).exists()

    clause = _baseline_clause(run_tool("accept", src, out).stdout)
    assert base.name in clause, \
        f"accept did not find the legacy baseline beside the input: {clause!r}"
    assert GONE not in clause, \
        f"accept calls a file it can see gone: {clause!r}"


def test_the_current_layout_wins_over_a_legacy_one_when_both_exist(
        kv, tmp_path):
    """CONTROL for the order. Two baselines: the one this build actually
    writes today (`baseline_path`, follows `-o`) and one an older build
    left beside the input. The current one must win, or a rerun's own fresh
    baseline loses to a stale leftover from before the fix.
    """
    from conftest import run_tool
    src = tmp_path / "tree" / "report.md"
    src.parent.mkdir()
    src.write_text("# T\n\nThe room was warm and the window faced the garden, "
                   "and the afternoon went by slowly.\n")
    out = tmp_path / "outside" / "report.kv.md"
    out.parent.mkdir()
    out.write_text("# T\n\nThe room was warm.\n")
    current = kv.baseline_path(src, out, explicit_out=True)
    current.write_text(src.read_text())
    legacy = src.with_suffix(f".orig{src.suffix}")
    legacy.write_text(src.read_text())
    kv.write_run_record(out)

    clause = _baseline_clause(run_tool("accept", src, out).stdout)
    assert str(current) in clause, clause
    assert str(legacy) not in clause, \
        f"the legacy input-side baseline won over the current one: {clause!r}"


def test_the_ordinary_layout_is_still_named_by_bare_name(kv, monkeypatch, tmp_path):
    """CONTROL. An undeclared run, which is now the same layout as a declared
    one — so this is what says the notice is not what puts the baseline there.
    """
    from conftest import run_canned, run_tool
    src = tmp_path / "report.md"
    src.write_text(DOC, encoding="utf-8")
    out = tmp_path / "sidecar.kv.md"
    run_canned(kv, monkeypatch, src, out, _one_edit(kv))
    base = out.with_suffix(f".orig{src.suffix}")
    assert base.is_file(), "the undeclared run wrote no baseline beside the input"
    said = run_tool("accept", src, out).stdout
    clause = _baseline_clause(said)
    assert base.name in clause and str(base) not in clause, \
        f"the ordinary layout is being reported as a full path: {clause!r}"


def test_no_baseline_anywhere_still_says_gone(kv, tmp_path):
    """CONTROL. The message must not name a file that does not exist."""
    from conftest import run_tool
    src = tmp_path / "hand.md"
    out = tmp_path / "hand.kv.md"
    src.write_text("# T\n\nThe room was warm and the window faced the garden, "
                   "and the afternoon went by slowly.\n")
    out.write_text("# T\n\nThe room was warm.\n")
    kv.write_run_record(out)
    said = run_tool("accept", src, out).stdout
    clause = _baseline_clause(said)
    assert GONE in clause, f"accept invented a baseline: {clause!r}"


def test_the_declared_runs_own_accept_command_actually_works(declared_run):
    """The remedy the report prints, TYPED rather than grepped for."""
    from conftest import run_tool
    src, out, ran = declared_run
    line = next(l for l in ran.splitlines() if l.startswith("keep all of it:"))
    printed = shlex.split(line.split(":", 1)[1])
    assert printed[0] == "kill-verbosity", line
    assert printed[1] == "accept", line
    assert printed[2:] == [str(src), str(out)], line

    r = run_tool(*printed[1:])
    assert r.returncode == 0, \
        f"the command the report prints does not work: {r.stdout}{r.stderr}"
    assert src.read_text() == out.read_text(), \
        f"the printed command exited 0 and wrote nothing: {r.stdout}"


def test_dry_run_reports_what_accept_would_do_and_copies_nothing(kv, declared_run):
    """`accept --dry-run`: every check, the baseline path, the copy, no write."""
    from conftest import run_tool
    src, out, _ran = declared_run
    before = src.read_bytes()
    would_keep = src.with_suffix(f".copy1{src.suffix}")

    r = run_tool("accept", src, out, "--dry-run")
    assert r.returncode == 0, f"dry run did not exit 0: {r.returncode}\n{r.stdout}{r.stderr}"
    assert src.read_bytes() == before, "the dry run replaced the file"
    assert kv.run_record_path(out).is_file(), \
        "the dry run deleted the run record, so the real accept will refuse"
    assert out.with_suffix(f".orig{src.suffix}").name in r.stdout, \
        f"the dry run did not name the baseline:\n{r.stdout}"
    assert f"keeping {would_keep.name} as a copy" in r.stdout, \
        f"the dry run did not name the copy it would keep:\n{r.stdout}"
    assert not would_keep.exists(), "the dry run took the copy"
    assert "nothing was copied" in r.stdout, \
        "the dry run does not say it copied nothing"
    assert any(v in r.stdout for v in ("PASS", "REVIEW", "FAIL")), \
        f"the dry run printed no verify verdict, so it checked nothing:\n{r.stdout}"


def test_a_real_accept_still_writes(kv, monkeypatch, tmp_path):
    """CONTROL. Without it, a `--dry-run` that short-circuits every accept
    passes the test above and breaks the command.
    """
    from conftest import run_canned, run_tool
    src = tmp_path / "report.md"
    src.write_text(DOC, encoding="utf-8")
    out = tmp_path / "sidecar.kv.md"
    run_canned(kv, monkeypatch, src, out, _one_edit(kv))
    assert out.read_text() != DOC, "the canned edit never landed"
    r = run_tool("accept", src, out)
    assert r.returncode == 0, f"the real accept refused: {r.stdout}{r.stderr}"
    assert src.read_text() == out.read_text(), "the real accept did not write"
    assert "nothing was copied" not in r.stdout, \
        "the real accept claims it copied nothing"


def test_accept_writes_in_a_declared_tree_and_keeps_a_numbered_copy(
        kv, declared_run):
    """The ruling's own second half: *"'never refuse' also covers the case
    where accepting destroys the user's own file - make copy add suffix
    .copyX (1...)"*.
    """
    from conftest import run_tool
    src, out, _ran = declared_run
    edited = out.read_text()
    assert edited != DOC

    r1 = run_tool("accept", src, out)
    assert r1.returncode == 0, f"accept refused in a declared tree: " \
                               f"{r1.stdout}{r1.stderr}"
    assert src.read_text() == edited, "accept did not write the declared file"
    copy1 = src.with_suffix(f".copy1{src.suffix}")
    assert copy1.is_file(), f"no numbered copy was kept:\n{r1.stdout}"
    assert copy1.read_text() == DOC, \
        "the copy does not hold the text accept overwrote"
    assert copy1.read_text() != edited, \
        "the copy was taken AFTER the write, so it saved nothing"
    assert f"{src.name} → {copy1.name} (copy kept before the write)" \
        in r1.stdout, f"accept kept a copy and did not say where:\n{r1.stdout}"

    src.write_text(DOC, encoding="utf-8")
    kv.write_run_record(out)
    r2 = run_tool("accept", src, out)
    assert r2.returncode == 0, f"the second accept refused: {r2.stdout}{r2.stderr}"
    copy2 = src.with_suffix(f".copy2{src.suffix}")
    assert copy2.is_file(), f"the second accept reused a number:\n{r2.stdout}"
    assert copy2.read_text() == DOC, \
        "the second copy does not hold the text the second accept overwrote"
    assert copy1.read_text() == DOC, "the second accept overwrote the first copy"
    assert src.read_text() == edited, "the second accept did not write"


def test_the_numbered_copy_is_taken_in_an_undeclared_tree_too(
        kv, monkeypatch, tmp_path):
    """CONTROL. The copy is the protection the ruling put in place OF `accept`,
    not a leftover of the declaration handling.
    """
    from conftest import run_canned, run_tool
    src = tmp_path / "report.md"
    src.write_text(DOC, encoding="utf-8")
    out = tmp_path / "sidecar.kv.md"
    run_canned(kv, monkeypatch, src, out, _one_edit(kv))
    edited = out.read_text()
    assert edited != DOC

    r = run_tool("accept", src, out)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    copy1 = src.with_suffix(f".copy1{src.suffix}")
    assert copy1.is_file(), f"no copy in an undeclared tree:\n{r.stdout}"
    assert copy1.read_text() == DOC, "the copy does not hold the overwritten text"
