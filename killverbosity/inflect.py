"""The other forms of a word, so a changed verb form is not a lost claim."""

from __future__ import annotations

VOWELS = "aeiou"

_HISS = ("ses", "xes", "zes", "ches", "shes")


def doubles(b: str) -> bool:
    """True when `b` doubles its last letter before -ed and -ing."""
    return (len(b) > 2 and b[-1] not in VOWELS + "wxy"
            and b[-2] in VOWELS and b[-3] not in VOWELS)


def verb_stems(w: str) -> set[str]:
    """The words `w` could be a past or present participle of."""
    out: set[str] = set()
    if len(w) > 4 and w.endswith("ied"):
        out.add(w[:-3] + "y")
    elif len(w) > 3 and w.endswith("ed"):
        out.add(w[:-1])
        if not doubles(w[:-2]):
            out.add(w[:-2])
        if len(w) > 4 and w[-3] == w[-4] and w[-3] not in VOWELS:
            out.add(w[:-3])
        if len(w) > 5 and w.endswith("cked"):
            out.add(w[:-3])
    if len(w) > 4 and w.endswith("ing"):
        out.add(w[:-3] + "e")
        if not doubles(w[:-3]):
            out.add(w[:-3])
        if len(w) > 5 and w[-4] == w[-5] and w[-4] not in VOWELS:
            out.add(w[:-4])
        if len(w) > 6 and w.endswith("cking"):
            out.add(w[:-4])
    return out


def noun_stems(w: str) -> set[str]:
    """The words `w` could be the plural, or the third person, of."""
    out: set[str] = set()
    if len(w) > 4 and w.endswith("ies"):
        out.add(w[:-3] + "y")
    elif len(w) > 4 and w.endswith(_HISS):
        out.add(w[:-2])
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        out.add(w[:-1])
    return out


def grow(b: str) -> set[str]:
    """Every form of the stem `b`."""
    out = {b, b + "s", b + "ed", b + "ing"}
    if b.endswith("e"):
        out.update({b + "d", b[:-1] + "ing"})
    if b.endswith(("s", "x", "z", "ch", "sh")):
        out.add(b + "es")
    if b.endswith("c"):
        out.update({b + "ked", b + "king"})
    if len(b) > 2 and b.endswith("y") and b[-2] not in VOWELS:
        out.update({b[:-1] + "ies", b[:-1] + "ied"})
    if doubles(b):
        out.update({b + b[-1] + "ed", b + b[-1] + "ing"})
    return out


def spread(words) -> frozenset[str]:
    """Every form of every word in `words`."""
    out: set[str] = set()
    for w in words:
        out |= grow(w)
        for b in verb_stems(w):
            out |= grow(b)
        out |= noun_stems(w)
    return frozenset(out)


def share(words, forms) -> float:
    """The fraction of `words` that `forms` holds, in any form."""
    if not words:
        return 0.0
    return sum(1 for w in words if w in forms) / len(words)


def overlap(words, forms) -> int:
    """How many of `words` `forms` holds."""
    return sum(1 for w in words if w in forms)


_NOMINAL = (
    ("ication", ("y",)),
    ("ization", ("ize", "ise")),
    ("isation", ("ise", "ize")),
    ("ution", ("ute",)),
    ("ision", ("ide",)),
    ("usion", ("ude",)),
    ("ption", ("be",)),
    ("ction", ("ct",)),
    ("ation", ("ate", "")),
    ("ment", ("", "e")),
    ("ysis", ("yse", "yze")),
    ("tion", ("te", "t")),
)


def verbs_from_noun(w: str) -> set[str]:
    """The verbs `w` could be the noun of. Empty when no suffix matches."""
    for suffix, ends in _NOMINAL:
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return {w[: -len(suffix)] + e for e in ends}
    return set()
