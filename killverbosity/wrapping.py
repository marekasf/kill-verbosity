"""Line margins: read one off a file, put one back, or take one away."""

from __future__ import annotations

import re
import textwrap
from collections.abc import Callable

LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)]|[a-zA-Z][.)])\s")

Mask = Callable[[str], tuple[list[str], object, object, object]]


MAX_WIDTH = 120


def longest_token(line: str) -> int:
    """The longest run of non-space in a line. What no margin can shorten."""
    return max((len(t) for t in line.split()), default=0)


UNBREAKABLE = re.compile(r"https?://|\]\(")


def _continuation_lengths(prose: list[str],
                          evidence_only: bool = False) -> list[int]:
    """The length of every line that has another line under it in its paragraph."""
    out: list[int] = []
    run: list[str] = []
    for line in list(prose) + [""]:
        if line.strip() and not LIST_ITEM.match(line):
            run.append(line.rstrip())
            continue
        for r in run[:-1]:
            if evidence_only and UNBREAKABLE.search(r):
                continue
            out.append(len(r))
        run = [line.rstrip()] if LIST_ITEM.match(line) else []
    return out


def multiline_paragraphs(prose: list[str]) -> int:
    """How many paragraphs run over more than one line."""
    n, run = 0, 0
    for line in list(prose) + [""]:
        if line.strip() and not LIST_ITEM.match(line):
            run += 1
            continue
        if run > 1:
            n += 1
        run = 1 if LIST_ITEM.match(line) else 0
    return n


def _high(lengths: list[int]) -> int:
    """The 90th-percentile length: the margin, with the outliers left off."""
    ordered = sorted(lengths)
    return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]


def wrap_width(orig_lines: list[str], mask: Mask) -> int | None:
    """The column this file wraps prose at, or None if it does not wrap."""
    prose, _h, _t, _q = mask("\n".join(orig_lines))
    if sum(1 for l in prose if l.strip()) < 10:
        return None
    lengths = _continuation_lengths(prose, evidence_only=True)
    if len(lengths) < 4:
        return None
    margin = _high(lengths)
    if margin > MAX_WIDTH:
        return None
    near = sum(1 for n in lengths if n > margin - 12)
    return margin if near * 2 >= len(lengths) else None


_UNBREAKABLE = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)|`[^`\n]+`")


def _protect_tokens(text: str) -> tuple[str, list[str]]:
    toks: list[str] = []

    def sub(m: "re.Match[str]") -> str:
        s = m.group(0)
        if " " not in s:
            return s
        i = len(toks)
        toks.append(s)
        tag = f"\x00{i}\x00"
        return tag + "\x01" * max(0, len(s) - len(tag))

    return _UNBREAKABLE.sub(sub, text), toks


def _restore_tokens(text: str, toks: list[str]) -> str:
    for i, s in enumerate(toks):
        text = re.sub(f"\x00{i}\x00\x01*", lambda _m: s, text, count=1)
    return text


def rewrap_prose(orig_lines: list[str], merged: list[str],
                 mask: Mask) -> list[str]:
    """Re-wrap prose lines that an edit left longer than the file's margin."""
    width = wrap_width(orig_lines, mask)
    if not width:
        return merged
    prose, _h, _t, _q = mask("\n".join(merged))
    untouched = set(orig_lines)
    out = []
    for i, line in enumerate(merged):
        if (i >= len(prose) or not prose[i].strip()
                or len(line.rstrip()) <= width
                or line in untouched
                or longest_token(line) > width):
            out.append(line)
            continue
        indent = line[:len(line) - len(line.lstrip())]
        bullet = re.match(r"[-*+]\s+|\d+[.)]\s+|[a-zA-Z][.)]\s+", line.lstrip())
        hang = indent + " " * len(bullet.group(0)) if bullet else indent
        safe, toks = _protect_tokens(line.strip())
        wrapped = textwrap.wrap(
            safe, width=width, initial_indent=indent,
            subsequent_indent=hang, break_long_words=False,
            break_on_hyphens=False)
        wrapped = [_restore_tokens(w, toks) for w in wrapped]
        out.extend(wrapped or [line])
    return out


def fold_paragraphs(merged: list[str], mask: Mask,
                    never_join: frozenset[int] = frozenset(),
                    ) -> list[tuple[str, int, int]]:
    """Each paragraph on one line, with the source lines it came from."""
    prose, _h, _t, _q = mask("\n".join(merged))

    def joinable(i: int) -> bool:
        text = merged[i].strip()
        return bool(
            text and i not in never_join
            and i < len(prose) and prose[i].strip()
            and not text.startswith(("#", ">"))
            and "|" not in text
            and not re.fullmatch(r"[=-]{2,}", text))

    out: list[tuple[str, int, int]] = []
    run: list[int] = []

    def flush() -> None:
        if not run:
            return
        if not all(joinable(i) for i in run):
            out.extend((merged[i], i, i) for i in run)
        else:
            for i in run:
                text = merged[i].strip()
                if out and run[0] != i and not LIST_ITEM.match(text):
                    prev, first, _last = out[-1]
                    out[-1] = (prev + " " + text, first, i)
                else:
                    indent = merged[i][:len(merged[i]) - len(merged[i].lstrip())]
                    out.append((indent + text, i, i))
        run.clear()

    for i, line in enumerate(merged):
        if not line.strip():
            flush()
            out.append((line, i, i))
        else:
            run.append(i)
    flush()
    return out


def join_paragraphs(merged: list[str], mask: Mask) -> list[str]:
    """One line per paragraph, for a message going to a chat client."""
    return [text for text, _first, _last in fold_paragraphs(merged, mask)]


def source_span(first: int, last: int,
                spans: list[tuple[int, int]]) -> tuple[int, int]:
    """A folded line range, as the 1-based lines the author wrote."""
    if not spans:
        return first, last
    lo = spans[min(max(first, 1), len(spans)) - 1][0] + 1
    hi = spans[min(max(last, 1), len(spans)) - 1][1] + 1
    return lo, hi


def label(first: int, last: int, spans: list[tuple[int, int]]) -> str:
    """A folded line range as `L12` or `L12-14`, in the author's numbers."""
    lo, hi = source_span(first, last, spans)
    return f"L{lo}" if lo == hi else f"L{lo}-{hi}"


def unwrap_source(lines: list[str], mask: Mask,
                  never_join: frozenset[int] = frozenset(),
                  ) -> tuple[list[str], list[tuple[int, int]]]:
    """Fold a hard-wrapped file so a specialist is given whole paragraphs."""
    if wrap_width(lines, mask) is None:
        return lines, [(i, i) for i in range(len(lines))]
    folded = fold_paragraphs(lines, mask, never_join)
    return [t for t, _f, _l in folded], [(f, l) for _t, f, l in folded]


def text_span(want: str, first: int, last: int,
              lines: list[str]) -> tuple[int, int]:
    """The 1-based source lines `want` occupies inside `lines[first-1:last]`."""
    want = " ".join(want.split())
    if not want or first > last or last > len(lines):
        return first, last
    at, ends = 0, []
    for i in range(first - 1, last):
        piece = " ".join(lines[i].split())
        at += len(piece) + (1 if ends else 0)
        ends.append(at)
    joined = " ".join(" ".join(lines[i].split())
                      for i in range(first - 1, last))
    start = joined.find(want)
    if start < 0:
        return first, last
    stop = start + len(want) - 1
    lo = next((k for k, e in enumerate(ends) if e > start), 0)
    hi = next((k for k, e in enumerate(ends) if e > stop), len(ends) - 1)
    return first + lo, first + hi
