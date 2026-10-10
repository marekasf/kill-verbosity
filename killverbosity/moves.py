"""A move the specialist described instead of making."""

from __future__ import annotations

import re

_INTO = re.compile(r"\bmoves?\b[^.]{0,80}?\bline (\d+)\b[^.]{0,80}?"
                   r"\binto\b[^.]{0,80}?\bat line (\d+)\b", re.I)

_TO = re.compile(r"\bmoves?\b[^.]{0,80}?\bfrom line (\d+)\b[^.]{0,40}?"
                 r"\bto (?:line )?(\d+)\b", re.I)

_REFUSED = re.compile(r"\bno (?:move|change)\b|\bnot needed\b|"
                      r"\bdoes not need\b|\bdo not move\b|\bleave it\b", re.I)

_DELIBERATED = re.compile(r"^\W*(?:i|we)?\s*(?:considered|thought about|"
                          r"weighed|looked at whether|debated)\b", re.I)
_DECLINED = re.compile(r"\bkept\b|\bkeeping\b|\bleft (?:it|them|both|the)\b|"
                       r"\bno (?:move|change)\b|\bnot needed\b|"
                       r"\bdoes not need\b|\bdo not move\b|\bleave it\b|"
                       r"\bsent neither\b|\bneither\b", re.I)

_KEEP = re.compile(r"^\W*(?:i|we)?\s*(?:keep|keeping|leave|leaving|retain)\b",
                   re.I)
_NAMED = re.compile(r"[\"“'`]([^\"”'`\n]{3,80})[\"”'`]")

OWNER = "structure"


MOVE_OPS = ("move", "move-block")


def records(applied):
    """Every structural move this run made, for the run record."""
    return [{"op": op, "line": line, "why": why}
            for line, why, op, _payload in applied if op in MOVE_OPS]


def declined_move(note: str) -> bool:
    """True when a note weighs a move and then says it was not made."""
    text = note.strip()
    if _DELIBERATED.search(text) and _DECLINED.search(text):
        return True
    return bool(_KEEP.match(text) and len(_NAMED.findall(text)) >= 2)


def as_edit(note: str, n_lines: int) -> dict | None:
    """The edit a note describes, or None if it describes no reachable move."""
    if _REFUSED.search(note):
        return None
    if hit := _INTO.search(note):
        op, key = "move-block", "into"
    elif hit := _TO.search(note):
        op, key = "move", "to"
    else:
        return None
    line, dest = int(hit.group(1)), int(hit.group(2))
    if not (1 <= line <= n_lines and 1 <= dest <= n_lines):
        return None
    return {"op": op, "line": line, key: dest,
            "why": f"described in a note: {note.strip()}"}


def promote(results, n_lines: int) -> list[tuple[str, str]]:
    """Turn each described move into the edit it describes, in place."""
    done = []
    for r in results:
        if r["specialist"] != OWNER or not r.get("notes"):
            continue
        taken = {e.get("line") for e in r.get("edits", ())}
        keep = []
        for note in r["notes"]:
            edit = as_edit(note, n_lines)
            if edit is None or edit["line"] in taken:
                if not declined_move(note):
                    keep.append(note)
                continue
            r.setdefault("edits", []).append(edit)
            done.append((r["specialist"], note))
        r["notes"] = keep
    return done
