"""How long the whole run may take, and what is left of it."""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable

Clock = Callable[[], float]


class Budget:
    """Seconds the run may spend in total."""

    def __init__(self, total: float | None, clock: Clock = time.monotonic):
        self._clock = clock
        self._total = total
        self._start = clock()

    @property
    def total(self) -> float | None:
        return self._total

    def spent(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        if self._total is None:
            return float("inf")
        return max(0.0, self._total - self.spent())

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    STARVED_SHARE = 0.25

    def cap(self, ceiling: int) -> float:
        """The most any job in this run can ever get."""
        if self._total is None:
            return ceiling
        return min(ceiling, self._total)

    def starved(self, ceiling: int) -> bool:
        """True when too little is left for the job to be worth asking."""
        left = self.remaining()
        return left != float("inf") and \
            left < self.cap(ceiling) * self.STARVED_SHARE

    def job_timeout(self, ceiling: int) -> int:
        """What one job may take."""
        left = self.remaining()
        if left == float("inf"):
            return ceiling
        return max(1, int(min(ceiling, left)))


def waves(n_jobs: int, pool: int) -> int:
    """How many rounds of the pool the matrix takes."""
    if n_jobs <= 0 or pool <= 0:
        return 0
    return -(-n_jobs // pool)


def matrix_seconds(n_jobs: int, pool: int, ceiling: int) -> int:
    """Wall clock the matrix needs if every job runs its full ceiling."""
    return waves(n_jobs, pool) * ceiling


def matrix_note(n_jobs: int, pool: int, ceiling: int,
                total: float | None, slow: dict[str, int] | None = None) -> str:
    """What the run says when `--timeout` cannot cover the matrix, or ""."""
    if not total:
        return ""
    w = waves(n_jobs, pool)
    need = w * ceiling
    if need <= total:
        return ""
    lower = int(total) // w
    fix = f"raise --timeout to {need}"
    killed = sorted((j for j, s in (slow or {}).items() if s >= lower), key=lambda j: (-slow[j], j))
    if killed:
        fix += (f" (lowering --job-timeout to {lower} is not offered: "
                f"{killed[0]} already timed out at {slow[killed[0]]}s"
                + (f", and {len(killed) - 1} more" if len(killed) > 1 else "")
                + ")")
    elif lower >= 1:
        fix += f", or lower --job-timeout to {lower},"
    return (
        f"budget: {n_jobs} job{'' if n_jobs == 1 else 's'}, {pool} at a time "
        f"= {w} wave{'' if w == 1 else 's'}. At the full {ceiling}s "
        f"--job-timeout that is {need}s of wall clock, against a --timeout of "
        f"{int(total)}s. Not a prediction: a job that answers early costs "
        f"less, a retry costs more, and a resume replays banked answers for "
        f"free. What the arithmetic says is that jobs go unsent if the "
        f"specialists are slow; those are named in the report and a rerun of "
        f"the same command pays only for them. To cover the whole matrix at "
        f"the ceiling, {fix} before this run.")


def unsent_reason(total: float | None) -> str:
    """What one job says when it was never sent."""
    return f"the {int(total or 0)}s run budget ran out before this job was sent"


def sigterm_reason() -> str:
    """What a job says when SIGTERM cut the run short before it was sent."""
    return "the run was terminated by SIGTERM before this job was sent"


def cut_clock_reason(total: float | None, given: int, ceiling: int) -> str:
    """What a job says when the budget, not the backend, killed it."""
    return (f"the {int(total or 0)}s run budget left only {given}s of the "
            f"{ceiling}s a job gets, and it did not finish in that")


_THEIR_ADVICE = re.compile(
    r"\braise (?:the limit with )?--timeout\b[^.\n]*?--no-timeout[^.\n]*"
    r"|\braise (?:the limit with )?--timeout\b[^.,\n]*"
    r"|\bdisable it with --no-timeout[^.\n]*", re.I)

_OURS = ("raise --job-timeout for one specialist, or --timeout for the "
         "whole run")


def local_flags(text: str) -> str:
    """A backend error with its flag advice swapped for this tool's flags."""
    return _THEIR_ADVICE.sub(_OURS, text) if text else text


def unsent_advice(n: int, journal: str, terminated: int = 0) -> str:
    """What the run tells the reader to do about the jobs it did not send."""
    cut = max(0, min(terminated, n))
    spent = n - cut
    if cut and spent:
        why = (f"{cut} job{'' if cut == 1 else 's'} went unsent because the "
               f"run was terminated by SIGTERM and {spent} because the run "
               f"budget ran out")
    elif cut:
        why = (f"{cut} job{'' if cut == 1 else 's'} went unsent because the "
               f"run was terminated by SIGTERM")
    else:
        why = (f"{n} job{'' if n == 1 else 's'} went unsent because the run "
               f"budget ran out")
    return (f"{why}. Everything that finished is banked in "
            f"{journal} — run the same command again and it pays only for "
            f"what is left."
            + (" Raise --timeout if the whole run needs longer." if spent else ""))


def unusable_advice(n: int, said: str) -> str:
    """What the run says when the BACKEND NAME was the fault, not the clock."""
    return (f"{n} job{'' if n == 1 else 's'} went unsent: the backend refused "
            f"the request itself, so the run stopped asking and there is "
            f"nothing to resume. Fix the --agent name and rerun — the same "
            f"command again fails the same way. {said}")


def finish_advice(unsent: int, dead: int, who: str, applied: int,
                  out_name: str, journal: str, accept_cmd: str = "",
                  unusable: str = "", terminated: int = 0) -> str:
    """How to finish an incomplete run, in one command."""
    if unusable:
        return unusable_advice(unsent, unusable)
    if not dead:
        return unsent_advice(unsent, journal, terminated)
    out = ""
    if accept_cmd and applied:
        out = (f"KEEP WHAT LANDED FIRST — do not delete {out_name} yet. "
               f"KV_FORCE=1 {sys.argv[0]} accept {accept_cmd} takes the "
               f"output with the dead span left exactly as it arrived, names "
               f"it under `still unedited:`, and exits 4 so a chained command "
               f"does not run. That span is then unshortened and nobody read "
               f"it — say so in your report.\n")
    out += (f"{'Otherwise d' if out else 'D'}elete {out_name} and rerun "
            f"with a different --agent. "
            f"({who} died twice.) There is no way to redo the dead spans "
            f"alone: a second run writes the output from scratch"
            + (f", so this costs the {applied} edit"
               f"{'' if applied == 1 else 's'} that did land."
               if applied else
               " -- and this run landed no edits, so that costs nothing."))
    if unsent:
        out += (f"\nThat covers the {unsent} unsent "
                f"job{'' if unsent == 1 else 's'} too — the new run does the "
                f"whole file."
                + (" Raise --timeout with it, or the same budget runs out "
                   "again." if unsent > terminated else ""))
    return out


def unretried_reason(total: float | None, first: str) -> str:
    """What a job says when it failed once and the budget killed its retry."""
    return (f"failed once ({first}) and the {int(total or 0)}s run budget ran "
            f"out before the retry was sent")


def dead_run_headline(total: int, dead: int, unsent: int) -> str:
    """The first line of a run that produced no output file."""
    tail = "there is nothing to write and no output file was made."
    if dead and unsent:
        return (f"no job finished ({total} of {total}): {dead} failed twice "
                f"and {unsent} ran out of run budget. There is nothing to "
                f"write and no output file was made.")
    if unsent:
        return (f"no job finished ({total} of {total}), so {tail} None of "
                f"them failed twice -- the run budget cut them.")
    return f"every job failed ({total} of {total}), so {tail}"
