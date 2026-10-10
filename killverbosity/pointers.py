"""A summary pointer that follows the heading it points at."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s*#+\s*")
_POINTER = re.compile(r"\(([^()\n]{3,60})\)")

HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def heading_name(text: str) -> str:
    """A heading's NAME: what a sentence may call the section."""
    return " ".join(HTML_COMMENT.sub(" ", text).split())

OWNER = "summary"


MENTION_WORDS = 2


def unreadable(lines, masked) -> set[int]:
    """Line numbers masking erased whole: fences, frontmatter, tree diagrams."""
    return {i for i, (raw, m) in enumerate(zip(lines, masked), 1)
            if raw.strip() and not m.strip()}


def stale_mentions(lines, was: str, heading_lines=()) -> list[int]:
    """Lines of the edited file that still name a renamed heading."""
    name = was.strip()
    if len(re.findall(r"\w+", name)) < MENTION_WORDS:
        return []
    rx = re.compile((r"(?<!\w)" if re.match(r"\w", name) else "")
                    + re.escape(name)
                    + (r"(?!\w)" if re.search(r"\w$", name) else ""), re.I)
    skip = set(heading_lines)
    return [i for i, line in enumerate(lines, 1)
            if i not in skip and refers(line, rx)]


REFERRING = re.compile(
    r"(?<!\w)(?:see|section|sections|heading|chapter|above|below|earlier|"
    r"later|overleaf|supra|infra)(?!\w)", re.I)


def refers(line: str, rx) -> bool:
    """True when this line names the heading AND is pointing at it."""
    m = rx.search(line)
    if not m:
        return False
    lead, tail = line[:m.start()], line[m.end():]
    quoted = (lead.endswith(('"', "'", "`", "“", "‘"))
              and tail.startswith(('"', "'", "`", "”", "’")))
    return quoted or bool(REFERRING.search(line))


def rename_map(headings, by_line: dict[int, str]) -> dict[str, str]:
    """{old heading text: new heading text} for what `by_line` renames."""
    out = {}
    for h in headings:
        line, old = h[0] + 1, heading_name(h[2])
        if line not in by_line:
            continue
        raw = by_line[line]
        new = heading_name(_HEADING.sub("", raw.strip().split("\n")[0]))
        if new != old:
            out[old] = new if raw.strip().startswith("#") else ""
    return out


def follow(results, renames: dict[str, str]) -> list[tuple[str, str]]:
    """Point each summary pointer at the new name, in place."""
    live = {k.casefold(): v for k, v in renames.items() if v}
    if not live:
        return []
    done = []
    for r in results:
        if r.get("specialist") != OWNER or r.get("error"):
            continue
        for e in r.get("edits", ()):
            text = e.get("new", "")
            if not text:
                continue

            def swap(m):
                names = [heading_name(p) for p in m.group(1).split(";")]
                out, hit = [], False
                for name in names:
                    new = live.get(name.casefold())
                    if new:
                        done.append((name, new))
                        out.append(new)
                        hit = True
                    else:
                        out.append(name)
                return f"({'; '.join(out)})" if hit else m.group(0)

            fixed = _POINTER.sub(swap, text)
            if fixed != text:
                e["new"] = fixed
    return done
