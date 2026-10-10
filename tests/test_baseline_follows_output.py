"""every side file follows `-o`, not the input."""

from __future__ import annotations

from conftest import run_tool

DOC = (
    "# Notes\n\n| id | state |\n|---|---|\n| C1 | done |\n\n"
    "This paragraph is, in point of fact, considerably longer than it "
    "strictly needs to be, and it leverages a number of things.\n"
)


def test_baseline_follows_the_output_directory_not_the_inputs(tmp_path):
    input_dir = tmp_path / "input_dir"
    input_dir.mkdir()
    out_dir = tmp_path / "out_dir"
    out_dir.mkdir()
    src = input_dir / "note.md"
    src.write_text(DOC)
    before = {p.name for p in input_dir.iterdir()}

    out = out_dir / "note.kv.md"
    r = run_tool("run", src, "-o", out, "--no-agents")
    assert r.returncode in (0, 3), (r.returncode, r.stdout, r.stderr)

    after = {p.name for p in input_dir.iterdir()}
    assert after == before, (
        f"the input's directory gained file(s) even though -o pointed "
        f"elsewhere: {after - before}")

    assert out.is_file(), "the output itself must still land at -o"
    baseline = out_dir / "note.kv.orig.md"
    assert baseline.is_file(), (
        "the baseline must follow -o's directory and name, not the input's")
    assert baseline.read_text() == DOC


def test_two_inputs_of_the_same_name_do_not_collide_on_one_baseline(tmp_path):
    """The round-two regression: two SOURCE files sharing a
    basename, each given a distinct `-o` in the same output directory, must
    not derive the same baseline name from `src` alone -- or the second run's
    baseline silently fails to distinguish itself from the first's, and
    `accept` on the second run's output resolves the FIRST run's untouched
    copy (measured live: held ALPHA while accepting BETA).
    """
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    src_a = dir_a / "doc.md"
    src_b = dir_b / "doc.md"
    src_a.write_text(DOC)
    src_b.write_text(DOC.replace("considerably longer", "rather longer"))

    out_a = out_dir / "a.kv.md"
    out_b = out_dir / "b.kv.md"
    ra = run_tool("run", src_a, "-o", out_a, "--no-agents")
    rb = run_tool("run", src_b, "-o", out_b, "--no-agents")
    assert ra.returncode in (0, 3), (ra.returncode, ra.stdout, ra.stderr)
    assert rb.returncode in (0, 3), (rb.returncode, rb.stdout, rb.stderr)

    base_a, base_b = out_dir / "a.kv.orig.md", out_dir / "b.kv.orig.md"
    assert base_a.is_file(), "run A wrote no baseline of its own"
    assert base_b.is_file(), "run B wrote no baseline of its own"
    assert base_a.read_text() == src_a.read_text(), \
        "run A's baseline was overwritten or never held its own text"
    assert base_b.read_text() == src_b.read_text(), \
        "run B's baseline is not run B's own original text -- the collision"

    r = run_tool("accept", src_b, out_b, "--dry-run", force=True)
    clause = next(l for l in r.stdout.splitlines()
                  if "The text before the first run" in l)
    assert str(base_b) in clause, \
        f"accept resolved the wrong baseline for run B: {clause!r}"
    assert str(base_a) not in clause, \
        f"accept on B's output named A's baseline instead: {clause!r}"


def test_accept_still_finds_the_relocated_baseline(tmp_path):
    """`accept`'s own baseline lookup must agree with where `run` wrote it."""
    input_dir = tmp_path / "input_dir"
    input_dir.mkdir()
    out_dir = tmp_path / "out_dir"
    out_dir.mkdir()
    src = input_dir / "note.md"
    src.write_text(DOC)
    out = out_dir / "note.kv.md"
    run_tool("run", src, "-o", out, "--no-agents")

    r = run_tool("accept", src, out, "--dry-run", force=True)
    assert r.returncode in (0, 4), (r.returncode, r.stdout, r.stderr)
    assert "gone unless git has it" not in r.stdout, (
        "accept could not find the baseline run just wrote: " + r.stdout)
