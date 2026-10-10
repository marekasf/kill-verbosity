"""`targets` scopes a `.killverbosity.json` declaration's `profile`/`specialists`
to the documents it names, the same way `refuse.paths` scopes a refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_tool

DOC = "# Title\n\nThis is a document that is, in point of fact, quite verbose.\n"


def _tree(tmp_path, declaration):
    (tmp_path / ".killverbosity.json").write_text(json.dumps(declaration))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text(DOC)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "b.md").write_text(DOC)
    return tmp_path


def _declared(stderr) -> bool:
    return "— profile general" in stderr


def test_a_document_matching_a_target_is_declared(tmp_path):
    """The matching case. `notes/*.md` names `notes/a.md`, so the profile in
    the same declaration governs it.
    """
    root = _tree(tmp_path, {"profile": "general", "targets": ["notes/*.md"]})

    r = run_tool("plan", root / "notes" / "a.md")
    assert r.returncode == 0, r.stderr + r.stdout
    assert _declared(r.stderr), r.stderr
    assert f"config: {(root / '.killverbosity.json').resolve()}" in r.stderr, \
        r.stdout


def test_a_document_matching_no_target_is_not_declared(tmp_path):
    """CONTROL for the match above and the defect `targets` exists to fix:
    without scoping, this declaration covered `other/b.md` too. With `targets`
    naming only `notes/*.md`, a document elsewhere under the same tree reads
    as undeclared — not merely un-refused, genuinely as if the file were not
    there — and no other `.killverbosity.json` exists above it here.
    """
    root = _tree(tmp_path, {"profile": "general", "targets": ["notes/*.md"]})

    r = run_tool("plan", root / "other" / "b.md")
    assert r.returncode == 0, r.stderr + r.stdout
    assert not _declared(r.stderr), r.stderr
    assert "none declared" in r.stderr, r.stderr


def test_a_document_matching_no_target_still_finds_an_outer_declaration(
        tmp_path):
    """The other half of `refuse`'s own rule, carried over: a declaration that
    does not apply is not a wall. The search continues upward past it to the
    next `.killverbosity.json`, exactly as it would if the inner file did not
    exist at all.
    """
    root = _tree(tmp_path, {"profile": "general", "targets": ["notes/*.md"]})
    (root.parent / ".killverbosity.json").write_text(
        json.dumps({"profile": "clinical"}))
    try:
        r = run_tool("plan", root / "other" / "b.md")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "— profile clinical" in r.stderr, r.stderr
        assert str((root.parent / ".killverbosity.json").resolve()) \
            in r.stderr, r.stderr
    finally:
        (root.parent / ".killverbosity.json").unlink()


def test_targets_absent_is_todays_behaviour_exactly(tmp_path):
    """No `targets` key: the declaration covers the whole tree, unchanged."""
    root = _tree(tmp_path, {"profile": "general"})

    for doc in (root / "notes" / "a.md", root / "other" / "b.md"):
        r = run_tool("run", doc, "--no-agents")
        assert r.returncode == 0, r.stderr + r.stdout
        assert _declared(r.stderr), (doc, r.stderr)


def test_targets_scope_specialists_too(tmp_path):
    """`specialists`, not only `profile`, is governed by `targets` — the
    declaration names one setting or the other, and both are in scope or
    neither is."""
    root = _tree(tmp_path, {"specialists": ["noise"],
                            "targets": ["notes/*.md"]})

    inside = run_tool("run", root / "notes" / "a.md", "--no-agents")
    assert "specialists noise" in inside.stderr, inside.stderr

    outside = run_tool("run", root / "other" / "b.md", "--no-agents")
    assert "specialists noise" not in outside.stderr, outside.stderr


def test_targets_is_relative_to_the_declaring_file(tmp_path):
    """Same convention as `refuse.paths`: globs are relative to the directory
    holding `.killverbosity.json`, not to the process's working directory."""
    root = _tree(tmp_path, {"profile": "general", "targets": ["notes/*.md"]})

    r = run_tool("run", root / "notes" / "a.md", "--no-agents", cwd=str(root))
    assert _declared(r.stderr), r.stderr


def test_an_empty_targets_list_is_refused(tmp_path):
    """A malformed declaration is refused with a message naming `targets`,
    the same discipline every other key in this file gets."""
    root = _tree(tmp_path, {"profile": "general", "targets": []})

    r = run_tool("plan", root / "notes" / "a.md")
    assert r.returncode == 2, r.stderr + r.stdout
    assert "targets" in r.stderr, r.stderr


def test_a_non_string_target_is_refused(tmp_path):
    root = _tree(tmp_path, {"profile": "general", "targets": ["notes/*.md", 3]})

    r = run_tool("plan", root / "notes" / "a.md")
    assert r.returncode == 2, r.stderr + r.stdout
    assert "targets" in r.stderr, r.stderr
