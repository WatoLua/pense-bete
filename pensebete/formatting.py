"""The formatting keys: Markdown markers put around the selection or at the start of its
lines, or taken away when they are already there, so that the same key undoes its work.

The rules work on lines of text and offsets in them; format() applies them to an editor
as one step that undo takes back.
"""

import re

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from .markdown import HEADING, INLINE, LIST_ITEM, QUOTE

# The marker each inline format adds, then the others that also make it.
MARKERS = {
    "bold": ("**", "__"),
    "italic": ("*", "_"),
    "strike": ("~~",),
    "code": ("`",),
}
PATTERNS = {kind: pattern for pattern, _, kind in INLINE}
LINE_FORMATS = ("heading1", "heading2", "heading3", "quote", "bullet")

# A line: its text and a range in it, (start, end), in characters.
Line = tuple[str, int, int]


def _run_before(line: str, index: int, char: str) -> int:
    count = 0
    while index - count > 0 and line[index - count - 1] == char:
        count += 1
    return count


def _run_after(line: str, index: int, char: str, limit: int | None = None) -> int:
    limit = len(line) if limit is None else limit
    count = 0
    while index + count < limit and line[index + count] == char:
        count += 1
    return count


def _makes(run: int, marker: str) -> bool:
    """Whether a run of a marker's character holds the marker: "**" is in "**" and
    "***"; "*" is in "*" and "***", not in "**", which is bold."""
    if len(marker) == 2:
        return run >= 2
    return run % 2 == 1


def span(line: str, start: int, end: int, kind: str) -> tuple[int, int, int, int] | None:
    """The markers of a format around a range: (opening start, opening end, closing
    start, closing end), or None when the range is not in that format.

    The markers count right outside the range, inside it at both ends, or around a
    span of the format that holds the range.
    """
    for marker in MARKERS[kind]:
        char, width = marker[0], len(marker)
        if _makes(_run_before(line, start, char), marker) \
                and _makes(_run_after(line, end, char), marker):
            return start - width, start, end, end + width
        opening = _run_after(line, start, char, end)
        closing = _run_before(line[:end], end, char) if opening < end - start else 0
        if opening + closing < end - start and _makes(opening, marker) \
                and _makes(closing, marker):
            return start, start + width, end - width, end
    for match in PATTERNS[kind].finditer(line):
        width = len(re.match(r"([*_~`])\1*", match.group()).group())
        width = min(width, len(MARKERS[kind][0]))
        if match.start() + width <= start and end <= match.end() - width:
            return match.start(), match.start() + width, match.end() - width, match.end()
    return None


def _trimmed(line: str, start: int, end: int) -> tuple[int, int]:
    """A range without the spaces at its ends: markers must touch the text they format."""
    while start < end and line[start].isspace():
        start += 1
    while end > start and line[end - 1].isspace():
        end -= 1
    return start, end


def toggle_inline(lines: list[Line], kind: str) -> list[Line]:
    """Put a format's markers around each line's range, or take them away when every
    range already has them. Lines of spaces only, among others, are left alone."""
    ranges = []
    for line, start, end in lines:
        start, end = _trimmed(line, start, end)
        blank = len(lines) > 1 and start == end
        ranges.append((line, start, end, None if blank else span(line, start, end, kind)))
    removing = all(found for line, start, end, found in ranges
                   if not (len(lines) > 1 and start == end))
    marker = MARKERS[kind][0]
    result = []
    for line, start, end, found in ranges:
        if len(lines) > 1 and start == end:
            result.append((line, start, end))
        elif removing:
            opening_start, opening_end, closing_start, closing_end = found
            text = (line[:opening_start] + line[opening_end:closing_start]
                    + line[closing_end:])
            width = opening_end - opening_start

            def moved(index: int) -> int:
                if index >= closing_end:
                    return index - width - (closing_end - closing_start)
                if index > closing_start:
                    return closing_start - width
                if index >= opening_end:
                    return index - width
                return min(index, opening_start)

            result.append((text, moved(start), moved(end)))
        elif found:
            result.append((line, start, end))
        else:
            text = line[:start] + marker + line[start:end] + marker + line[end:]
            result.append((text, start + len(marker), end + len(marker)))
    return result


def _prefix(line: str, kind: str) -> tuple[int, int] | None:
    """Where a line's marker of a line format is, (start, end), None without one."""
    if kind.startswith("heading"):
        heading = HEADING.match(line)
        if heading and len(heading.group(1)) == int(kind[-1]):
            return 0, heading.end(2)
        return None
    if kind == "quote":
        quote = QUOTE.match(line)
        if quote:  # one level of quoting: the first ">", and the space after it
            start = line.index(">")
            return start, start + (2 if line[start + 1:start + 2] == " " else 1)
        return None
    item = LIST_ITEM.match(line)
    if item and item.group(2):
        return len(item.group(1)), item.end()
    return None


