"""Which lines and which specialist a refusal belongs to."""

from __future__ import annotations


def carriers(start: int, end: int, edited) -> set[int]:
    """The edited lines a rule lost between `start` and `end` is refused on."""
    return {k for k in range(start, end + 1) if k in edited}


def job_owners(ln: int, job_spans) -> list[str]:
    """The specialist(s) whose dispatched span covered original line `ln`."""
    if not job_spans:
        return []
    out = []
    for j in job_spans:
        lo, hi = j.get("lo"), j.get("hi")
        if not isinstance(lo, int) or not isinstance(hi, int) or not (
                lo <= ln <= hi):
            continue
        who, unit = j.get("specialist", "?"), j.get("unit")
        out.append(f"{who} ({unit})" if unit else who)
    return out


def repeat_rows(added, results, key, words: int):
    """One `(line, specialist, cluster text)` per edit the dedup retry drops."""
    heads = [(head, d) for d in added
             if (head := " ".join(d["text"].split()[:words]))]
    out = []
    for r in results:
        for e in r.get("edits", ()):
            body = key(e.get("new", ""))
            if not body:
                continue
            for head, d in heads:
                if head in body:
                    out.append((e.get("line") or min(d.get("lines") or [0]),
                                r["specialist"], d.get("said") or d["text"]))
                    break
    return out
