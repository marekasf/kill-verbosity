"""The middle of a WRAPPED quotation is not a quotation."""

from __future__ import annotations

import importlib.util
import sys

import pytest
from conftest import REPO, run_tool

pytestmark = pytest.mark.regression

ORIG = """# Policy

The standard says *"Quality is not a stage in the process and
verification should always occur"*, and its first prohibited use is generative AI *"Without Quality
assurance the release is a guess."*

The reviewer added *"a released defect costs ten times what a caught one does."*

Nothing else in this document is touched by the edits below, so the run has
only the paragraph named in each test to answer for.
"""

EDIT_PROSE = """# Policy

The standard says *"Quality is not a stage in the process and
verification should always occur"*, and its first use is generative AI *"Without Quality
assurance the release is a guess."*

The reviewer added *"a released defect costs ten times what a caught one does."*

Nothing else in this document is touched by the edits below, so the run has
only the paragraph named in each test to answer for.
"""

EDIT_CUT = """# Policy

The standard says *"Quality is not a stage in the process and
verification should always occur"*, and its first prohibited use is generative AI *"Without Quality
assurance the release is a guess."*

The reviewer agreed with the standard.

Nothing else in this document is touched by the edits below, so the run has
only the paragraph named in each test to answer for.
"""

FALSE_SPAN = '"*, and its first prohibited use is generative AI *"'
REAL_QUOTE = '"a released defect costs ten times what a caught one does."'
WRAPPED_ONE = ('"Quality is not a stage in the process and '
               'verification should always occur"')
WRAPPED_TWO = '"Without Quality assurance the release is a guess."'


def _verify(tmp_path, orig, edit):
    o, n = tmp_path / "orig.md", tmp_path / "new.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


def test_the_middle_of_a_wrapped_quotation_is_not_collected_as_one(kv):
    spans = [s for _ln, s in kv.quoted_claims(ORIG.splitlines())]

    assert FALSE_SPAN not in spans, spans
    assert spans == [WRAPPED_ONE, WRAPPED_TWO, REAL_QUOTE], spans


def test_editing_the_words_between_two_wrapped_quotations_is_not_a_loss(
        tmp_path):
    r = _verify(tmp_path, ORIG, EDIT_PROSE)

    assert "QUOTATIONS LOST" not in r.stdout, r.stdout
    assert "prohibited use is generative AI" not in r.stdout, r.stdout


def test_a_genuinely_deleted_quotation_is_still_a_hard_failure(tmp_path):
    """The control. The check still fails the run on a real loss."""
    r = _verify(tmp_path, ORIG, EDIT_CUT)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout
    assert "a released defect costs ten times" in r.stdout, r.stdout


def _mutant(tmp_path, old, new):
    """`_legacy.py` with one line replaced, loaded from a COPY in tmp_path."""
    src = (REPO / "killverbosity" / "_legacy.py").read_text()
    assert src.count(old) == 1, (
        "the mutation target is not in the source exactly once, so this "
        "mutant would test nothing: %r" % old)
    path = tmp_path / "mutant_legacy.py"
    path.write_text(src.replace(old, new))

    name = "kv_mutant_%s" % tmp_path.name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


def test_removing_the_carry_brings_the_false_quotation_back(tmp_path):
    """The mutant, on a copy: drop the carry and the repro test goes red."""
    mut = _mutant(tmp_path,
                  "scan, inside = quote_carry_head(ln, carry)",
                  "scan, inside = ln, False")

    spans = [s for _ln, s in mut.quoted_claims(ORIG.splitlines())]

    assert FALSE_SPAN in spans, (
        "the mutant did not change behaviour, so it says nothing about the "
        "test: %r" % (spans,))