def _without_other(line: str, kind: str) -> tuple[str, int]:
    """A line without the marker another format of its kind gave it, a heading of
    another level or a numbered item for a bullet: the new marker replaces it. Returns
    the line and how many characters went, from its start."""
    if kind.startswith("heading"):
        heading = HEADING.match(line)
        if heading:
            return line[heading.end(2):], heading.end(2)
    elif kind == "bullet":
        item = LIST_ITEM.match(line)
        if item:
            indent = item.group(1)
            return indent + line[item.end():], item.end() - len(indent)
    return line, 0


def toggle_lines(lines: list[str], kind: str) -> list[tuple[str, int, int]]:
    """Give each line the marker of a line format, a heading, a quote or a bullet, or take
    it away when every line has it; empty lines among others are left alone.

    Returns each line's new text with the change at its start: how many characters went
    and how many came, so that offsets in the line can follow.
    """
    skipped = [len(lines) > 1 and not line.strip() for line in lines]
    removing = all(_prefix(line, kind) for line, skip in zip(lines, skipped) if not skip)
    result = []
    for line, skip in zip(lines, skipped):
        found = _prefix(line, kind)
        if skip or (found and not removing):
            result.append((line, 0, 0))
        elif removing:
            start, end = found
            result.append((line[:start] + line[end:], end, start))
        else:
            rest, gone = _without_other(line, kind)
            if kind == "bullet":
                indent = re.match(r"\s*", rest).group()
                marker = indent + "- "
                rest = rest[len(indent):]
                gone += len(indent)
            elif kind == "quote":
                marker = "> "
            else:
                marker = "#" * int(kind[-1]) + " "
            result.append((marker + rest, gone, len(marker)))
    return result


def _units(text: str, index: int) -> int:
    """An offset in characters as the editor counts it, in UTF-16 code units."""
    return len(text[:index].encode("utf-16-le")) // 2


def _index(text: str, units: int) -> int:
    index = 0
    while index < len(text) and _units(text, index + 1) <= units:
        index += 1
    return index


def format(editor: QPlainTextEdit, kind: str) -> None:
    """Toggle a format on the editor's selection, or at its cursor, as one step."""
    cursor = editor.textCursor()
    document = editor.document()
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    first, last = document.findBlock(start), document.findBlock(end)
    # A selection that ends at the start of a line leaves that line out.
    if end > start and end == last.position() and last != first:
        last = last.previous()
    blocks = [first]
    while blocks[-1] != last:
        blocks.append(blocks[-1].next())
    texts = [block.text() for block in blocks]
    # Where the anchor and the cursor are: (line among these, character in it).
    ends = []
    for position in (cursor.anchor(), cursor.position()):
        line = max(0, min(document.findBlock(position).blockNumber() - first.blockNumber(),
                          len(blocks) - 1))
        offset = position - blocks[line].position()
        ends.append((line, _index(texts[line], max(0, min(offset, _units(texts[line],
                                                                        len(texts[line])))))))
    if kind in LINE_FORMATS:
        changed = toggle_lines(texts, kind)
        new_texts = [text for text, _, _ in changed]

        def follow(line: int, index: int) -> int:
            text, gone, came = changed[line]
            return index - gone + came if index >= gone else came
        new_ends = [(line, follow(line, index)) for line, index in ends]
    else:
        ranges = [(text, 0, len(text)) for text in texts]
        low, high = sorted(ends)
        ranges[low[0]] = (texts[low[0]], low[1], ranges[low[0]][2])
        ranges[high[0]] = (texts[high[0]], ranges[high[0]][1], high[1])
        changed = toggle_inline(ranges, kind)
        new_texts = [text for text, _, _ in changed]
        new_low, new_high = (low[0], changed[low[0]][1]), (high[0], changed[high[0]][2])
        new_ends = [new_low, new_high] if ends[0] <= ends[1] else [new_high, new_low]
    edit = QTextCursor(document)
    edit.beginEditBlock()
    for block, text, new_text in reversed(list(zip(blocks, texts, new_texts))):
        if new_text != text:
            edit.setPosition(block.position())
            edit.setPosition(block.position() + len(block.text().encode("utf-16-le")) // 2,
                             QTextCursor.KeepAnchor)
            edit.insertText(new_text)
    edit.endEditBlock()
    number = first.blockNumber()
    positions = [document.findBlockByNumber(number + line).position()
                 + _units(new_texts[line], index) for line, index in new_ends]
    result = QTextCursor(document)
    result.setPosition(positions[0])
    result.setPosition(positions[1], QTextCursor.KeepAnchor)
    editor.setTextCursor(result)
