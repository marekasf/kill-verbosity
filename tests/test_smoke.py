"""Can the tool start at all."""

import json
import re

import pytest
from conftest import REPO, run_tool

SUBCOMMANDS = ["plan", "run", "verify", "accept", "crosscheck", "selftest"]


pytestmark = pytest.mark.smoke


def test_launcher_runs():
    r = run_tool("--help")
    assert r.returncode == 0, r.stderr
    assert "kill-verbosity" in r.stdout


@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_every_subcommand_parses(sub):
    r = run_tool(sub, "--help")
    assert r.returncode == 0, f"{sub} --help failed: {r.stderr}"
    assert "usage:" in r.stdout


def test_runs_through_a_relative_symlink(symlinked_launcher):
    """The way it actually ships."""
    r = run_tool("--help", binary=symlinked_launcher)
    assert r.returncode == 0, r.stderr
    assert "ModuleNotFoundError" not in r.stderr


@pytest.mark.skipif(not hasattr(__import__("sys"), "stdlib_module_names"),
                    reason="needs sys.stdlib_module_names (Python 3.10+)")
def test_the_tool_imports_only_the_standard_library():
    """The tool ships with no dependencies, so any import outside the
    standard library is a crash on someone else's machine."""
    import subprocess
    import sys

    probe = (
        "import sys, json;"
        "outside = lambda: {"
        "  n.split('.')[0] for n, m in sys.modules.items()"
        "  if n.split('.')[0] not in sys.stdlib_module_names"
        "  and n.split('.')[0] != 'killverbosity'};"
        "before = outside();"
        f"sys.path.insert(0, {str(REPO)!r});"
        "import killverbosity._legacy;"
        "print(json.dumps(sorted(outside() - before)))"
    )
    r = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [], (
        f"importing the tool pulls in {r.stdout.strip()}, which is not in "
        "the standard library"
    )


def test_every_shipped_profile_loads_and_compiles(kv, tmp_path):
    """A hand-written profile with a bad regex fails here, not mid-run."""
    profiles = sorted(kv.PROFILE_DIR.glob("*.json"))
    assert profiles, f"no profiles found in {kv.PROFILE_DIR}"
    doc = tmp_path / "readme.md"
    doc.write_text((REPO / "SKILL.md").read_text())
    cfg = tmp_path / ".killverbosity.json"
    for p in profiles:
        cfg.write_text(json.dumps({"profile": p.stem}))
        r = run_tool("plan", doc, "--json")
        assert r.returncode == 0, f"profile {p.stem} failed to load: {r.stderr}"


def test_plan_emits_parseable_json(doc):
    f = doc("# Title\n\nIt is worth noting that the check is missing.\n")
    r = run_tool("plan", f, "--json")
    assert r.returncode == 0, r.stderr
    json.loads(r.stdout)


def test_verify_refuses_the_same_file_twice(doc):
    """It needs an untouched original, so both paths being one file is an error
    and not a pass."""
    f = doc("# Title\n\nSome prose here.\n")
    r = run_tool("verify", f, f)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)


CLI_SURFACE = {
    "plan": {"--json", "--chat", "--full", "--no-reorder"},
    "run": {"-o", "--out", "--agent", "--any-agent", "--timeout",
            "--job-timeout", "--no-budget", "--dry-run", "--chat", "--full",
            "--no-reorder", "--no-agents"},
    "verify": {"--chat", "--full", "--in-place"},
    "accept": {"--chat", "--full", "--dry-run"},
    "crosscheck": {"--context", "--full", "--backend"},
    "selftest": {"--full"},
}


@pytest.mark.parametrize("cmd", sorted(CLI_SURFACE))
def test_the_command_takes_exactly_these_options(cmd):
    r = run_tool(cmd, "--help")
    assert r.returncode == 0, r.stderr
    found = {
        m
        for m in re.findall(r"(?<![\w-])--?[a-z][\w-]*", r.stdout)
        if m not in ("-h", "--help")
    }
    assert found == CLI_SURFACE[cmd], f"{cmd}: {found ^ CLI_SURFACE[cmd]}"


def test_the_project_file_is_found_from_the_document_not_the_shell(tmp_path):
    """A document's kind is a property of the document. The same file read from
    its own folder and from the repository root has to score the same way."""
    deep = tmp_path / "docs" / "policies"
    deep.mkdir(parents=True)
    (tmp_path / ".killverbosity.json").write_text('{"profile": "es"}')
    doc = deep / "p.md"
    doc.write_text("# Politica\n\nEl equipo revisa cada despliegue.\n")

    r = run_tool("plan", doc, cwd=str(tmp_path.parent))

    assert "profile es" in r.stderr, r.stderr


def test_an_unknown_key_in_the_project_file_is_named(tmp_path):
    """A key this build does not know is a typo, and the alternative to saying
    so is a setting that silently does nothing."""
    (tmp_path / ".killverbosity.json").write_text('{"profil": "es"}')
    doc = tmp_path / "p.md"
    doc.write_text("# T\n\nThe team reviews each deployment.\n")

    r = run_tool("plan", doc)

    assert r.returncode == 2
    assert "'profil'" in r.stderr or "profil" in r.stderr, r.stderr


DOC = "# T\n\nSome prose here that is long enough to be a document, with words.\n"


def test_an_input_named_like_an_output_is_warned_about(tmp_path):
    """`doc.kv.md` is matched by the `*.md` that found `doc.md`."""
    (tmp_path / "doc.kv.md").write_text(DOC)

    r = run_tool("run", tmp_path / "doc.kv.md", "--dry-run")

    assert "looks like another run's output" in r.stderr
    assert "doc.kv.kv.md" in r.stderr


def test_an_ordinary_input_is_not_warned_about(tmp_path):
    """The control. A warning on every correct run is one nobody reads, and it
    would fire on the common case: the tool is normally pointed at `doc.md`.
    """
    (tmp_path / "doc.md").write_text(DOC)

    r = run_tool("run", tmp_path / "doc.md", "--dry-run")

    assert r.returncode == 0, r.stderr
    assert "looks like another run's output" not in r.stderr
