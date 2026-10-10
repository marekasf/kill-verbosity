# Known issues

Open problems an outside user can hit, each with what to do about it. See also
the [user guide](user-guide.md) and [how it works](how-it-works.md). If you hit
something not listed here, report it with the document, the agent, the exact
command, what the tool printed, and what you expected instead.

## Platform and agents

- **The Windows code path has never run on a Windows host.** Three Windows paths
  were tested only on macOS and Linux: killing a timed-out job's process tree
  with `taskkill /T /F`, resolving an agent CLI installed as a `.cmd` shim, and
  the launcher's re-exec under `-X utf8` on a non-UTF-8 code page. What to do:
  first run `python kill-verbosity selftest`, then `plan` on a real document, and
  report the output either way.

- **The `agy` agent was not exercised end to end in the release build.** Only
  `codex` and `claude` ran against real documents. The `agy` invocation
  (stream-json over stdin, `--sandbox`) never ran against a real `agy` install.
  What to do: try `run --agent agy --dry-run`, then a run on a small file, before
  relying on it; if it fails, `--agent codex` or `--agent claude` is the tested
  path.

- **`run` costs money or quota for every specialist call.** A run sends one call
  per job in the job matrix, and a long document can mean dozens; a fallback to
  another installed agent spends that agent's quota too. What to do: run `plan`
  or `run --dry-run` first to see the job count, and keep `--timeout` and the
  default budget on. Re-running a killed run with the same command replays
  finished jobs from the `.kvjournal` file without paying for them again.

- **Only installation is checked, not login or quota.** An agent on `PATH` but
  signed out or out of quota counts as available, so it fails later as a failed
  job (or a failed reviewer in `crosscheck`), not up front. What to do: check
  that each agent CLI answers a trivial prompt on its own before a long run.

## What the checks cannot see

- **The tool matches text, not meaning.** It cannot see "X causes Y" turned into
  "X does not cause Y", and it cannot protect a fact that carries no number,
  path, link or identifier. A rule stated in the indicative ("Rollback is
  manual.") is not held as a rule, only modal wording is. What to do: read the
  diff; `verify` names the sentence shapes it did not compare.

- **A dated record whose date and actor are on different lines is missed.** Shape
  detection reads one line at a time, so a sentence hard-wrapped between the date
  and the "by ..." part does not fire the `worklog` shape. The same holds for
  every shape. What to do: unwrap paragraphs before running, or check wrapped
  history paragraphs by hand.

- **Dated records of renames and refactors fire only when they name an actor.**
  `rewritten`, `renamed`, `refactored`, `reverted`, `split` and `moved` are not
  on the completion-verb list. What to do: check such lines by hand.

- **A number followed by a word starting with a month abbreviation reads as a
  date.** "20 markdown files", "3 decades", "12 marginal cases" and "4 junctions"
  all fire `worklog`, which is a deletion shape. What to do: add
  `<!-- kv:keep -->` to the line, or `<!-- kv:allow-shape worklog -->` if the
  file has many of them.

- **Some shapes cannot tell a word's subject use from its opinion use.**
  `process leak` cannot separate a document that leaks process from one about
  process, and `evaluative adjective` fires on `flaky` and `clean` used as exact
  technical terms. What to do: `<!-- kv:allow flaky, clean -->` or
  `<!-- kv:allow-shape process leak -->`.

- **A low shape score does not mean a section belongs in the file.** Detectors
  count sentence shapes, so a long worklog with none of them scores low. What to
  do: judge whether a section should exist at all yourself.

- **A restatement in new words is not flagged as an echo.** The echo shape works
  off phrase lists. What to do: look for repeated paragraphs by hand.

- **Table rows that read alike can hide a gutted row.** A lost claim is looked
  for anywhere in the file, so a near-identical neighbour row can match it. A
  cell that loses only a citation such as `(C270)` is also silent. What to do:
  protect tables whose rows must not change with `freeze.lines` (see the user
  guide).

- **`verify` reports a move as a loss.** Splitting one document into two reports
  every token that went to the other file as gone. What to do: concatenate the
  parts and verify the original against that.

- **Two word pairs can match as the same word**: "seed" with "seeing", "suited"
  with "suite". This can only hide a deletion when the surviving sentence already
  keeps every number, path and identifier and most of the content words. What to
  do: nothing; read the diff as usual.

## Results that look like bugs but are not

- **A run lands at about 1.2 times the target.** That is normal and the report
  says so. A run past 1.5x is worth reporting, with the diff.

- **A section that is still in the file is listed under
  `headings gone or renamed`.** A section renamed and rewritten in one run cannot
  be told from a deleted one. Each row says whether its protected tokens are
  still in the file: if they are, find the section under its new name.

- **A heading is left with nothing under it.** `noise` may empty a section but
  never delete its heading; removing the heading is `structure`'s job.

- **A reword drops a protected token** that is stated elsewhere in the file.
  `verify` compares the whole file, so that is allowed.

- **A pipe hides the exit code.** `verify orig.md new.md | tail` exits with
  `tail`'s status. Redirect to a file and check `$?` instead.

- **Exit 2 with one line is a usage problem** (a misspelled marker, a file that
  is already short enough, a specialist that does not run on this kind of
  document). Fix it and rerun. A Python traceback is a bug; report it whole.
