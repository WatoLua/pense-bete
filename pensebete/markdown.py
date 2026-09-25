"""Markdown shown formatted in place: the text stays exactly as typed, only its look changes.

Headings, emphasis, code, task lists and tables are styled over the source, their
markers dimmed rather than hidden, so that nothing is ever rewritten behind the
user's back: the note, its history and its differences stay those of the text typed.
"""

import re

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QKeyEvent, QKeySequence, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit

from . import tables

HEADING = re.compile(r"^(#{1,6})(\s+)(.*)$")
# A task's box: "[ ]" to do, "[v]" ok, "[x]" ko.
TASK = re.compile(r"^(\s*[-*+]\s+)\[([ vVxX])\](?=\s|$)")
LIST_ITEM = re.compile(r"^(\s*)(?:([-*+])|(\d+)([.)]))(\s+)(\[[ vVxX]\]\s+)?")
# What a click on a box turns it into.
NEXT_STATE = {" ": "v", "v": "x", "V": "x", "x": " ", "X": " "}
QUOTE = re.compile(r"^(\s*>+)")
FENCE = re.compile(r"^\s*(```|~~~)")
# How long typing in a table pauses before its columns are aligned.
TABLE_ALIGN_DELAY_MS = 2000
END_OF_CELL = 1 << 30  # an offset past any cell's text
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
        elif kind in ("ok", "ko"):
            # Dark on a light note, light on a dark one, as the text is.
            light_note = self.text_color.lightness() < 128
            colors = {"ok": ("#2e7d32", "#a5d6a7"), "ko": ("#c62828", "#ef9a9a")}[kind]
            text_format.setForeground(QColor(colors[0] if light_note else colors[1]))
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
        if tables.is_table_line(text):
            self.setFormat(0, len(text), self._format("table"))
            for match in re.finditer(r"\||(?<=\|)[\s:-]+(?=\|)" if tables.is_separator(text)
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
            self._merge(task.start(1), task.end(1), "marker")
            # In a fixed font, "[ ]" is as wide as "[x]", and reads as a box.
            self._merge(task.end(1), task.end(), "code")
            self._merge(task.end(1), task.end(), "bold")
            state = task.group(2).lower()
            if state != " ":
                self._merge(task.end(1), task.end(), "ok" if state == "v" else "ko")
            if state == "v":  # what is ok is dealt with: its text, not the space before it
                start = len(text) - len(text[task.end():].lstrip())
                self._merge(start, len(text), "done")
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
    """The task box under a point of the editor's viewport: its block's cursor and
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
    """Turn a task's box to its next state, to do, ok, ko then to do again, as one step
    that undo can take back."""
    block = block_cursor.block()
    cursor = QTextCursor(block)
    cursor.setPosition(block.position() + offset)
    cursor.setPosition(block.position() + offset + 1, QTextCursor.KeepAnchor)
    cursor.insertText(NEXT_STATE[block.text()[offset]])


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


class MarkdownEditing(QObject):
    """What typing and clicking do in Markdown: tasks toggle on a click, Enter continues a
    list, and tables keep their columns aligned and take rows and columns on demand."""

    def __init__(self, editor: QPlainTextEdit):
        super().__init__(editor)
        self.editor = editor
        self.enabled = False
        # The number of the first line of the table the cursor is in, None outside tables.
        self.table_start: int | None = None
        self.replacing = False  # while a table is being rewritten
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)
        editor.viewport().setMouseTracking(True)
        editor.cursorPositionChanged.connect(self._on_cursor_moved)
        # A table being typed in is aligned once the typing pauses.
        self.align_timer = QTimer(self)
        self.align_timer.setSingleShot(True)
        self.align_timer.setInterval(TABLE_ALIGN_DELAY_MS)
        self.align_timer.timeout.connect(self._align_current)
        # The text right after an alignment: undo and redo take the alignment and the
        # edit it followed as one step there.
        self.aligned_text: str | None = None
        self.undone_text: str | None = None

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
        elif event.type() == QEvent.KeyPress:
            if self._toggle_key(event) or self._table_key(event) or self._continue_list(event):
                return True
            if self.table_start is not None and _is_typing(event):
                self.align_timer.start()
        return False

    def _toggle_key(self, event: QKeyEvent) -> bool:
        """Ctrl+Space anywhere on a task's line turns its box to the next state."""
        if event.key() != Qt.Key_Space or event.modifiers() != Qt.ControlModifier:
            return False
        cursor = self.editor.textCursor()
        task = TASK.match(cursor.block().text())
        if task is None:
            return False
        position = cursor.position()
        toggle_checkbox(QTextCursor(cursor.block()), task.end(1) + 1)
        cursor.setPosition(position)  # where it was, rather than past the new letter
        self.editor.setTextCursor(cursor)
        return True

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

    def _table_key(self, event: QKeyEvent) -> bool:
        """Tab and Shift+Tab move between cells, Ctrl+Enter adds a row, Ctrl+Shift+Enter a
        column, Ctrl+Backspace deletes the row, Ctrl+Shift+Backspace the column; elsewhere
        than in a table, these keys do what they usually do."""
        if self.table() is None:
            return False
        key, modifiers = event.key(), event.modifiers() & ~Qt.KeypadModifier
        enter = key in (Qt.Key_Return, Qt.Key_Enter)
        if key == Qt.Key_Backspace and modifiers == Qt.ControlModifier:
            # Taken even where it cannot delete, the header's row: deleting the word
            # before the cursor instead would be a surprise.
            if self.can_delete_row():
                self.delete_row()
            return True
        if key == Qt.Key_Backspace and modifiers == Qt.ControlModifier | Qt.ShiftModifier:
            if self.can_delete_column():
                self.delete_column()
            return True
        if key == Qt.Key_Tab and not modifiers:
            self.move_to_cell(1)
        elif key == Qt.Key_Backtab:
            self.move_to_cell(-1)
        elif enter and modifiers == Qt.ControlModifier:
            self.insert_row()
        elif enter and modifiers == Qt.ControlModifier | Qt.ShiftModifier:
            self.insert_column()
        else:
            return False
        return True

    def table(self, cursor: QTextCursor | None = None):
        """The table at a cursor, the editor's by default: (number of its first line, its
        lines, the row, cell and offset in the cell of the cursor), None outside tables."""
        cursor = cursor or self.editor.textCursor()
        block = cursor.block()
        first = _table_start(block)
        if first is None:
            return None
        lines = _table_lines(first)
        row = block.blockNumber() - first.blockNumber()
        cell, offset = tables.cell_at(block.text(), cursor.positionInBlock())
        return first.blockNumber(), lines, row, max(cell, 0), offset

    def insert_row(self) -> None:
        start, lines, row, cell, offset = self.table()
        new_lines, new_row = tables.insert_row(lines, row)
        self._replace(start, len(lines), new_lines, (new_row, 0, 0))

    def insert_column(self) -> None:
        start, lines, row, cell, offset = self.table()
        self._replace(start, len(lines), tables.insert_column(lines, cell), (row, cell + 1, 0))

    def can_delete_row(self) -> bool:
        table = self.table()
        return table is not None and tables.can_delete_row(table[1], table[2])

    def delete_row(self) -> None:
        start, lines, row, cell, offset = self.table()
        new_lines = tables.delete_row(lines, row)
        self._replace(start, len(lines), new_lines, (min(row, len(new_lines) - 1), cell, 0))

    def can_delete_column(self) -> bool:
        table = self.table()
        return table is not None and tables.can_delete_column(table[1])

    def delete_column(self) -> None:
        start, lines, row, cell, offset = self.table()
        new_lines = tables.delete_column(lines, cell)
        columns = tables.column_count(new_lines)
        self._replace(start, len(lines), new_lines, (row, min(cell, columns - 1), 0))

    def move_to_cell(self, step: int) -> None:
        """To the next cell, or the previous one for a negative step, past the separator;
        from the last cell, to a new row. The cursor lands at the end of the cell's text."""
        start, lines, row, cell, offset = self.table()
        columns = tables.column_count(lines)
        position = row * columns + cell
        while True:
            position += step
            row, cell = divmod(position, columns)
            if position < 0:
                return
            if row >= len(lines):
                new_lines, new_row = tables.insert_row(lines, len(lines) - 1)
                self._replace(start, len(lines), new_lines, (new_row, 0, 0))
                return
            if not tables.is_separator(lines[row]):
                break
        self._replace(start, len(lines), tables.align_table(lines), (row, cell, END_OF_CELL))

    def undo(self) -> None:
        """Undo, taking back an alignment together with the edit it followed: undoing
        the alignment alone would leave the table to be aligned again."""
        document = self.editor.document()
        steps = 2 if self._just_aligned() and document.availableUndoSteps() >= 2 else 1
        for _ in range(steps):
            self.editor.undo()
        self.undone_text = document.toPlainText() if steps == 2 else None

    def redo(self) -> None:
        """Redo, bringing back an edit and the alignment that followed it as one step."""
        document = self.editor.document()
        steps = 2 if self.undone_text == document.toPlainText() \
            and document.availableRedoSteps() >= 2 else 1
        for _ in range(steps):
            self.editor.redo()
        self.undone_text = None
        if steps == 2:
            self.aligned_text = document.toPlainText()

    def _just_aligned(self) -> bool:
        return self.aligned_text is not None and self.aligned_text == self.editor.toPlainText()

    def _align_current(self) -> None:
        """Align the table being typed in, the cursor staying where it is in its cell."""
        table = self.table() if self.enabled else None
        if table is None or self.editor.textCursor().hasSelection():
            return
        start, lines, row, cell, offset = table
        aligned = tables.align_table(lines, keep=(row, cell, offset))
        if aligned != lines:
            self._replace(start, len(lines), aligned, (row, cell, offset), aligning=True)

    def _on_cursor_moved(self) -> None:
        if self.replacing:
            return
        first = _table_start(self.editor.textCursor().block()) if self.enabled else None
        start = first.blockNumber() if first is not None else None
        left, self.table_start = self.table_start, start
        if left is not None and left != start:
            self.align_timer.stop()
            self._align(left)

    def _align(self, number: int) -> None:
        """Align the table that starts at a line, once the cursor has left it."""
        first = _table_start(self.editor.document().findBlockByNumber(number))
        if first is None:
            return
        lines = _table_lines(first)
        aligned = tables.align_table(lines)
        if aligned != lines:
            self._replace(first.blockNumber(), len(lines), aligned, None, aligning=True)

    def _replace(self, start: int, count: int, lines: list[str],
                 target: tuple[int, int, int] | None, aligning: bool = False) -> None:
        """Put new lines in place of a table's, then the cursor at (row, cell, offset).

        Without a target, the editor's cursor, outside the table, follows by itself.
        An alignment is recorded, for undo to take it back with the edit before it.
        """
        document = self.editor.document()
        first, last = document.findBlockByNumber(start), document.findBlockByNumber(start + count - 1)
        cursor = QTextCursor(first)
        self.replacing = True
        try:
            cursor.beginEditBlock()
            cursor.setPosition(last.position() + len(last.text()), QTextCursor.KeepAnchor)
            cursor.insertText("\n".join(lines))
            cursor.endEditBlock()
            if target is not None:
                row, cell, offset = target
                block = document.findBlockByNumber(start + row)
                moved = QTextCursor(block)
                moved.setPosition(block.position() + tables.cell_column(lines[row], cell, offset))
                self.editor.setTextCursor(moved)
        finally:
            self.replacing = False
        self.aligned_text = document.toPlainText() if aligning else None
        self._on_cursor_moved()


def _is_typing(event: QKeyEvent) -> bool:
    """Whether a key changes the text: a character, a deletion, a paste or a cut. Undo and
    redo do not count, since aligning after them would clear what redo can bring back."""
    if event.matches(QKeySequence.Paste) or event.matches(QKeySequence.Cut):
        return True
    if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
        return True
    return bool(event.text()) and event.text().isprintable() \
        and not event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)


def _table_start(block):
    """The first line of the table a line belongs to, None outside tables."""
    if not block.isValid() or not tables.is_table_line(block.text()):
        return None
    while block.previous().isValid() and tables.is_table_line(block.previous().text()):
        block = block.previous()
    return block


def _table_lines(first) -> list[str]:
    lines = []
    block = first
    while block.isValid() and tables.is_table_line(block.text()):
        lines.append(block.text())
        block = block.next()
    return lines
