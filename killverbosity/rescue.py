"""Which deleted sentences a surviving sentence still answers for."""

from __future__ import annotations

from killverbosity import inflect

LEAST_SHARED = 3


def answered(deleted, survivors, floor: float, taken: set | None = None,
             least: int = LEAST_SHARED) -> set:
    """The `deleted` entries whose content a survivor still carries."""
    taken = set() if taken is None else taken
    ranked = sorted(
        ((hit / len(words), ref, key)
         for ref, forms in deleted
         for key, words in survivors
         for hit in (inflect.overlap(words, forms),)
         if hit >= least and hit / len(words) >= floor),
        key=lambda r: (-r[0], r[1], r[2]))
    out = set()
    for _score, ref, key in ranked:
        if key not in taken and ref not in out:
            taken.add(key)
            out.add(ref)
    return out
