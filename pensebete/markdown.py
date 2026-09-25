"""Markdown shown formatted in place: the text stays exactly as typed, only its look changes.

Headings, emphasis, code, task lists and tables are styled over the source, their
markers dimmed rather than hidden, so that nothing is ever rewritten behind the
user's back: the note, its history and its differences stay those of the text typed.
"""

import re

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QKeyEvent, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit

HEADING = re.compile(r"^(#{1,6})(\s+)(.*)$")
TASK = re.compile(r"^(\s*[-*+]\s+)\[([ xX])\](?=\s|$)")
LIST_ITEM = re.compile(r"^(\s*)(?:([-*+])|(\d+)([.)]))(\s+)(\[[ xX]\]\s+)?")
QUOTE = re.compile(r"^(\s*>+)")
FENCE = re.compile(r"^\s*(```|~~~)")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*(:?-+:?\s*)?\|?\s*$")
# Inline spans: (pattern, marker length, format name). Code first, so that nothing
# inside code is taken for emphasis.
INLINE = (
    (re.compile(r"`[^`\n]+`"), 1, "code"),
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__"), 2, "bold"),
    (re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])"
                r"|(?<![_\w])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![_\w])"), 1, "italic"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), 2, "strike"),
)
HEADING_SCALES = (1.6, 1.4, 1.25, 1.1, 1.0, 1.0)
IN_CODE_BLOCK = 1  # block state: inside a fenced code block


class MarkdownHighlighter(QSyntaxHighlighter):
    """Styles the Markdown of a document, for a text color and size set by the note."""

    def __init__(self, document, font_size: int, text_color: str):
        super().__init__(document)
        self.enabled = False
        self.font_size = font_size
        self.text_color = QColor(text_color)

    def configure(self, enabled: bool, font_size: int, text_color: str) -> None:
        changed = (enabled, font_size, QColor(text_color)) != (
            self.enabled, self.font_size, self.text_color)
        self.enabled, self.font_size, self.text_color = enabled, font_size, QColor(text_color)
        if changed:
            self.rehighlight()

    def _format(self, kind: str) -> QTextCharFormat:
        text_format = QTextCharFormat()
        if kind == "marker":
            dimmed = QColor(self.text_color)
            dimmed.setAlpha(110)
            text_format.setForeground(dimmed)
        elif kind == "bold":
            text_format.setFontWeight(QFont.Bold)
        elif kind == "italic":
            text_format.setFontItalic(True)
        elif kind == "strike":
            text_format.setFontStrikeOut(True)
        elif kind in ("code", "table"):
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            font.setPixelSize(self.font_size)
            text_format.setFont(font, QTextCharFormat.FontPropertiesSpecifiedOnly)
            text_format.setFontFamilies(font.families())
        elif kind == "done":
            text_format.setFontStrikeOut(True)
            done = QColor(self.text_color)
            done.setAlpha(150)
            text_format.setForeground(done)
        return text_format

    def highlightBlock(self, text: str) -> None:
        if not self.enabled:
            self.setCurrentBlockState(0)
            return
        in_code = self.previousBlockState() == IN_CODE_BLOCK
        if FENCE.match(text):
            self.setFormat(0, len(text), self._format("marker"))
            self.setCurrentBlockState(0 if in_code else IN_CODE_BLOCK)
            return
        self.setCurrentBlockState(IN_CODE_BLOCK if in_code else 0)
        if in_code:
            self.setFormat(0, len(text), self._format("code"))
            return
        if TABLE_ROW.match(text) or TABLE_SEPARATOR.match(text) and "|" in text:
            self.setFormat(0, len(text), self._format("table"))
            for match in re.finditer(r"\||(?<=\|)[\s:-]+(?=\|)" if TABLE_SEPARATOR.match(text)
                                     else r"\|", text):
                self._merge(match.start(), match.end(), "marker")
            return

        heading = HEADING.match(text)
        if heading:
            level = len(heading.group(1))
            font = QFont()
            font.setPixelSize(round(self.font_size * HEADING_SCALES[level - 1]))
            font.setBold(True)
            text_format = QTextCharFormat()
            text_format.setFont(font, QTextCharFormat.FontPropertiesSpecifiedOnly)
            self.setFormat(0, len(text), text_format)
            self._merge(0, heading.end(2), "marker")
        quote = QUOTE.match(text)
        if quote:
            self._merge(0, quote.end(), "marker")
            self._merge(quote.end(), len(text), "italic")
        task = TASK.match(text)
        if task:
            if task.group(2) in "xX":
                self._merge(task.end(), len(text), "done")
            self._merge(task.start(1), task.end(1), "marker")
            # In a fixed font, "[ ]" is as wide as "[x]", and reads as a box.
            self._merge(task.end(1), task.end(), "code")
            self._merge(task.end(1), task.end(), "bold")
        elif LIST_ITEM.match(text):
            item = LIST_ITEM.match(text)
            self._merge(len(item.group(1)), item.end(), "marker")

        for pattern, marker, kind in INLINE:
            for match in pattern.finditer(text):
                self._merge(match.start(), match.end(), kind)
                self._merge(match.start(), match.start() + marker, "marker")
                self._merge(match.end() - marker, match.end(), "marker")

    def _merge(self, start: int, end: int, kind: str) -> None:
        """Add a style over a range, keeping what the range already has."""
        extra = self._format(kind)
        for position in range(start, end):
            text_format = self.format(position)
            text_format.merge(extra)
            self.setFormat(position, 1, text_format)


