"""Does this file open with a summary, and is the one it has any good?"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple


class Rules(NamedTuple):
    """The profile's answers, read at the call and never cached."""

    heading: re.Pattern[str]
    needed_from: int
    min_words: int
    cap: Callable[[int], int]
    words: Callable[[str], int] = lambda s: len(s.split())


BURIED_MIN_WORDS = 30

_URL = re.compile(r"<[^>\s]+>|\bhttps?://\S+")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CODE = re.compile(r"`[^`]*`")


def _real_words(lines) -> int:
    """Words above a summary that a reader actually has to read."""
    text = " ".join(lines)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(" ", _URL.sub(" ", text))
    return len(text.split())


_FM_DESCRIPTION = re.compile(r"^description:\s*\S", re.I)


def declares_abstract(text: str) -> bool:
    """True when the file states its own abstract in frontmatter."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return False
    for ln in lines[1:]:
        if ln.strip() == "---":
            return False
        if _FM_DESCRIPTION.match(ln):
            return True
    return False


def has_title(headings, body, rules: Rules) -> bool:
    """True when the first heading names the document, not its first section."""
    if not headings:
        return False
    line, level, txt = headings[0]
    if rules.heading.match(txt.strip()):
        return False
    if level == 1:
        return True
    nxt = headings[1][0] if len(headings) > 1 else len(body)
    return not any(body[j].strip()
                   for j in range(line + 1, min(nxt, len(body))))


QUOTE_BODY = re.compile(r"^\s{0,3}>+\s?(.*)$")


def quoted_view(prose, raw):
    """`prose` with blockquote bodies put back, for counting only."""
    if raw is None:
        return prose
    out = list(prose)
    for i in range(min(len(out), len(raw))):
        if out[i].strip():
            continue
        got = QUOTE_BODY.match(raw[i])
        if got and got.group(1).strip():
            out[i] = got.group(1)
    return out


def opening_summary(headings, prose, words, rules: Rules, declared=False,
                    verbatim=False, raw=None, marked=False):
    """Report on the one-page abstract a long document owes its reader."""
    if words < rules.needed_from:
        return None
    return _find_opening(headings, prose, words, rules, declared=declared,
                         verbatim=verbatim, raw=raw, marked=marked)


def _find_opening(headings, prose, words, rules: Rules, declared=False,
                  verbatim=False, raw=None, marked=False):
    """The walk both entry points share, with no length gate on it."""
    for i, (line, level, txt) in enumerate(headings):
        if i == 0 and has_title(headings, prose, rules):
            continue
        if not rules.heading.match(txt.strip()):
            break
        _v = quoted_view(prose, raw)
        above = [j for j in range(min(line, len(_v)))
                 if _v[j].strip() and not any(h[0] == j for h in headings)]
        aw = _real_words(_v[j] for j in above) if above else 0
        if aw >= BURIED_MIN_WORDS:
            return {"present": False, "words": words, "doc": words,
                    "buried": line + 1, "above": len(above), "above_words": aw}
        sibling = next((h[0] for h in headings[i + 1:] if h[1] <= level), None)
        end = sibling if sibling is not None else (
            headings[i + 1][0] if i + 1 < len(headings) else len(prose))
        n = sum(rules.words(prose[j]) for j in range(line, min(end, len(prose))))
        return {"present": True, "line": line + 1, "title": txt,
                "words": n, "end": end, "doc": words}
    lede, lede_where = _unheaded_lede(headings, prose, words, rules, raw)
    headed, headed_title, headed_at = (
        (0, None, 0) if lede else _headed_opening(headings, prose, words, rules))
    return {"present": False, "words": words, "doc": words,
            **({"declared": True} if declared else {}),
            **({"verbatim": True} if verbatim else {}),
            **({"marked": True} if marked else {}),
            **({"lede": lede, "lede_where": lede_where} if lede else {}),
            **({"headed": headed, "headed_title": headed_title,
                "headed_at": headed_at} if headed else {})}


LEDE_WHERE = {
    "below-title": "between the title and the first section heading",
    "title-only": "under the title, with no other heading anywhere in the file",
    "above-first": "above the first heading",
}


def lede_where_phrase(where) -> str:
    """Where an unheaded opening sits, or the untitled reading when unknown."""
    return LEDE_WHERE.get(where, LEDE_WHERE["above-first"])


def _unheaded_lede(headings, prose, words, rules: Rules, raw=None):
    """`(words, where)` for prose with no heading over it, or `(0, None)`."""
    titled = has_title(headings, prose, rules)
    after = [h[0] for h in (headings[1:] if titled else headings)]
    stop = after[0] if after else len(prose)
    start = headings[0][0] + 1 if titled else 0
    where = ("below-title" if titled and after
             else "title-only" if titled
             else "above-first")
    view = quoted_view(prose, raw)
    n = sum(rules.words(view[j]) for j in range(start, min(stop, len(view)))
            if not any(h[0] == j for h in headings))
    if n < rules.min_words:
        return 0, None
    if n > max(rules.cap(words), words // 4):
        return 0, None
    return n, where


def _series_member(txt: str) -> bool:
    """True when this heading is one of a numbered series, not an opening."""
    parts = txt.strip().split()
    return bool(parts) and any(c.isdigit() for c in parts[0] + parts[-1])


def _headed_opening(headings, prose, words, rules: Rules):
    """`(words, heading, line)` for a LABELLED opening section, or `(0, None, 0)`."""
    if len(headings) < 2 or not has_title(headings, prose, rules):
        return 0, None, 0
    line, _level, txt = headings[1]
    if rules.heading.match(txt.strip()) or _series_member(txt):
        return 0, None, 0
    if any(prose[j].strip()
           for j in range(headings[0][0] + 1, min(line, len(prose)))):
        return 0, None, 0
    nxt = headings[2][0] if len(headings) > 2 else len(prose)
    n = sum(len(prose[j].split()) for j in range(line + 1, min(nxt, len(prose)))
            if not any(h[0] == j for h in headings))
    if n < rules.min_words or n > max(rules.cap(words), words // 4):
        return 0, None, 0
    return n, txt, line + 1


def heads_summary(text: str, rules: Rules) -> bool:
    """True when this block of new text opens with a summary heading."""
    first = text.strip().split("\n")[0]
    marked = re.match(r"\s*#+\s*(.+)", first)
    return bool(marked and rules.heading.match(marked.group(1).strip()))


def section_level(headings, body, rules: Rules) -> int:
    """The `#` depth this document writes a top-level section at."""
    if not headings or not has_title(headings, body, rules):
        return 0
    after = [lvl for _ln, lvl, _txt in headings[1:]]
    return min(after) if after else min(headings[0][1] + 1, 6)


def buried_above(summary) -> int:
    """How many real lines sit over a buried summary."""
    return summary.get("above", summary["buried"] - 1)


def buried_reason(summary) -> str:
    """The lines above a buried summary, and the number that fired the check."""
    n = buried_above(summary)
    lines = f"{n} line{'' if n == 1 else 's'} of body above it"
    aw = summary.get("above_words")
    if aw is None:
        return lines
    return (f"{lines} carrying {aw} word{'' if aw == 1 else 's'}, over the "
            f"{BURIED_MIN_WORDS}-word floor this check fires on")


def projected(lines, edits, owner, rules: Rules) -> str:
    """The file as the merge will leave it, minus the renames it will refuse."""
    def lands(ln: int, new: str) -> bool:
        was = re.sub(r"^\s*#+\s*", "", lines[ln - 1]).strip()
        now = re.sub(r"^\s*#+\s*", "", new).strip()
        if rules.heading.match(now) and not rules.heading.match(was):
            return owner.get(ln) == "summary"
        return True

    return "\n".join(
        edits[k] if k in edits and lands(k, edits[k]) else lines[k - 1]
        for k in range(1, len(lines) + 1))


def opens_with_summary(headings, prose, words, rules: Rules) -> int:
    """The line the file opens its summary on, or 0."""
    s = _find_opening(headings, prose, words, rules)
    return s["line"] if s and s.get("present") else 0
