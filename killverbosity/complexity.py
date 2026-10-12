"""ARI and MTLD over the prose of a Markdown file. A report, never a gate."""
import re

_FENCE = re.compile(r"^\s*(```|~~~)")
_ITEM = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")
_STOP = re.compile(r"[.!?]+(?:\s+|$)")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
MTLD_THRESHOLD = 0.72


def sentences(text):
    out, para = [], []

    def flush():
        out.extend(s for s in _STOP.split(" ".join(para)) if s.strip())
        para.clear()

    fenced = False
    for raw in text.split("\n"):
        if _FENCE.match(raw):
            fenced = not fenced
            flush()
            continue
        if fenced or raw.lstrip().startswith("|"):
            continue
        line = re.sub(r"`[^`]*`", " ", raw)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"(?:https?://|www\.)\S+", " ", line)
        if not line.strip():
            flush()
        elif _ITEM.match(line):
            flush()
            out.extend(s for s in _STOP.split(_ITEM.sub("", line)) if s.strip())
        else:
            para.append(line.strip())
    flush()
    return out


def ari(sents):
    words = [w for s in sents for w in _WORD.findall(s)]
    if not words or not sents:
        return None
    chars = sum(len(re.sub(r"[^A-Za-z0-9]", "", w)) for w in words)
    return 4.71 * chars / len(words) + 0.5 * len(words) / len(sents) - 21.43


def _factors(tokens):
    count, seen, n = 0.0, set(), 0
    for t in tokens:
        n += 1
        seen.add(t)
        if len(seen) / n <= MTLD_THRESHOLD:
            count += 1
            seen, n = set(), 0
    if n:
        count += (1 - len(seen) / n) / (1 - MTLD_THRESHOLD)
    return count


def mtld(sents):
    tokens = [w.lower() for s in sents for w in _WORD.findall(s)]
    fwd, back = _factors(tokens), _factors(tokens[::-1])
    if not fwd or not back:
        return None
    return (len(tokens) / fwd + len(tokens) / back) / 2


def measure(text):
    s = sentences(text)
    return ari(s), mtld(s)


def _f(v):
    return "n/a" if v is None else f"{v:.1f}"


def line(text):
    a, m = measure(text)
    return f"complexity: ARI {_f(a)}  MTLD {_f(m)}"


def change_line(before, after):
    (a0, m0), (a1, m1) = measure(before), measure(after)
    return (f"complexity: ARI {_f(a0)} -> {_f(a1)}  "
            f"MTLD {_f(m0)} -> {_f(m1)}")
