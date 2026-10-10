"""Where a document is hard to read because of its shape, not its length."""

from __future__ import annotations

import re

WORD = re.compile(r"[a-z][a-z'-]+")

STOP = frozenset(
    "the a an of to in on at for and or but is are was were be been being it "
    "its this that these those we you they he she as by with from into than "
    "then so if when while do does did has have had will would can could "
    "should may might must our your their his her not no all any one two more "
    "most some such there here what which who how why also only just about "
    "over under out up down per each via using use used need needs".split())


def content(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower())
            if w not in STOP and len(w) > 2}


def seam(sents: list[str], win: int = 3):
    """The boundary inside one paragraph where the subject changes."""
    if len(sents) < 2 * win:
        return None, None
    scored = []
    for k in range(win, len(sents) - win + 1):
        left = set().union(*(content(s) for s in sents[k - win:k]))
        right = set().union(*(content(s) for s in sents[k:k + win]))
        both = left | right
        scored.append((len(left & right) / len(both) if both else 1.0, k))
    if len(scored) > 1 and len({s for s, _k in scored}) < 2:
        return None, None
    best = min(s for s, _k in scored)
    mid = len(sents) / 2
    best_i = min((k for s, k in scored if s == best), key=lambda k: abs(k - mid))
    return best_i, round(best, 3)


CARRY = frozenset(
    "then nor and but so or if when while there here also".split())

LEAD = re.compile(r"^(?:the|a|an|this|that|these|those|it|its)\s+", re.I)

VERB = frozenset(
    "is are was were be been being has have had does do did can could will "
    "would may might must should".split())


def shape(sent: str):
    """The opening word a parallel run would repeat, or None."""
    text = sent.strip()
    first = re.match(r"[A-Za-z][\w'-]*|\d+", text)
    if first and first.group(0).lower() in CARRY:
        return None
    rest = LEAD.sub("", text)
    word = re.match(r"[A-Za-z][\w'-]*|\d+", rest)
    if not word:
        return None
    key = word.group(0).lower()
    return None if key in CARRY or key in VERB else key


def list_runs(paras, floor: int = 3):
    """Runs of `floor` or more consecutive sentences sharing an opening word."""
    out = []
    for _line, pairs in paras:
        i = 0
        while i < len(pairs):
            key = shape(pairs[i][1])
            j = i + 1
            if key is not None:
                while j < len(pairs) and shape(pairs[j][1]) == key:
                    j += 1
            if key is not None and j - i >= floor:
                out.append((pairs[i][0], key, [s for _l, s in pairs[i:j]]))
            i = j if j > i + 1 else i + 1
    return out


LABEL = re.compile(r"^\*{1,2}\s*([A-Z][^*:]{0,40}?)\s*(?::\s*\*{1,2}|\*{1,2}\s*:)")


NUMBERED = re.compile(r"^\*{1,2}\s*\d+\\?[.)]\s+[^*]{1,60}?\*{1,2}")


def labelled(sents: list[str]) -> list[int]:
    """Sentences that open with the author's own label."""
    return [i for i, s in enumerate(sents)
            if LABEL.match(s.strip()) or NUMBERED.match(s.strip())]


def label_runs(paras, floor: int = 3):
    """Runs of neighbouring paragraphs that each open with a label."""
    out: list[list[int]] = []
    run: list[int] = []
    for line, sents in paras:
        if sents and labelled(sents[:1]):
            run.append(line)
            continue
        if len(run) >= floor:
            out.append(run)
        run = []
    if len(run) >= floor:
        out.append(run)
    return out
