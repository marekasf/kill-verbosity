"""A stdlib-only CommonMark block parser: headings, tables and blockquotes.

`parser_blocks` in `_legacy.py` needs three things a line-at-a-time scanner
cannot decide: setext headings, tables written without outer pipes, and lazy
blockquote continuation lines. This module answers them with the block-level
half of a CommonMark parser and nothing else -- there is no inline parsing and
no rendering.

It is a port of the block rules of markdown-it-py (the "commonmark" preset,
with the GFM table rule enabled and the front-matter rule of mdit-py-plugins),
kept rule-for-rule so the token stream's types and line maps match the
original's. Only the tokens a caller reads carry data: `type`, `tag`, `map`
(0-based `[first, end)` line range) and, for `inline` tokens, `content`.

Portions derived from markdown-it-py and mdit-py-plugins:
Copyright (c) 2020 ExecutableBookProject
Copyright (c) 2014 Vitaly Puzrin, Alex Kocharin
Released under the MIT License:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import re

MAX_NESTING = 20
SPACE = (" ", "\t")


class Token:
    __slots__ = ("type", "tag", "map", "content")

    def __init__(self, type_, tag, map_=None, content=""):
        self.type, self.tag, self.map, self.content = type_, tag, map_, content

    def __repr__(self):
        return f"Token({self.type!r}, {self.tag!r}, {self.map!r})"


def _at(s, i):
    return s[i] if 0 <= i < len(s) else None


class _State:
    def __init__(self, src):
        self.src = src
        self.tokens = []
        self.bMarks, self.eMarks, self.tShift = [], [], []
        self.sCount, self.bsCount = [], []
        self.blkIndent = 0
        self.line = 0
        self.tight = False
        self.listIndent = -1
        self.parentType = "root"
        self.level = 0

        found = False
        start = indent = offset = 0
        n = len(src)
        for pos, ch in enumerate(src):
            if not found:
                if ch in SPACE:
                    indent += 1
                    offset += 4 - offset % 4 if ch == "\t" else 1
                    continue
                found = True
            if ch == "\n" or pos == n - 1:
                if ch != "\n":
                    pos += 1
                self.bMarks.append(start)
                self.eMarks.append(pos)
                self.tShift.append(indent)
                self.sCount.append(offset)
                self.bsCount.append(0)
                found = False
                indent = offset = 0
                start = pos + 1
        for arr, v in ((self.bMarks, n), (self.eMarks, n), (self.tShift, 0),
                       (self.sCount, 0), (self.bsCount, 0)):
            arr.append(v)
        self.lineMax = len(self.bMarks) - 1

    def push(self, type_, tag, nesting, map_=None, content=""):
        if nesting < 0:
            self.level -= 1
        tok = Token(type_, tag, map_, content)
        if nesting > 0:
            self.level += 1
        self.tokens.append(tok)
        return tok

    def isEmpty(self, line):
        return self.bMarks[line] + self.tShift[line] >= self.eMarks[line]

    def skipEmptyLines(self, line):
        while line < self.lineMax:
            if self.bMarks[line] + self.tShift[line] < self.eMarks[line]:
                break
            line += 1
        return line

    def skipSpaces(self, pos):
        while pos < len(self.src) and self.src[pos] in SPACE:
            pos += 1
        return pos

    def skipSpacesBack(self, pos, minimum):
        if pos <= minimum:
            return pos
        while pos > minimum:
            pos -= 1
            if self.src[pos] not in SPACE:
                return pos + 1
        return pos

    def skipChars(self, pos, ch):
        while pos < len(self.src) and self.src[pos] == ch:
            pos += 1
        return pos

    def skipCharsBack(self, pos, ch, minimum):
        if pos <= minimum:
            return pos
        while pos > minimum:
            pos -= 1
            if self.src[pos] != ch:
                return pos + 1
        return pos

    def getLines(self, begin, end, indent, keepLastLF):
        if begin >= end:
            return ""
        out = []
        for line in range(begin, end):
            lineIndent = 0
            lineStart = first = self.bMarks[line]
            last = (self.eMarks[line] + 1 if line + 1 < end or keepLastLF
                    else self.eMarks[line])
            while first < last and lineIndent < indent:
                ch = self.src[first]
                if ch in SPACE:
                    if ch == "\t":
                        lineIndent += 4 - (lineIndent + self.bsCount[line]) % 4
                    else:
                        lineIndent += 1
                elif first - lineStart < self.tShift[line]:
                    lineIndent += 1
                else:
                    break
                first += 1
            if lineIndent > indent:
                out.append(" " * (lineIndent - indent) + self.src[first:last])
            else:
                out.append(self.src[first:last])
        return "".join(out)

    def is_code_block(self, line):
        return self.sCount[line] - self.blkIndent >= 4

    def line_text(self, line):
        return self.src[self.bMarks[line] + self.tShift[line]:self.eMarks[line]]


def _terminates(st, kind, line, end):
    return any(rule(st, line, end, True) for rule in _ALT[kind])


# --- rules -----------------------------------------------------------------

def front_matter(st, startLine, endLine, silent):
    start = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    if startLine != 0 or not st.src or st.src[0] != "-":
        return False
    pos = start + 1
    while pos <= maximum and pos < len(st.src):
        if st.src[pos] != "-":
            break
        pos += 1
    count = pos - start
    if count < 3:
        return False
    if silent:
        return True
    nextLine, closed = startLine, False
    while True:
        nextLine += 1
        if nextLine >= endLine:
            return False
        if st.src[start:maximum] == "...":
            break
        start = st.bMarks[nextLine] + st.tShift[nextLine]
        maximum = st.eMarks[nextLine]
        if start < maximum and st.sCount[nextLine] < st.blkIndent:
            break
        if _at(st.src, start) != "-":
            continue
        if st.is_code_block(nextLine):
            continue
        pos = start + 1
        while pos < maximum and st.src[pos] == "-":
            pos += 1
        if pos - start < count:
            continue
        if st.skipSpaces(pos) < maximum:
            continue
        closed = True
        break
    st.line = nextLine + (1 if closed else 0)
    st.push("front_matter", "", 0, [startLine, st.line])
    return True


_HEADER_CELL = re.compile(r"^:?-+:?$")


def _escaped_split(s):
    result, current, last, escaped = [], "", 0, False
    for pos, ch in enumerate(s):
        if ch == "|":
            if not escaped:
                result.append(current + s[last:pos])
                current, last = "", pos + 1
            else:
                current += s[last:pos - 1]
                last = pos
        escaped = ch == "\\"
    result.append(current + s[last:])
    return result


def table(st, startLine, endLine, silent):
    if startLine + 2 > endLine:
        return False
    nextLine = startLine + 1
    if st.sCount[nextLine] < st.blkIndent or st.is_code_block(nextLine):
        return False
    pos = st.bMarks[nextLine] + st.tShift[nextLine]
    end = st.eMarks[nextLine]
    if pos >= end:
        return False
    first = st.src[pos]
    pos += 1
    if first not in "|-:" or pos >= end:
        return False
    second = st.src[pos]
    pos += 1
    if second not in "|-:" and second not in SPACE:
        return False
    if first == "-" and second in SPACE:
        return False
    while pos < end:
        if st.src[pos] not in "|-:" and st.src[pos] not in SPACE:
            return False
        pos += 1
    columns = st.line_text(startLine + 1).split("|")
    aligns = 0
    for i, col in enumerate(columns):
        t = col.strip()
        if not t:
            if i in (0, len(columns) - 1):
                continue
            return False
        if not _HEADER_CELL.search(t):
            return False
        aligns += 1
    text = st.line_text(startLine).strip()
    if "|" not in text or st.is_code_block(startLine):
        return False
    cols = _escaped_split(text)
    if cols and cols[0] == "":
        cols.pop(0)
    if cols and cols[-1] == "":
        cols.pop()
    ncols = len(cols)
    if ncols == 0 or ncols != aligns:
        return False
    if silent:
        return True
    old_parent = st.parentType
    st.parentType = "table"
    tok = st.push("table_open", "table", 1, [startLine, 0])
    autocompleted = 0
    nextLine = startLine + 2
    while nextLine < endLine:
        if st.sCount[nextLine] < st.blkIndent:
            break
        if _terminates(st, "blockquote", nextLine, endLine):
            break
        text = st.line_text(nextLine).strip()
        if not text or st.is_code_block(nextLine):
            break
        cols = _escaped_split(text)
        if cols and cols[0] == "":
            cols.pop(0)
        if cols and cols[-1] == "":
            cols.pop()
        autocompleted += ncols - len(cols)
        if autocompleted > 0x10000:
            break
        nextLine += 1
    st.push("table_close", "table", -1)
    tok.map[1] = nextLine
    st.parentType = old_parent
    st.line = nextLine
    return True


def code(st, startLine, endLine, silent):
    if not st.is_code_block(startLine):
        return False
    last = nextLine = startLine + 1
    while nextLine < endLine:
        if st.isEmpty(nextLine):
            nextLine += 1
            continue
        if st.is_code_block(nextLine):
            nextLine += 1
            last = nextLine
            continue
        break
    st.line = last
    st.push("code_block", "code", 0, [startLine, st.line])
    return True


def fence(st, startLine, endLine, silent):
    pos = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    if st.is_code_block(startLine) or pos + 3 > maximum:
        return False
    marker = st.src[pos]
    if marker not in ("~", "`"):
        return False
    mem = pos
    pos = st.skipChars(pos, marker)
    length = pos - mem
    if length < 3:
        return False
    if marker == "`" and "`" in st.src[pos:maximum]:
        return False
    if silent:
        return True
    nextLine, closed = startLine, False
    while True:
        nextLine += 1
        if nextLine >= endLine:
            break
        pos = mem = st.bMarks[nextLine] + st.tShift[nextLine]
        maximum = st.eMarks[nextLine]
        if pos < maximum and st.sCount[nextLine] < st.blkIndent:
            break
        if pos >= len(st.src):
            break
        if st.src[pos] != marker:
            continue
        if st.is_code_block(nextLine):
            continue
        pos = st.skipChars(pos, marker)
        if pos - mem < length:
            continue
        if st.skipSpaces(pos) < maximum:
            continue
        closed = True
        break
    st.line = nextLine + (1 if closed else 0)
    st.push("fence", "code", 0, [startLine, st.line])
    return True


def _quote_line(st, line):
    """Strip one `>` marker off `line` in place; return (old marks, empty)."""
    pos = st.bMarks[line] + st.tShift[line] + 1
    maximum = st.eMarks[line]
    initial = offset = st.sCount[line] + 1
    nxt = _at(st.src, pos)
    adjustTab = False
    if nxt == " ":
        pos += 1
        initial += 1
        offset += 1
        spaceAfter = True
    elif nxt == "\t":
        spaceAfter = True
        if (st.bsCount[line] + offset) % 4 == 3:
            pos += 1
            initial += 1
            offset += 1
        else:
            adjustTab = True
    else:
        spaceAfter = False
    old = (st.bMarks[line], st.bsCount[line], st.tShift[line], st.sCount[line])
    st.bMarks[line] = pos
    while pos < maximum:
        ch = st.src[pos]
        if ch == "\t":
            offset += 4 - (offset + st.bsCount[line] + (1 if adjustTab else 0)) % 4
        elif ch == " ":
            offset += 1
        else:
            break
        pos += 1
    st.bsCount[line] = st.sCount[line] + 1 + (1 if spaceAfter else 0)
    st.sCount[line] = offset - initial
    st.tShift[line] = pos - st.bMarks[line]
    return old, pos >= maximum


def blockquote(st, startLine, endLine, silent):
    oldLineMax = st.lineMax
    pos = st.bMarks[startLine] + st.tShift[startLine]
    if st.is_code_block(startLine) or _at(st.src, pos) != ">":
        return False
    if silent:
        return True
    saved = []
    old, lastLineEmpty = _quote_line(st, startLine)
    saved.append(old)
    oldParent = st.parentType
    st.parentType = "blockquote"
    nextLine = startLine + 1
    while nextLine < endLine:
        isOutdented = st.sCount[nextLine] < st.blkIndent
        pos = st.bMarks[nextLine] + st.tShift[nextLine]
        if pos >= st.eMarks[nextLine]:
            break
        if st.src[pos] == ">" and not isOutdented:
            old, lastLineEmpty = _quote_line(st, nextLine)
            saved.append(old)
            nextLine += 1
            continue
        if lastLineEmpty:
            break
        if _terminates(st, "blockquote", nextLine, endLine):
            st.lineMax = nextLine
            if st.blkIndent != 0:
                saved.append((st.bMarks[nextLine], st.bsCount[nextLine],
                              st.tShift[nextLine], st.sCount[nextLine]))
                st.sCount[nextLine] -= st.blkIndent
            break
        saved.append((st.bMarks[nextLine], st.bsCount[nextLine],
                      st.tShift[nextLine], st.sCount[nextLine]))
        st.sCount[nextLine] = -1
        nextLine += 1
    oldIndent = st.blkIndent
    st.blkIndent = 0
    tok = st.push("blockquote_open", "blockquote", 1, [startLine, 0])
    tokenize(st, startLine, nextLine)
    st.push("blockquote_close", "blockquote", -1)
    st.lineMax = oldLineMax
    st.parentType = oldParent
    tok.map[1] = st.line
    for i, (b, bs, ts, sc) in enumerate(saved):
        st.bMarks[i + startLine] = b
        st.bsCount[i + startLine] = bs
        st.tShift[i + startLine] = ts
        st.sCount[i + startLine] = sc
    st.blkIndent = oldIndent
    return True


def hr(st, startLine, endLine, silent):
    pos = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    if st.is_code_block(startLine):
        return False
    marker = _at(st.src, pos)
    if marker not in ("*", "-", "_"):
        return False
    pos += 1
    cnt = 1
    while pos < maximum:
        ch = st.src[pos]
        pos += 1
        if ch != marker and ch not in SPACE:
            return False
        if ch == marker:
            cnt += 1
    if cnt < 3:
        return False
    if silent:
        return True
    st.line = startLine + 1
    st.push("hr", "hr", 0, [startLine, st.line])
    return True


def _bullet_marker(st, line):
    pos = st.bMarks[line] + st.tShift[line]
    maximum = st.eMarks[line]
    if _at(st.src, pos) not in ("*", "-", "+"):
        return -1
    pos += 1
    if pos < maximum and st.src[pos] not in SPACE:
        return -1
    return pos


def _ordered_marker(st, line):
    start = pos = st.bMarks[line] + st.tShift[line]
    maximum = st.eMarks[line]
    if pos + 1 >= maximum:
        return -1
    if not "0" <= st.src[pos] <= "9":
        return -1
    pos += 1
    while True:
        if pos >= maximum:
            return -1
        ch = st.src[pos]
        pos += 1
        if "0" <= ch <= "9":
            if pos - start >= 10:
                return -1
            continue
        if ch in (")", "."):
            break
        return -1
    if pos < maximum and st.src[pos] not in SPACE:
        return -1
    return pos


def list_block(st, startLine, endLine, silent):
    terminating = False
    if st.is_code_block(startLine):
        return False
    if (st.listIndent >= 0 and st.sCount[startLine] - st.listIndent >= 4
            and st.sCount[startLine] < st.blkIndent):
        return False
    if (silent and st.parentType == "paragraph"
            and st.sCount[startLine] >= st.blkIndent):
        terminating = True
    after = _ordered_marker(st, startLine)
    if after >= 0:
        ordered = True
        start = st.bMarks[startLine] + st.tShift[startLine]
        if terminating and int(st.src[start:after - 1]) != 1:
            return False
    else:
        after = _bullet_marker(st, startLine)
        if after < 0:
            return False
        ordered = False
    if terminating and st.skipSpaces(after) >= st.eMarks[startLine]:
        return False
    markerChar = st.src[after - 1]
    if silent:
        return True
    kind = "ordered_list" if ordered else "bullet_list"
    tok = st.push(kind + "_open", "ol" if ordered else "ul", 1, [startLine, 0])
    nextLine = startLine
    prevEmptyEnd = False
    oldParent = st.parentType
    st.parentType = "list"
    while nextLine < endLine:
        pos = after
        maximum = st.eMarks[nextLine]
        initial = offset = (st.sCount[nextLine] + after
                            - (st.bMarks[startLine] + st.tShift[startLine]))
        while pos < maximum:
            ch = st.src[pos]
            if ch == "\t":
                offset += 4 - (offset + st.bsCount[nextLine]) % 4
            elif ch == " ":
                offset += 1
            else:
                break
            pos += 1
        contentStart = pos
        indentAfter = 1 if contentStart >= maximum else offset - initial
        if indentAfter > 4:
            indentAfter = 1
        indent = initial + indentAfter
        item = st.push("list_item_open", "li", 1, [startLine, 0])
        oldTight = st.tight
        oldTShift = st.tShift[startLine]
        oldSCount = st.sCount[startLine]
        oldListIndent = st.listIndent
        st.listIndent = st.blkIndent
        st.blkIndent = indent
        st.tight = True
        st.tShift[startLine] = contentStart - st.bMarks[startLine]
        st.sCount[startLine] = offset
        if contentStart >= maximum and st.isEmpty(startLine + 1):
            st.line = min(st.line + 2, endLine)
        else:
            tokenize(st, startLine, endLine)
        prevEmptyEnd = st.line - startLine > 1 and st.isEmpty(st.line - 1)
        st.blkIndent = st.listIndent
        st.listIndent = oldListIndent
        st.tShift[startLine] = oldTShift
        st.sCount[startLine] = oldSCount
        st.tight = oldTight
        st.push("list_item_close", "li", -1)
        nextLine = startLine = st.line
        item.map[1] = nextLine
        if nextLine >= endLine:
            break
        if st.sCount[nextLine] < st.blkIndent or st.is_code_block(startLine):
            break
        if _terminates(st, "list", nextLine, endLine):
            break
        if ordered:
            after = _ordered_marker(st, nextLine)
        else:
            after = _bullet_marker(st, nextLine)
        if after < 0 or markerChar != st.src[after - 1]:
            break
    st.push(kind + "_close", "ol" if ordered else "ul", -1)
    tok.map[1] = nextLine
    st.line = nextLine
    st.parentType = oldParent
    return True


# --- link reference definitions (only whether one is there, and its end) ---

def _link_destination(s, pos, maximum):
    start = pos
    if _at(s, pos) == "<":
        pos += 1
        while pos < maximum:
            ch = s[pos]
            if ch in ("\n", "<"):
                return None
            if ch == ">":
                return pos + 1, s[start + 1:pos]
            if ch == "\\" and pos + 1 < maximum:
                pos += 2
                continue
            pos += 1
        return None
    level = 0
    while pos < maximum:
        ch = s[pos]
        if ch == " " or ord(ch) < 0x20 or ord(ch) == 0x7F:
            break
        if ch == "\\" and pos + 1 < maximum:
            if s[pos + 1] == " ":
                break
            pos += 2
            continue
        if ch == "(":
            level += 1
            if level > 32:
                return None
        if ch == ")":
            if level == 0:
                break
            level -= 1
        pos += 1
    if start == pos or level != 0:
        return None
    return pos, s[start:pos]


class _Title:
    __slots__ = ("ok", "can_continue", "pos", "text", "marker")

    def __init__(self):
        self.ok = self.can_continue = False
        self.pos, self.text, self.marker = 0, "", ""


def _link_title(s, start, maximum, prev=None):
    pos = start
    res = _Title()
    if prev is not None:
        res.text, res.marker = prev.text, prev.marker
    else:
        if pos >= maximum:
            return res
        marker = s[pos]
        if marker not in ('"', "'", "("):
            return res
        start += 1
        pos += 1
        res.marker = ")" if marker == "(" else marker
    while pos < maximum:
        ch = s[pos]
        if ch == res.marker:
            res.pos = pos + 1
            res.text += s[start:pos]
            res.ok = True
            return res
        if ch == "(" and res.marker == ")":
            return res
        if ch == "\\" and pos + 1 < maximum:
            pos += 1
        pos += 1
    res.can_continue = True
    res.text += s[start:pos]
    return res


_BAD_PROTO = re.compile(r"^(vbscript|javascript|file|data):")
_GOOD_DATA = re.compile(r"^data:image\/(gif|png|jpeg|webp);")


def _next_ref_line(st, nextLine):
    if nextLine >= st.lineMax or st.isEmpty(nextLine):
        return None
    cont = st.is_code_block(nextLine) or st.sCount[nextLine] < 0
    if not cont:
        old = st.parentType
        st.parentType = "reference"
        stop = _terminates(st, "reference", nextLine, st.lineMax)
        st.parentType = old
        if stop:
            return None
    return st.src[st.bMarks[nextLine] + st.tShift[nextLine]:
                  st.eMarks[nextLine] + 1]


def reference(st, startLine, _endLine, silent):
    pos = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    nextLine = startLine + 1
    if st.is_code_block(startLine) or _at(st.src, pos) != "[":
        return False
    s = st.src[pos:maximum + 1]
    maximum = len(s)
    labelEnd = None
    pos = 1
    while pos < maximum:
        ch = s[pos]
        if ch == "[":
            return False
        if ch == "]":
            labelEnd = pos
            break
        if ch == "\n":
            more = _next_ref_line(st, nextLine)
            if more is not None:
                s += more
                maximum = len(s)
                nextLine += 1
        elif ch == "\\":
            pos += 1
            if pos < maximum and s[pos] == "\n":
                more = _next_ref_line(st, nextLine)
                if more is not None:
                    s += more
                    maximum = len(s)
                    nextLine += 1
        pos += 1
    if labelEnd is None or _at(s, labelEnd + 1) != ":":
        return False
    pos = labelEnd + 2
    while pos < maximum:
        ch = s[pos]
        if ch == "\n":
            more = _next_ref_line(st, nextLine)
            if more is not None:
                s += more
                maximum = len(s)
                nextLine += 1
        elif ch not in SPACE:
            break
        pos += 1
    dest = _link_destination(s, pos, maximum)
    if dest is None:
        return False
    href = dest[1].strip().lower()
    if _BAD_PROTO.search(href) and not _GOOD_DATA.search(href):
        return False
    pos = dest[0]
    destEndPos, destEndLine = pos, nextLine
    start = pos
    while pos < maximum:
        ch = s[pos]
        if ch == "\n":
            more = _next_ref_line(st, nextLine)
            if more is not None:
                s += more
                maximum = len(s)
                nextLine += 1
        elif ch not in SPACE:
            break
        pos += 1
    title = _link_title(s, pos, maximum)
    while title.can_continue:
        more = _next_ref_line(st, nextLine)
        if more is None:
            break
        s += more
        pos = maximum
        maximum = len(s)
        nextLine += 1
        title = _link_title(s, pos, maximum, title)
    if pos < maximum and start != pos and title.ok:
        has_title = bool(title.text)
        pos = title.pos
    else:
        has_title = False
        pos, nextLine = destEndPos, destEndLine
    while pos < maximum and s[pos] in SPACE:
        pos += 1
    if pos < maximum and s[pos] != "\n" and has_title:
        has_title = False
        pos, nextLine = destEndPos, destEndLine
        while pos < maximum and s[pos] in SPACE:
            pos += 1
    if pos < maximum and s[pos] != "\n":
        return False
    if not re.sub(r"\s+", " ", s[1:labelEnd].strip()):
        return False
    if silent:
        return True
    st.line = nextLine
    return True


# --- html blocks -----------------------------------------------------------

_BLOCK_NAMES = (
    "address article aside base basefont blockquote body caption center col "
    "colgroup dd details dialog dir div dl dt fieldset figcaption figure "
    "footer form frame frameset h1 h2 h3 h4 h5 h6 head header hr html iframe "
    "legend li link main menu menuitem nav noframes ol optgroup option p "
    "param search section summary table tbody td tfoot th thead title tr "
    "track ul").split()
_ATTR = ("(?:\\s+[a-zA-Z_:][a-zA-Z0-9:._-]*(?:\\s*=\\s*"
         "(?:[^\"'=<>`\\x00-\\x20]+|'[^']*'|\"[^\"]*\"))?)")
_OPEN_CLOSE = ("^(?:<[A-Za-z][A-Za-z0-9\\-]*" + _ATTR + "*\\s*\\/?>"
               "|<\\/[A-Za-z][A-Za-z0-9\\-]*\\s*>)")
_HTML_SEQUENCES = [
    (re.compile(r"^<(script|pre|style|textarea)(?=(\s|>|$))", re.I),
     re.compile(r"<\/(script|pre|style|textarea)>", re.I), True),
    (re.compile(r"^<!--"), re.compile(r"-->"), True),
    (re.compile(r"^<\?"), re.compile(r"\?>"), True),
    (re.compile(r"^<![A-Z]"), re.compile(r">"), True),
    (re.compile(r"^<!\[CDATA\["), re.compile(r"\]\]>"), True),
    (re.compile("^</?(" + "|".join(_BLOCK_NAMES) + ")(?=(\\s|/?>|$))", re.I),
     re.compile(r"^$"), True),
    (re.compile(_OPEN_CLOSE + "\\s*$"), re.compile(r"^$"), False),
]


def html_block(st, startLine, endLine, silent):
    pos = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    if st.is_code_block(startLine) or _at(st.src, pos) != "<":
        return False
    text = st.src[pos:maximum]
    seq = next((q for q in _HTML_SEQUENCES if q[0].search(text)), None)
    if seq is None:
        return False
    if silent:
        return seq[2]
    nextLine = startLine + 1
    if not seq[1].search(text):
        while nextLine < endLine:
            if st.sCount[nextLine] < st.blkIndent:
                break
            text = st.line_text(nextLine)
            if seq[1].search(text):
                if text:
                    nextLine += 1
                break
            nextLine += 1
    st.line = nextLine
    st.push("html_block", "", 0, [startLine, nextLine])
    return True


# --- headings and paragraphs -------------------------------------------------

def heading(st, startLine, endLine, silent):
    pos = st.bMarks[startLine] + st.tShift[startLine]
    maximum = st.eMarks[startLine]
    if st.is_code_block(startLine):
        return False
    if _at(st.src, pos) != "#" or pos >= maximum:
        return False
    level = 1
    pos += 1
    ch = _at(st.src, pos)
    while ch == "#" and pos < maximum and level <= 6:
        level += 1
        pos += 1
        ch = _at(st.src, pos)
    if level > 6 or (pos < maximum and ch not in SPACE):
        return False
    if silent:
        return True
    maximum = st.skipSpacesBack(maximum, pos)
    tmp = st.skipCharsBack(maximum, "#", pos)
    if tmp > pos and st.src[tmp - 1] in SPACE:
        maximum = tmp
    st.line = startLine + 1
    st.push("heading_open", f"h{level}", 1, [startLine, st.line])
    st.push("inline", "", 0, [startLine, st.line], st.src[pos:maximum].strip())
    st.push("heading_close", f"h{level}", -1)
    return True


def lheading(st, startLine, endLine, silent):
    level = None
    nextLine = startLine + 1
    if st.is_code_block(startLine):
        return False
    oldParent = st.parentType
    st.parentType = "paragraph"
    while nextLine < endLine and not st.isEmpty(nextLine):
        if st.sCount[nextLine] - st.blkIndent > 3:
            nextLine += 1
            continue
        if st.sCount[nextLine] >= st.blkIndent:
            pos = st.bMarks[nextLine] + st.tShift[nextLine]
            maximum = st.eMarks[nextLine]
            if pos < maximum:
                marker = st.src[pos]
                if marker in ("-", "="):
                    pos = st.skipSpaces(st.skipChars(pos, marker))
                    if pos >= maximum:
                        level = 1 if marker == "=" else 2
                        break
        if st.sCount[nextLine] < 0:
            nextLine += 1
            continue
        if _terminates(st, "paragraph", nextLine, endLine):
            break
        nextLine += 1
    if not level:
        # The original leaves parentType set to "paragraph" here; kept so the
        # rules that read it afterwards see what they saw there.
        return False
    content = st.getLines(startLine, nextLine, st.blkIndent, False).strip()
    st.line = nextLine + 1
    st.push("heading_open", f"h{level}", 1, [startLine, st.line])
    st.push("inline", "", 0, [startLine, st.line - 1], content)
    st.push("heading_close", f"h{level}", -1)
    st.parentType = oldParent
    return True


def paragraph(st, startLine, endLine, silent):
    nextLine = startLine + 1
    endLine = st.lineMax
    oldParent = st.parentType
    st.parentType = "paragraph"
    while nextLine < endLine:
        if st.isEmpty(nextLine):
            break
        if st.sCount[nextLine] - st.blkIndent > 3 or st.sCount[nextLine] < 0:
            nextLine += 1
            continue
        if _terminates(st, "paragraph", nextLine, endLine):
            break
        nextLine += 1
    content = st.getLines(startLine, nextLine, st.blkIndent, False).strip()
    st.line = nextLine
    st.push("paragraph_open", "p", 1, [startLine, st.line])
    st.push("inline", "", 0, [startLine, st.line], content)
    st.push("paragraph_close", "p", -1)
    st.parentType = oldParent
    return True


_RULES = [front_matter, table, code, fence, blockquote, hr, list_block,
          reference, html_block, heading, lheading, paragraph]
_TERMINATORS = {
    "paragraph": [front_matter, table, fence, blockquote, hr, list_block,
                  html_block, heading],
    "blockquote": [front_matter, fence, blockquote, hr, list_block,
                   html_block, heading],
    "list": [front_matter, fence, blockquote, hr],
}
_TERMINATORS["reference"] = _TERMINATORS["paragraph"]
_ALT = _TERMINATORS


def tokenize(st, startLine, endLine):
    line = startLine
    hasEmptyLines = False
    while line < endLine:
        st.line = line = st.skipEmptyLines(line)
        if line >= endLine:
            break
        if st.sCount[line] < st.blkIndent:
            break
        if st.level >= MAX_NESTING:
            st.line = endLine
            break
        for rule in _RULES:
            if rule(st, line, endLine, False):
                break
        st.tight = not hasEmptyLines
        line = st.line
        if line - 1 < endLine and st.isEmpty(line - 1):
            hasEmptyLines = True
        if line < endLine and st.isEmpty(line):
            hasEmptyLines = True
            line += 1
            st.line = line


def parse(text):
    """The block token stream for `text`, in document order."""
    src = re.sub(r"\r\n?|\n", "\n", text).replace("\0", "�")
    if not src:
        return []
    st = _State(src)
    tokenize(st, st.line, st.lineMax)
    return st.tokens
