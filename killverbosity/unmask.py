"""The sentence as the author wrote it, recovered from the masked copy."""

from __future__ import annotations

import re

_PREFIX_WIDTHS = (72, 48, 32, 20, 12)


def joined(src: list[str], masked: list[str], ln: int, end: int, s: str) -> str:
    """`s` as it reads across the source lines `ln` to `end`."""
    if not (0 < ln <= min(len(src), len(masked))):
        return s
    rows = range(ln - 1, min(end, len(src), len(masked)))
    whole = " ".join(" ".join(src[i].split()) for i in rows)
    row = " ".join(masked[i].strip() for i in rows)
    raw = " ".join(src[i].strip() for i in rows)
    if len(row) != len(raw):
        return whole
    at = row.find(s)
    if at >= 0:
        return raw[at:at + len(s)].strip() or whole
    for width in _PREFIX_WIDTHS:
        at = row.find(s[:width]) if len(s) >= width else -1
        if at >= 0:
            return raw[at:].strip() or whole
    return whole


def as_written(src: list[str], masked: list[str], ln: int, s: str) -> str:
    """`s` as it reads in the source, or the source line, or `s` unchanged."""
    if not (0 < ln <= min(len(src), len(masked))):
        return s
    row, raw = masked[ln - 1], src[ln - 1]
    if len(row) != len(raw):
        return raw.strip()
    for width in _PREFIX_WIDTHS:
        at = row.find(s[:width]) if len(s) >= width else -1
        if at >= 0:
            return _lead(raw, at) + (raw[at:at + len(s)].strip() or raw.strip())
    at = row.find(s)
    return (_lead(raw, at) + (raw[at:at + len(s)].strip() or raw.strip())) if at >= 0 \
        else raw.strip()


_OPENS = re.compile(r'''(^|[.!?]["')\]]?\s|\|\s*|^\s*[-*+]\s|\d+[.)]\s)$''')


def _lead(raw: str, at: int) -> str:
    """`…` when the span starts mid-sentence, `""` when it starts at one."""
    if at <= 0:
        return ""
    return "" if _OPENS.search(raw[:at]) else "…"


_BLOCK = re.compile(r"\s*(#|\||>|[-*+] |\d+[.)] |```|~~~|:?-{3,})")


def _paragraph(src: list[str], ln: int) -> str:
    """Line `ln` and the wrapped lines below it, joined with a space."""
    if not 0 < ln <= len(src):
        return ""
    out = [src[ln - 1]]
    for nxt in src[ln:]:
        if not nxt.strip() or _BLOCK.match(nxt):
            break
        out.append(nxt.strip())
    return " ".join(out)


def in_context(src: list[str], masked: list[str], ln: int, s: str,
               width: int = 60, nth: int = 0, abbr=None) -> str:
    """The match, plus the rest of its sentence, cut to `width`."""
    said = as_written(src, masked, ln, s)
    raw = _paragraph(src, ln)
    lead = ""
    if said.startswith("\u2026"):
        lead, said = said[0], said[1:]
    anchor = said
    if 0 < ln <= len(src) and said == src[ln - 1].strip() and s != said \
            and s in raw:
        anchor = s
    at = -1
    for _ in range(nth + 1):
        nxt = raw.find(anchor, at + 1)
        if nxt < 0:
            break
        at = nxt
    if at < 0:
        return lead + quote(said, width)
    said = anchor
    tail = raw[at:]
    for end in re.finditer(r"[.!?](?=\s|$)", tail[len(said):]):
        cut = tail[:len(said) + end.end()]
        if abbr and abbr.search(cut):
            continue
        return lead + quote(cut, width)
    return lead + quote(tail, width)


def quote(text: str, width: int = 60) -> str:
    """`text` cut to `width` for a message, on a word boundary, marked if cut."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    head = text[:width]
    at = head.rfind(" ")
    return (head[:at] if at > width // 2 else head).rstrip(" ,;:") + "…"
