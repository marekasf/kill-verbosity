"""Every flag a shipped document presents as usable is a flag the CLI accepts."""

import re

import pytest

from conftest import REPO, run_tool

SKILL = REPO / "SKILL.md"
SHIPPED = [SKILL, *sorted((REPO / "docs").glob("*.md"))]

FLAG = re.compile(r"`(--?[a-zA-Z][-a-zA-Z0-9]*)")

FOREIGN = {
    "--add-dir": "an agent CLI's flag, quoted where the docs show how agy is run",
    "--sandbox": "an agent CLI's flag, quoted where the docs show how codex "
                 "and agy are run",
    "--tools": "claude's flag, quoted where the docs show how claude is run",
}



def _help(*args):
    """`--help` for a command, or for the program when called with none."""
    r = run_tool(*args, "--help")
    return r.stdout + r.stderr


def _commands():
    """The subcommands, read out of the parser's own choice list."""
    m = re.search(r"\{([a-z][a-z,]*)\}", _help())
    return sorted(m.group(1).split(",")) if m else []


@pytest.fixture(scope="module")
def commands():
    return _commands()


@pytest.fixture(scope="module")
def promised():
    """The flag table in SKILL.md, keyed by flag, valued by its whole row."""
    out = {}
    for row in SKILL.read_text(encoding="utf-8").splitlines():
        if not row.startswith("| `-"):
            continue
        cells = [c.strip() for c in row.strip("|").split("|")]
        m = FLAG.search(cells[0])
        if m:
            out[m.group(1)] = row
    return out


def _cli_flags(commands):
    out = set()
    for cmd in [None, *commands]:
        out |= set(re.findall(r"(--[a-zA-Z][-a-zA-Z0-9]*)",
                              _help(*([cmd] if cmd else []))))
    return out


@pytest.fixture(scope="module")
def cli_flags(commands):
    return _cli_flags(commands)




def test_the_parser_still_names_its_commands(commands):
    """A floor and not an equality: a command added on purpose must not go
    red, and a choice list that stops parsing drops to zero."""
    assert len(commands) >= 6, (
        "read only %d subcommand(s) out of the top-level --help: %r. The choice "
        "list is not being parsed, so every flag set below is built from the "
        "wrong help text." % (len(commands), commands))


def test_the_doc_still_has_a_flag_table(promised):
    """A floor, so a broken row reader cannot sweep over nothing."""
    assert len(promised) >= 13, (
        "found only %d flags in %s; the row reader is broken, not the doc"
        % (len(promised), SKILL.name))


def test_the_flag_reader_finds_something(cli_flags):
    """A floor on the long flags read out of every command's `--help`."""
    assert len(cli_flags) >= 15, (
        "read only %d flags out of --help: %r" % (len(cli_flags), sorted(cli_flags)))




def test_every_promised_flag_is_accepted_somewhere(promised, commands):
    """Where the row names the command, that command's `--help` must list it.
    Where it does not, any command will do — plus the program itself, which is
    where `--version` lives."""
    texts = {c: _help(c) for c in commands}
    program = _help()
    missing = []
    for flag, row in sorted(promised.items()):
        named = [c for c in texts if "`%s`" % c in row]
        where = {c: texts[c] for c in named} or texts
        if not any(flag in t for t in where.values()) and flag not in program:
            missing.append("%s (looked in %s)"
                           % (flag, ", ".join(sorted(where)) or "every command"))
    assert not missing, \
        "SKILL.md promises flags the CLI does not accept: " + "; ".join(missing)



RETRACTED = re.compile(
    r"does not exist|no longer|removed|was `|rejected|not a flag|hallucinat"
    r"|invalid|unrecognized|unrecognised|dropped|never existed|deleted|gone"
    r"|is a finding|does not accept",
    re.I)

BANNER = re.compile(
    r"historical|not documentation|no longer current|superseded|out of date"
    r"|dated .{0,40}report",
    re.I)
BANNER_HEAD = 15

