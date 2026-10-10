"""Three findings from an outside session reading real reports, plus one the
check for them turned up.
"""

from __future__ import annotations

from conftest import run_tool

BODY = "\n\n".join(
    ["This paragraph carries ordinary prose about the system and its "
     "behaviour in some detail for the reader."] * 40
)
IDS = ("# Title\n\n" + BODY +
       "\n\n## Section\n\nThe round-8 failure was never explained anywhere. "
       "The round-3 failure likewise.\n")

NOTE = "matched against this build's default id families"



def test_the_rendering_sense_of_solid_no_longer_fires(kv):
    rx = kv.EXISTENCE["evaluative adjective"]
    for probe in ("Use a solid line for measured data.",
                  "The border is solid, not dashed.",
                  "solid fill under the curve.",
                  "The table uses a solid rule between rows."):
        assert not rx.search(probe), probe


def test_the_known_miss_is_real_and_is_the_price(kv):
    """Stated rather than fixed, so the trade is visible in a test and not only
    in a comment: this IS the lazy verdict the rule was built for."""
    assert not kv.EXISTENCE["evaluative adjective"].search("The design is solid.")


def test_the_rest_of_the_list_and_its_noun_exceptions_are_untouched(kv):
    """The control. Dropping one alternative from a shared pattern is one edit
    away from emptying the rule, and every assertion above is satisfied by a
    regex that matches nothing at all."""
    rx = kv.EXISTENCE["evaluative adjective"]
    for fires in ("The parser is brittle.", "The API is weak.",
                  "The tests are flaky."):
        assert rx.search(fires), fires
    for exempt in ("A weak crypto suite.", "A clean checkout is required."):
        assert not rx.search(exempt), exempt



def test_an_untuned_tree_is_told_the_vocabulary_is_tunable(doc):
    out = run_tool("plan", doc(IDS), "--full").stdout
    assert "bare internal id 2" in out
    assert NOTE in out
    assert "`id_families`" in out
    assert ".killverbosity.json" in out
    assert "resolves against that file" in out


def test_the_default_plan_report_says_it_in_one_line(doc):
    out = run_tool("plan", doc(IDS)).stdout
    assert "bare internal id 2" in out
    assert NOTE in out
    assert "--full" in out
    assert "`id_families`" not in out
    assert "resolves against that file" not in out


def test_it_is_said_ONCE_however_many_hits_there_are(doc):
    out = run_tool("plan", doc(IDS)).stdout
    assert out.count(NOTE) == 1, out.count(NOTE)


def test_it_sits_in_the_header_beside_the_census_not_at_the_tail(doc):
    """The one measurement of who reads this report found an agent acting on the
    blocks that refused something and touching none of the document-level blocks
    at the tail. A footer here would be the correct sentence in the one place it
    is known not to be read."""
    lines = run_tool("plan", doc(IDS)).stdout.splitlines()
    census = next(i for i, ln in enumerate(lines) if ln.startswith("shapes:"))
    note = next(i for i, ln in enumerate(lines) if NOTE in ln)
    first_chunk = next(i for i, ln in enumerate(lines) if ln.startswith("── "))
    assert census < note < first_chunk, (census, note, first_chunk)


def test_a_tree_that_has_ALREADY_tuned_id_families_is_not_lectured(doc, tmp_path):
    """The control, and the half that decides whether this is a note or noise."""
    p = doc(IDS)
    (tmp_path / "kv.json").write_text(
        '{"name": "added", "id_families": {"add": ["ZZ-\\\\d+"]}}\n')
    (tmp_path / ".killverbosity.json").write_text('{"profile": "./kv.json"}\n')
    out = run_tool("plan", p).stdout
    assert "bare internal id 2" in out, out
    assert NOTE not in out, out


def test_a_clean_document_says_nothing_about_id_families(doc):
    out = run_tool("plan", doc("# Title\n\n" + BODY + "\n\n## Section\n\n"
                               + BODY + "\n")).stdout
    assert NOTE not in out



def test_a_relative_profile_path_resolves_from_ANY_directory(doc, tmp_path):
    """The declaration means the same thing wherever the tool is invoked from,
    which is why the search for it runs from the DOCUMENT and not the working
    directory. `refuse`'s globs already held this."""
    p = doc(IDS)
    (tmp_path / "kv.json").write_text('{"name": "mine"}\n')
    (tmp_path / ".killverbosity.json").write_text('{"profile": "./kv.json"}\n')
    from_own = run_tool("plan", "doc.md", cwd=tmp_path)
    from_elsewhere = run_tool("plan", p, cwd=tmp_path.parent)
    for r in (from_own, from_elsewhere):
        assert r.returncode == 0, r.stderr
        assert "profile mine" in r.stderr, r.stderr
    assert "no profile at" not in from_elsewhere.stderr


def test_a_shipped_profile_NAME_is_still_a_name_and_not_a_path(doc, tmp_path):
    """The control. Resolving every value against the declaring file would turn
    `{"profile": "legal"}` into a path that does not exist."""
    p = doc(IDS)
    (tmp_path / ".killverbosity.json").write_text('{"profile": "legal"}\n')
    r = run_tool("plan", p, cwd=tmp_path.parent)
    assert r.returncode == 0, r.stderr
    assert "profile legal" in r.stderr, r.stderr


def test_a_missing_relative_profile_names_the_path_it_looked_in(doc, tmp_path):
    """The absence path. It said `no profile at kv.json` and listed the shipped
    names, which reads as "yours does not exist" rather than "I looked in the
    wrong place"."""
    p = doc(IDS)
    (tmp_path / ".killverbosity.json").write_text('{"profile": "./gone.json"}\n')
    r = run_tool("plan", p, cwd=tmp_path.parent)
    assert r.returncode == 2
    assert str(tmp_path / "gone.json") in r.stderr, r.stderr
