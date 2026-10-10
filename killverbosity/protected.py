"""Sections that say not to edit them, and are then edited."""

from __future__ import annotations

import re

MARKER = re.compile(
    r"^\W*(?:note for agents?\b"
    r"|do[ -]not[ -](?:edit|modify|change|touch)\b"
    r"|read[ -]only\b"
    r"|agents?[ -]read[ -]this\b)",
    re.I)


def is_marker(heading: str) -> bool:
    return bool(MARKER.search(heading.strip()))


DATED_STATUS = re.compile(
    r"^\**\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:DONE|TODO|IN_PROGRESS|ACCEPTED|REJECTED|BLOCKED(?:-ON-USER)?)\b"
    r"[^\n]{0,40}?\b\d{4}-\d{2}-\d{2}\b",
    re.I)


def is_dated_status(heading: str) -> bool:
    return bool(DATED_STATUS.search(heading.strip()))


def dated_status_lines(headings) -> set[int]:
    """1-based line numbers of headings that record a dated status."""
    return {idx + 1 for idx, _level, text in headings if is_dated_status(text)}


def lines(headings, n_lines: int) -> set[int]:
    """1-based lines inside a section a heading marks as do-not-edit."""
    out: set[int] = set()
    for i, (idx, level, text) in enumerate(headings):
        if not is_marker(text):
            continue
        end = n_lines
        for later_idx, later_level, _t in headings[i + 1:]:
            if later_level <= level:
                end = later_idx
                break
        out |= set(range(idx + 1, end + 1))
    return out
