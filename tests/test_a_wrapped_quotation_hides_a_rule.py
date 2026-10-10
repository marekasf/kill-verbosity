"""A rule inside a WRAPPED quotation
could be deleted outright and `verify` said PASS, exit 0. Both gates were
blind at once, and neither one alone.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest
from conftest import REPO, run_tool

pytestmark = pytest.mark.regression

RULE = "Never deploy on a Friday without the on-call engineer signing off."

BARE = """# Deployment notes

The service runs behind the proxy and reads its config at boot.

%s

Rollbacks are one command and are logged to the audit trail.
""" % RULE

LEAD_IN = """# Deployment notes

The service runs behind the proxy and reads its config at boot.

The policy states %s

Rollbacks are one command and are logged to the audit trail.
""" % RULE

QUOTED_SAME_LINE = """# Deployment notes

The service runs behind the proxy and reads its config at boot.

The policy states "%s"

Rollbacks are one command and are logged to the audit trail.
""" % RULE

QUOTED_WRAPPED = """# Deployment notes

The service runs behind the proxy and reads its config at boot.

The policy states "Never deploy on a Friday without the
on-call engineer signing off."

Rollbacks are one command and are logged to the audit trail.
"""


NAMELESS_QUOTE_ORIG = """# Working agreement

The rule is not negotiable. The policy states "never run git commit or git push without an
explicit, in-this-turn confirmation from the user for that exact action" and every
session here is bound by it, without exception of any kind whatsoever.

It is worth noting that, at this point in time, the team has generally agreed that
the above is the correct approach going forward.
"""

NAMELESS_QUOTE_EDIT = """# Working agreement

The rule is not negotiable. Every session here is bound by it.

The team agreed this is correct.
"""


BARE_WRAPPED_ORIG = """# Working agreement

Sessions must never run git commit or git push without an explicit confirmation given
in that same turn, and this applies to every repository without exception of any kind.

It is worth noting that, at this point in time, the team has generally agreed that
the above is the correct approach going forward.
"""

BARE_WRAPPED_NEW = """# Working agreement

The team agreed this is correct.
"""

LEADIN_WRAPPED_ORIG = """# Working agreement

The policy states Sessions must never run git commit or git push without an explicit confirmation given
in that same turn, and this applies to every repository without exception of any kind.

It is worth noting that, at this point in time, the team has generally agreed that
the above is the correct approach going forward.
"""

LEADIN_WRAPPED_NEW = """# Working agreement

The team agreed this is correct.
"""

SAME_LINE_QUOTED_ORIG = """# Working agreement

The policy states "Sessions must never run git commit or git push without an explicit confirmation given in that same turn, and this applies to every repository without exception of any kind."

It is worth noting that, at this point in time, the team has generally agreed that
the above is the correct approach going forward.
"""

SAME_LINE_QUOTED_NEW = """# Working agreement

