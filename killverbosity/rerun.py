"""Whether a run may write over an output file that is already there."""

from __future__ import annotations

import time
from pathlib import Path

RESUME = "resume"
REFUSE = "refuse"
PROCEED = "proceed"


def verdict(out_path: Path, src: Path, text: str, banked: dict) -> str:
    """What to do about an output file found beside the input."""
    if not out_path.exists():
        return PROCEED
    if out_path.stat().st_mtime <= src.stat().st_mtime:
        return PROCEED
    if out_path.read_text(errors="replace") == text:
        return PROCEED
    return RESUME if banked else REFUSE


def refusal(out_name: str, out_mtime: float, src_mtime: float,
            resume: str = "unknown") -> str:
    """Why this run will not start, with the two readings it rests on."""
    gap = out_mtime - src_mtime
    return (f"kill-verbosity: {out_name} is newer than the input, so an "
            f"earlier run wrote it and this one would throw it away. "
            f"({out_name} {_when(out_mtime)}, input {_when(src_mtime)} — "
            f"{gap:.0f}s apart. A gap of seconds is usually an editor or a "
            f"checkout touching both, not a run.) Accept "
            f"it, delete it, or send this run somewhere else with -o. "
            + _resume_note(resume))


_RESUME_NOTES = {
    "banked": "Deleting it does not cost you the answers already paid for — "
              "the journal is a separate file and the next run resumes from it.",
    "discarded": "NOTE the journal held answers for a different version of "
                 "this input and has already been discarded, so the next run "
                 "pays for every job again — deleting the sidecar costs you "
                 "nothing further, but there is no resume to come back to.",
    "none": "There is no journal beside it, so the next run pays for every "
            "job again — deleting the sidecar costs you nothing further.",
    "unknown": "Whether a journal survives beside it was not checked here, so "
               "this does not say whether the next run resumes or pays again.",
}


def _resume_note(resume: str) -> str:
    return _RESUME_NOTES.get(resume, _RESUME_NOTES["unknown"])


def stale_note(orig_name: str, edited_name: str,
               orig_mtime: float, edited_mtime: float):
    """The input moved after the edit was made. `None` when it did not."""
    gap = orig_mtime - edited_mtime
    if gap <= 0:
        return None
    return (f"{orig_name} is NEWER than {edited_name}: the input moved after "
            f"the edit was made, so anything below that reads as content lost "
            f"may be content that arrived. ({orig_name} {_when(orig_mtime)}, "
            f"{edited_name} {_when(edited_mtime)} — {gap:.0f}s apart. A gap of "
            f"seconds is usually an editor or a checkout touching both; hours "
            f"or days is the input having been rewritten or regenerated.)")


def moved_note(orig_name: str, edited_name: str, orig_mtime: float,
               edited_mtime: float, recorded: str | None, current: str):
    """`stale_note`, decided by content when the run record holds a digest."""
    if not recorded:
        return stale_note(orig_name, edited_name, orig_mtime, edited_mtime)
    if recorded == current:
        return None
    return (f"{orig_name} is not the input the run read: its digest is "
            f"{current[:12]} now and the run record says {recorded[:12]}, so "
            f"anything below that reads as content lost may be content that "
            f"arrived after {edited_name} was written.")


def _when(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
