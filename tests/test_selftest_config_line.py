"""`selftest`'s wiring fixture prints a `config:` line that reads as a
statement about the reader's own tree.
"""

from conftest import run_tool


def test_selftest_does_not_print_a_bare_fixture_config_line():
    r = run_tool("selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    combined = r.stdout + r.stderr
    for line in combined.splitlines():
        assert line.strip() != "config: /p/.killverbosity.json", (
            "selftest printed the fixture's config line unprefixed, in the "
            "same form as a real per-file config line:\n" + combined
        )