def checkbox_at(editor: QPlainTextEdit, position) -> tuple[QTextCursor, int] | None:
    """The task checkbox under a point of the editor's viewport: its block's cursor and
    the offset of the character between the brackets."""
    cursor = editor.cursorForPosition(position)
    block = cursor.block()
    task = TASK.match(block.text())
    if task is None:
        return None
    # The brackets and what they hold, plus a character on each side for an easy click.
    start, end = task.end(1) - 1, task.end() + 1
    if not start <= cursor.positionInBlock() <= end:
        return None
    # cursorForPosition picks the nearest character: the point must also be on the line.
    rect = editor.cursorRect(cursor)
    if not rect.top() - 2 <= position.y() <= rect.bottom() + 2:
        return None
    return QTextCursor(block), task.end(1) + 1


def toggle_checkbox(block_cursor: QTextCursor, offset: int) -> None:
    """Check or uncheck a task, as one step that undo can take back."""
    block = block_cursor.block()
    checked = block.text()[offset] in "xX"
    cursor = QTextCursor(block)
    cursor.setPosition(block.position() + offset)
    cursor.setPosition(block.position() + offset + 1, QTextCursor.KeepAnchor)
    cursor.insertText(" " if checked else "x")


def continued_item(line: str) -> str | None:
    """What Enter at the end of a list item starts the next line with: the same bullet,
    the next number, an unchecked box. "" for an empty item, which ends the list."""
    item = LIST_ITEM.match(line)
    if item is None:
        return None
    if not line[item.end():].strip():
        return ""
    indent, bullet, number, delimiter, space, box = item.groups()
    marker = bullet or f"{int(number) + 1}{delimiter}"
    return f"{indent}{marker}{space}{'[ ] ' if box else ''}"


def align_table(lines: list[str]) -> list[str]:
    """The rows of a table with their cells padded to the width of each column."""
    rows = [_cells(line) for line in lines]
    separators = [TABLE_SEPARATOR.match(line) is not None for line in lines]
    columns = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (columns - len(row)))
    widths = [max([3] + [len(row[column]) for row, separator in zip(rows, separators)
                         if not separator]) for column in range(columns)]
    indent = re.match(r"\s*", lines[0]).group()
    aligned = []
    for row, separator in zip(rows, separators):
        if separator:
            cells = [_separator_cell(cell, width) for cell, width in zip(row, widths)]
        else:
            cells = [cell.ljust(width) for cell, width in zip(row, widths)]
        aligned.append(f"{indent}| {' | '.join(cells)} |")
    return aligned


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def _separator_cell(cell: str, width: int) -> str:
    left, right = cell.startswith(":"), cell.endswith(":")
    return f"{':' if left else '-'}{'-' * (width - 2)}{':' if right else '-'}"


def is_table_line(text: str) -> bool:
    return bool(TABLE_ROW.match(text) or (TABLE_SEPARATOR.match(text) and "|" in text))


class MarkdownEditing(QObject):
    """What typing and clicking do in Markdown: tasks toggle on a click, Enter continues
    a list, and a table is aligned once the cursor leaves it."""

    def __init__(self, editor: QPlainTextEdit):
        super().__init__(editor)
        self.editor = editor
        self.enabled = False
        self.table_block = None  # the first line of the table the cursor is in
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)
        editor.viewport().setMouseTracking(True)
        editor.cursorPositionChanged.connect(self._on_cursor_moved)

    def eventFilter(self, watched, event) -> bool:
        # The viewport still sends events while the editor is being destroyed.
        if not self.enabled or not shiboken6.isValid(self.editor) or self.editor.isReadOnly():
            return False
        if watched is self.editor.viewport():
            if event.type() == QEvent.MouseMove:
                over = checkbox_at(self.editor, event.position().toPoint()) is not None
                self.editor.viewport().setCursor(Qt.PointingHandCursor if over else Qt.IBeamCursor)
            # A double click is two clicks, so it toggles twice.
            elif event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) \
                    and event.button() == Qt.LeftButton:
                checkbox = checkbox_at(self.editor, event.position().toPoint())
                if checkbox is not None and not event.modifiers():
                    toggle_checkbox(*checkbox)
                    return True
        elif event.type() == QEvent.KeyPress and self._continue_list(event):
            return True
        return False

    def _continue_list(self, event: QKeyEvent) -> bool:
        if event.key() not in (Qt.Key_Return, Qt.Key_Enter) or event.modifiers() & ~Qt.KeypadModifier:
            return False
        cursor = self.editor.textCursor()
        if cursor.hasSelection() or not cursor.atBlockEnd():
            return False
        prefix = continued_item(cursor.block().text())
        if prefix is None:
            return False
        cursor.beginEditBlock()
        if prefix == "":  # Enter on an empty item ends the list
            cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
        else:
            cursor.insertText("\n" + prefix)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        return True

    def _on_cursor_moved(self) -> None:
        start = _table_start(self.editor.textCursor().block()) if self.enabled else None
        # Updated before aligning, which moves the cursor again.
        left, self.table_block = self.table_block, start
        if left is not None and left != start:
            self._align(left)

    def _align(self, first) -> None:
        if not first.isValid() or not is_table_line(first.text()):
            return
        blocks = []
        block = first
        while block.isValid() and is_table_line(block.text()):
            blocks.append(block)
            block = block.next()
        lines = [block.text() for block in blocks]
        aligned = align_table(lines)
        if aligned == lines:
            return
        # The editor's own cursor, below the table, follows the edit by itself.
        cursor = QTextCursor(first)
        cursor.beginEditBlock()
        cursor.setPosition(blocks[-1].position() + len(blocks[-1].text()), QTextCursor.KeepAnchor)
        cursor.insertText("\n".join(aligned))
        cursor.endEditBlock()


def _table_start(block):
    """The first line of the table a line belongs to, None outside tables."""
    if not is_table_line(block.text()):
        return None
    while block.previous().isValid() and is_table_line(block.previous().text()):
        block = block.previous()
    return block