AUTHORITATIVE = [SKILL, REPO / "docs" / "user-guide.md"]


def _logical_lines(text):
    """These documents wrap at 80 columns, so a LINE is not a claim. Reading by
    line put "`--no-timeout` in" and "any output is a finding." in different
    units and lost the retraction between them. Join a wrapped continuation back
    onto the line it belongs to before reading either."""
    out = []
    for raw in text.splitlines():
        continuation = (out and raw[:1] in (" ", "\t") and raw.strip()
                        and not raw.lstrip().startswith(("-", "*", "|", "#", ">")))
        if continuation:
            out[-1] += " " + raw.strip()
        else:
            out.append(raw)
    return out


def _named(text):
    """Flags the document presents as usable: named in at least one claim that
    does not also say they are gone, and not another program's."""
    promised = set()
    for line in _logical_lines(text):
        if RETRACTED.search(line):
            continue
        promised |= set(re.findall(r"`(--[a-zA-Z][-a-zA-Z0-9]*)", line))
    return promised - set(FOREIGN)


def _declares_itself_history(text):
    return any(line.lstrip().startswith(">") and BANNER.search(line)
               for line in text.splitlines()[:BANNER_HEAD])


def _ghosts(text, cli_flags):
    return sorted(_named(text) - cli_flags)


def test_every_declared_foreign_flag_is_still_named(cli_flags):
    """An exclusion for something no document says is a reason with nothing
    under it. A foreign flag the CLI has since grown needs its exclusion
    deleted, or the docs' use of it stops being checked."""
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in SHIPPED)
    for flag, why in sorted(FOREIGN.items()):
        assert re.search(r"`%s(?![-a-zA-Z0-9])" % re.escape(flag), text), (
            "FOREIGN declares %s (%s) and no shipped document names it — delete "
            "the entry" % (flag, why))
        assert flag not in cli_flags, (
            "FOREIGN excuses %s as another program's, and this CLI now accepts "
            "it — delete the entry" % flag)


def test_an_authoritative_doc_names_no_flag_the_cli_rejects(cli_flags):
    """SKILL.md and the user guide cannot buy silence with a history banner: a
    reader who arrives at a user guide holding a task types what it shows."""
    for path in AUTHORITATIVE:
        name = path.name
        assert path.exists(), "%s is not shipped any more; re-decide what is " \
                              "authoritative rather than skipping it" % name
        ghosts = _ghosts(path.read_text(encoding="utf-8", errors="replace"),
                         cli_flags)
        assert not ghosts, "%s names flags the CLI rejects: %s" % (
            name, ", ".join(ghosts))


def test_a_doc_naming_a_dead_flag_declares_itself_history(cli_flags):
    """Every other shipped document."""
    offenders = []
    for path in SHIPPED:
        if path in AUTHORITATIVE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ghosts = _ghosts(text, cli_flags)
        if ghosts and not _declares_itself_history(text):
            offenders.append("%s (%s)" % (path.relative_to(REPO),
                                          ", ".join(ghosts)))
    assert not offenders, (
        "these name flags the CLI rejects and do not declare themselves history "
        "in their first %d lines:\n  " % BANNER_HEAD + "\n  ".join(offenders))


def test_the_banner_reader_can_say_both_words(cli_flags, tmp_path):
    """The control, and the only thing separating the test above from a
    predicate that answers "bannered" to everything."""
    dead = "--no-such-flag"
    assert dead not in cli_flags
    body = "# probe\n\nRun it with `%s`.\n" % dead

    bare = tmp_path / "bare.md"
    bare.write_text(body)
    assert _ghosts(bare.read_text(), cli_flags) == [dead]
    assert not _declares_itself_history(bare.read_text()), \
        "BANNER matches a document with no banner in it"

    with_banner = tmp_path / "bannered.md"
    with_banner.write_text(
        "> Historical report, not documentation: flags below may be gone.\n\n"
        + body)
    assert _declares_itself_history(with_banner.read_text()), \
        "BANNER does not match a history banner"