The team agreed this is correct.
"""


def _without_the_rule(text):
    return "\n".join(ln for ln in text.splitlines()
                     if "Friday" not in ln and "on-call engineer" not in ln) + "\n"


def _verify(tmp_path, orig, edit):
    o, n = tmp_path / "orig.md", tmp_path / "new.md"
    o.write_text(orig)
    n.write_text(edit)
    return run_tool("verify", o, n)


@pytest.mark.parametrize("name,doc", [
    ("bare", BARE),
    ("unquoted lead-in", LEAD_IN),
    ("quoted on one line", QUOTED_SAME_LINE),
    ("quoted and wrapped", QUOTED_WRAPPED),
])
def test_deleting_the_rule_fails_however_it_is_spelled(tmp_path, name, doc):
    """All four arms. The fourth is the defect; the other three are what says
    the fourth is not passing for some unrelated reason."""
    r = _verify(tmp_path, doc, _without_the_rule(doc))

    assert r.returncode == 1, "%s: %s" % (name, r.stdout)
    assert ("RULES LOST" in r.stdout or "QUOTATIONS LOST" in r.stdout), (
        "%s: %s" % (name, r.stdout))


def test_a_wrapped_quotation_that_survives_is_not_a_loss(tmp_path):
    """The wrapped-quotation control, re-run here: collecting the wrap must not cost the
    passing case. The author's own words around it are edited, the quotation
    is not."""
    edit = QUOTED_WRAPPED.replace("Rollbacks are one command and are logged",
                                  "Rollbacks are logged")
    r = _verify(tmp_path, QUOTED_WRAPPED, edit)

    assert "QUOTATIONS LOST" not in r.stdout, r.stdout


def test_a_wrapped_quotation_reflowed_onto_a_different_split_is_not_a_loss(
        tmp_path):
    """The one a shortening run actually produces. `cmd_verify` normalises
    whitespace on both sides, and the span is joined with single spaces here
    so it still matches when the wrap moves."""
    edit = QUOTED_WRAPPED.replace(
        'states "Never deploy on a Friday without the\non-call engineer signing off."',
        'states "Never deploy on a Friday\nwithout the on-call engineer signing off."')
    assert edit != QUOTED_WRAPPED, "the reflow rewrote nothing"
    r = _verify(tmp_path, QUOTED_WRAPPED, edit)

    assert "QUOTATIONS LOST" not in r.stdout, r.stdout


def test_dropping_only_the_continuation_line_is_a_loss(tmp_path):
    """Drop ONLY the wrapped
    continuation and leave the opening line standing. A shortening run
    produces this far more readily than the whole-quotation delete above --
    it looks like trimming a sentence -- and the span the original collected
    is nowhere in the edited file, so it is a loss even though both the
    opening words and the opening quote mark survive."""
    edit = QUOTED_WRAPPED.replace("\non-call engineer signing off.\"", "")
    assert edit != QUOTED_WRAPPED, "the edit removed nothing"
    r = _verify(tmp_path, QUOTED_WRAPPED, edit)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout


def test_the_wrapped_quotation_is_collected_as_one_span(kv):
    spans = [s for _ln, s in kv.quoted_claims(QUOTED_WRAPPED.splitlines())]

    assert spans == ['"%s"' % RULE], spans


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


def test_dropping_the_wrap_accumulator_loses_the_span_again(tmp_path):
    """The mutant: stop opening a pending span and the wrapped quotation is
    collected by nothing again, which is the state the peer measured."""
    mut = _mutant(tmp_path,
                  "            pending = (i, [ln[idx:].strip()]) if idx >= 0 else None",
                  "            pending = None")

    spans = [s for _ln, s in mut.quoted_claims(QUOTED_WRAPPED.splitlines())]

    assert spans == [], (
        "the mutant did not change behaviour, so it says nothing about the "
        "test: %r" % (spans,))


def test_a_nameless_wrapped_quotation_deleted_is_a_loss(tmp_path):
    """Fixture C (reviewer-implementer). The quotation gate ALONE has to catch
    this: there is no credited name to catch it by, and the surviving prose
    carries no rule wording for `RULES LOST` either."""
    r = _verify(tmp_path, NAMELESS_QUOTE_ORIG, NAMELESS_QUOTE_EDIT)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout


def test_the_same_deletion_with_a_credited_name_still_names_the_quotation(
        tmp_path):
    """Fixture B, and it is here to keep C honest rather than to add coverage."""
    orig = NAMELESS_QUOTE_ORIG.replace("The policy states", "Alex said")
    assert orig != NAMELESS_QUOTE_ORIG, "the name was not restored"
    r = _verify(tmp_path, orig, NAMELESS_QUOTE_EDIT)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout
    assert "Alex 1\u21920" in r.stdout, r.stdout


def test_a_bare_wrapped_rule_deleted_fails_rules_lost(tmp_path):
    """Fixture D (reviewer-implementer). No quotation anywhere in this
    document, so masking never touches the sentence -- `RULES LOST` alone has
    to catch it, and it has to catch it wrapped over two physical lines in
    the ORIGINAL, not only on one line the way BARE above is written."""
    r = _verify(tmp_path, BARE_WRAPPED_ORIG, BARE_WRAPPED_NEW)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout


def test_an_unquoted_leadin_wrapped_rule_deleted_fails_rules_lost(tmp_path):
    """Fixture F (reviewer-implementer). "The policy states" with no
    quotation marks at all is not an attribution `quoted_claims` or the
    credited-name check can see -- it is ordinary prose leading into a rule,
    still wrapped over two lines, and `RULES LOST` is the only gate in a
    position to catch it going."""
    r = _verify(tmp_path, LEADIN_WRAPPED_ORIG, LEADIN_WRAPPED_NEW)

    assert r.returncode == 1, r.stdout
    assert "RULES LOST" in r.stdout, r.stdout


def test_a_same_line_quoted_rule_deleted_fails_quotations_lost(tmp_path):
    """Fixture G (reviewer-implementer). The rule is inside quote marks, so
    `mask_quotes` blanks it before `RULES LOST` ever reads the sentence --
    `QUOTATIONS LOST` is the only gate that can see it go, and it has to see
    it on a single, unwrapped line, not only the wrapped case."""
    r = _verify(tmp_path, SAME_LINE_QUOTED_ORIG, SAME_LINE_QUOTED_NEW)

    assert r.returncode == 1, r.stdout
    assert "QUOTATIONS LOST" in r.stdout, r.stdout
