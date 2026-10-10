"""Find the JSON object in a model's answer."""

from __future__ import annotations

import json
import re

FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def objects(raw: str) -> list[str]:
    """Every balanced `{...}` in the text, outermost only, in order."""
    out: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(raw):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append(raw[start:i + 1])
    return out


def candidates(raw: str) -> list[str]:
    """The objects to try, fenced blocks first."""
    fenced = [o for m in FENCE.findall(raw) for o in objects(m)]
    return fenced + [o for o in objects(raw) if o not in fenced]


def payload(raw: str) -> tuple[dict | None, str | None]:
    """The reply object, or an error naming what came back instead."""
    seen: dict | None = None
    bad = ""
    for text in candidates(raw):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            bad = bad or f"bad JSON: {e}"
            continue
        if not isinstance(obj, dict):
            continue
        if "edits" in obj or "notes" in obj:
            return obj, None
        seen = seen if seen is not None else obj
    if seen is not None:
        return seen, None
    return None, bad or (
        f'no JSON object in the answer (one object carrying "edits" or '
        f'"notes", e.g. {{"edits": [{{"line": 12, "new": "..."}}], '
        f'"notes": []}}): {raw.strip()[:200]!r}')
