"""The bar under a note's text that finds, and replaces, words in it."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit,
    QToolButton,
)

from .i18n import tr

# Translucent, so that it reads on any note color; the current match is the selection.
MATCH_COLOR = QColor(255, 152, 0, 110)
MAX_HIGHLIGHTS = 1000  # beyond, counting goes on but the text is not marked


class FindBar(QFrame):
    """Finds the text typed in the note's editor, forward or back, and replaces it once
    or everywhere. Return finds the next match, Shift+Return the previous one, Escape
    closes the bar."""

    highlights_changed = Signal()  # the matches to mark over the text changed

    def __init__(self, editor: QPlainTextEdit):
        super().__init__()
        self.editor = editor
        self.matches: list[tuple[int, int]] = []  # (start, end) in the editor's text

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(tr("find_placeholder"))
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.textChanged.connect(lambda: self._search(from_start_of_selection=True))
        self.find_edit.returnPressed.connect(self.find_next)
        self.count = QLabel()
        self.previous_button = QToolButton()
        self.previous_button.setText("▲")
        self.previous_button.setToolTip(tr("find_previous"))
        self.previous_button.clicked.connect(self.find_previous)
        self.next_button = QToolButton()
        self.next_button.setText("▼")
        self.next_button.setToolTip(tr("find_next"))
        self.next_button.clicked.connect(self.find_next)
        self.case_button = QToolButton()
        self.case_button.setText("Aa")
        self.case_button.setCheckable(True)
        self.case_button.setToolTip(tr("find_case"))
        self.case_button.toggled.connect(lambda: self._search(from_start_of_selection=True))
        close_button = QToolButton()
        close_button.setText("✕")
        close_button.setToolTip(tr("find_close"))
        close_button.clicked.connect(self.close_bar)

        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText(tr("replace_placeholder"))
        self.replace_edit.returnPressed.connect(self.replace)
        self.replace_button = QPushButton(tr("replace"))
        self.replace_button.clicked.connect(self.replace)
        self.replace_all_button = QPushButton(tr("replace_all"))
        self.replace_all_button.clicked.connect(self.replace_all)
        self.replace_widgets = (self.replace_edit, self.replace_button, self.replace_all_button)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.find_edit, 0, 0)
        layout.addWidget(self.count, 0, 1)
        layout.addWidget(self.previous_button, 0, 2)
        layout.addWidget(self.next_button, 0, 3)
        layout.addWidget(self.case_button, 0, 4)
        layout.addWidget(close_button, 0, 5)
        layout.addWidget(self.replace_edit, 1, 0)
        layout.addWidget(self.replace_button, 1, 1, 1, 3)
        layout.addWidget(self.replace_all_button, 1, 4, 1, 2)
        layout.setColumnStretch(0, 1)

        for key, action in (("Esc", self.close_bar), ("Shift+Return", self.find_previous),
                            ("Shift+Enter", self.find_previous)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
        # The matches move as the note is typed in; they follow once the typing pauses.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(200)
        self.refresh_timer.timeout.connect(self._refresh)
        editor.textChanged.connect(self._on_text_changed)
        self.hide()

    def _on_text_changed(self) -> None:
        if self.isVisible():
            self.refresh_timer.start()

    def open(self, replacing: bool) -> None:
        """Show the bar, the text selected in the note to find, if on one line."""
        for widget in self.replace_widgets:
            widget.setVisible(replacing)
        selected = self.editor.textCursor().selectedText()
        if selected and " " not in selected:  # the editor's line separator
            self.find_edit.blockSignals(True)
            self.find_edit.setText(selected)
            self.find_edit.blockSignals(False)
        self.show()
        self._refresh()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.matches = []
        self.highlights_changed.emit()
        self.editor.setFocus()

    def _flags(self) -> QTextDocument.FindFlag:
        return QTextDocument.FindCaseSensitively if self.case_button.isChecked() \
            else QTextDocument.FindFlag(0)

    def _find(self, position: int, backward: bool = False) -> QTextCursor | None:
        """The match after a position, or before it going back, around the end."""
        text = self.find_edit.text()
        if not text:
            return None
        document = self.editor.document()
        flags = self._flags() | (QTextDocument.FindBackward if backward
                                 else QTextDocument.FindFlag(0))
        found = document.find(text, position, flags)
        if found.isNull():
            found = document.find(text, document.characterCount() if backward else 0, flags)
        return None if found.isNull() else found

    def _search(self, from_start_of_selection: bool) -> None:
        """Select the first match from the cursor, the one being typed included."""
        cursor = self.editor.textCursor()
        found = self._find(cursor.selectionStart() if from_start_of_selection
                           else cursor.position())
        if found is not None:
            self.editor.setTextCursor(found)
        self._refresh()

    def find_next(self) -> None:
        found = self._find(self.editor.textCursor().selectionEnd())
        if found is not None:
            self.editor.setTextCursor(found)
        self._refresh()

    def find_previous(self) -> None:
        found = self._find(self.editor.textCursor().selectionStart(), backward=True)
        if found is not None:
            self.editor.setTextCursor(found)
        self._refresh()

    def _is_match(self, cursor: QTextCursor) -> bool:
        selected, text = cursor.selectedText(), self.find_edit.text()
        if self.case_button.isChecked():
            return bool(text) and selected == text
        return bool(text) and selected.casefold() == text.casefold()

    def replace(self) -> None:
        """Replace the match selected, then select the next one."""
        cursor = self.editor.textCursor()
        if self._is_match(cursor):
            cursor.insertText(self.replace_edit.text())
            self.editor.setTextCursor(cursor)
        self.find_next()

    def replace_all(self) -> None:
        """Replace every match, as one step that undo takes back."""
        text = self.find_edit.text()
        if not text:
            return
        document = self.editor.document()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        replaced, position = 0, 0
        while True:
            found = document.find(text, position, self._flags())
            if found.isNull():
                break
            edit.setPosition(found.selectionStart())
            edit.setPosition(found.selectionEnd(), QTextCursor.KeepAnchor)
            edit.insertText(self.replace_edit.text())
            position = edit.position()
            replaced += 1
        edit.endEditBlock()
        self._refresh()
        self.count.setText(tr("replaced", count=replaced))

    def _refresh(self) -> None:
        """Find every match again, and show where the selected one is among them."""
        self.refresh_timer.stop()
        self.matches = []
        text = self.find_edit.text()
        document = self.editor.document()
        if text:
            found = document.find(text, 0, self._flags())
            while not found.isNull():
                self.matches.append((found.selectionStart(), found.selectionEnd()))
                found = document.find(text, found.selectionEnd(), self._flags())
        cursor = self.editor.textCursor()
        current = (cursor.selectionStart(), cursor.selectionEnd())
        if not text:
            self.count.setText("")
        elif not self.matches:
            self.count.setText(tr("find_none"))
        elif current in self.matches:
            self.count.setText(f"{self.matches.index(current) + 1}/{len(self.matches)}")
        else:
            self.count.setText(f"{len(self.matches)}")
        for widget in (self.previous_button, self.next_button, self.replace_button,
                       self.replace_all_button):
            widget.setEnabled(bool(self.matches))
        self.highlights_changed.emit()

    def selections(self) -> list[QTextEdit.ExtraSelection]:
        """The matches, marked over the note's text while the bar is open."""
        selections = []
        for start, end in self.matches[:MAX_HIGHLIGHTS] if self.isVisible() else []:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(MATCH_COLOR)
            selection.cursor = QTextCursor(self.editor.document())
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(end, QTextCursor.KeepAnchor)
            selections.append(selection)
        return selections
