"""The window of one note, and its history panel."""

import subprocess
from datetime import datetime

from PySide6.QtCore import (
    QByteArray, QEvent, QPoint, QPointF, QRect, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import (
    APP_NAME, AUTOSAVE_DELAY_MS, DEFAULT_FONT_SIZE, MAX_FONT_SIZE, MIN_FONT_SIZE, PALETTE,
)
from .diff import differences, utf16_ranges
from .i18n import tr
from .markdown import MarkdownEditing, MarkdownHighlighter
from .storage import Note, NoteStore, Version
from .style import color_icon, note_palette, pin_icon, pixel_font, text_color_for


TASKS_TEMPLATE = "- [ ] "
TITLE_FONT_SIZE = 14

# Translucent, so that they read on any note color.
REMOVED_COLOR = QColor(229, 57, 53, 90)
ADDED_COLOR = QColor(67, 160, 71, 90)


def highlights(editor: QPlainTextEdit, text: str, ranges: list[tuple[int, int]],
               color: QColor) -> list[QTextEdit.ExtraSelection]:
    """Colored backgrounds over the given ranges of the editor's text, which stays as is."""
    selections = []
    for start, length in utf16_ranges(text, ranges):
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(color)
        selection.cursor = QTextCursor(editor.document())
        selection.cursor.setPosition(start)
        selection.cursor.setPosition(start + length, QTextCursor.KeepAnchor)
        selections.append(selection)
    return selections


def resized(start: QRect, edges: Qt.Edge, dx: int, dy: int, minimum: QSize) -> QRect:
    """A window's geometry once the given edges have moved by (dx, dy), the others staying
    put, and never below the minimum size. With no edges, the whole window moves."""
    if not edges:
        return start.translated(dx, dy)
    left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()
    if edges & Qt.LeftEdge:
        left = min(left + dx, right + 1 - minimum.width())
    if edges & Qt.RightEdge:
        right = max(right + dx, left - 1 + minimum.width())
    if edges & Qt.TopEdge:
        top = min(top + dy, bottom + 1 - minimum.height())
    if edges & Qt.BottomEdge:
        bottom = max(bottom + dy, top - 1 + minimum.height())
    return QRect(QPoint(left, top), QPoint(right, bottom))


class HistoryPanel(QFrame):
    """Read-only view of a note's previous versions, browsed from a dated list or arrows."""

    restore_requested = Signal(object)  # Version
    copy_requested = Signal(object)  # Version
    close_requested = Signal()
    shown = Signal()  # another version, or none, is on display

    def __init__(self):
        super().__init__()
        self.versions: list[Version] = []
        self.font_size = DEFAULT_FONT_SIZE

        self.older_button = QToolButton()
        self.older_button.setText("◀")
        self.older_button.setToolTip(tr("history_older"))
        self.older_button.clicked.connect(lambda: self.select(self.combo.currentIndex() + 1))
        self.newer_button = QToolButton()
        self.newer_button.setText("▶")
        self.newer_button.setToolTip(tr("history_newer"))
        self.newer_button.clicked.connect(lambda: self.select(self.combo.currentIndex() - 1))
        self.combo = QComboBox()
        # Long titles must not widen the panel at the expense of the note beside it.
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self.combo.currentIndexChanged.connect(self._show)
        self.position = QLabel()

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setAutoFillBackground(True)
        self.title.setMargin(2)
        self.title.setFont(pixel_font(self.title.font(), TITLE_FONT_SIZE, bold=True))
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setFrameShape(QFrame.NoFrame)
        self.markdown = False
        self.highlighter = MarkdownHighlighter(self.content.document(), self.font_size,
                                               "#000000")

        self.restore_button = QPushButton(tr("history_restore"))
        self.restore_button.setToolTip(tr("history_restore_tip"))
        self.restore_button.clicked.connect(lambda: self.restore_requested.emit(self.current()))
        self.copy_button = QPushButton(tr("history_copy"))
        self.copy_button.setToolTip(tr("history_copy_tip"))
        self.copy_button.clicked.connect(lambda: self.copy_requested.emit(self.current()))
        close_button = QToolButton()
        close_button.setText("✕")
        close_button.setToolTip(tr("history_close"))
        close_button.clicked.connect(self.close_requested)

        navigation = QHBoxLayout()
        navigation.addWidget(self.older_button)
        navigation.addWidget(self.combo, 1)
        navigation.addWidget(self.newer_button)
        navigation.addWidget(self.position)
        navigation.addWidget(close_button)
        actions = QHBoxLayout()
        actions.addWidget(self.restore_button)
        actions.addWidget(self.copy_button)
        actions.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.addLayout(navigation)
        layout.addWidget(self.title)
        layout.addWidget(self.content, 1)
        layout.addLayout(actions)

    def set_versions(self, versions: list[Version]) -> None:
        """Fill the list, keeping the selected version when it is still there."""
        selected = self.current().commit if self.current() else None
        self.versions = versions
        self.combo.blockSignals(True)
        self.combo.clear()
        for index, version in enumerate(versions):
            title = version.title.strip() or tr("untitled")
            label = f"{version.date} — {title}"
            if index == 0:
                label += f" ({tr('history_current')})"
            self.combo.addItem(color_icon(version.color), label)
        self.combo.blockSignals(False)
        commits = [version.commit for version in versions]
        # Opening on the version before the current one: that is what history is looked for.
        self.select(commits.index(selected) if selected in commits else min(1, len(versions) - 1))

    def current(self) -> Version | None:
        index = self.combo.currentIndex()
        return self.versions[index] if 0 <= index < len(self.versions) else None

    def select(self, index: int) -> None:
        if 0 <= index < len(self.versions):
            self.combo.setCurrentIndex(index)
        self._show()

    def _show(self) -> None:
        version = self.current()
        index = self.combo.currentIndex()
        self.older_button.setEnabled(version is not None and index < len(self.versions) - 1)
        self.newer_button.setEnabled(version is not None and index > 0)
        self.restore_button.setEnabled(version is not None and index > 0)
        self.copy_button.setEnabled(version is not None)
        if version is None:
            self.position.clear()
            self.title.setText(tr("history_empty"))
            self.content.clear()
            self.shown.emit()
            return
        self.position.setText(f"{len(self.versions) - index} / {len(self.versions)}")
        self.title.setText(version.title.strip() or tr("untitled"))
        self.content.setPlainText(version.content)
        foreground = text_color_for(version.color)
        self.highlighter.configure(self.markdown, self.font_size, foreground)
        # The version on its own paper; the panel's buttons stay on the note's.
        for widget in (self.title, self.content):
            widget.setPalette(note_palette(version.color))
        self.content.setFont(pixel_font(self.content.font(), self.font_size))
        self.shown.emit()


class NoteWindow(QWidget):
    """Editor window for a single note."""

    changed = Signal(object)  # what the list shows changed: title, color or last edit
    font_size_changed = Signal(object)  # the text was zoomed in or out
    closing = Signal(object)  # the window is closing, after its note was saved
    copy_requested = Signal(object)  # Version to copy into a new note
    on_top_changed = Signal(object)  # the "keep on top" button was toggled
    shortcuts_requested = Signal()  # F1: the list of keyboard shortcuts

    def __init__(self, note: Note, store: NoteStore):
        super().__init__()
        self.note = note
        self.store = store
        self.dirty = False
        self.discarded = False
        self.geometry_before_history: QByteArray | None = None
        # How the history panel found and left the window, to give its width back on closing.
        self.width_before_history = self.width_with_history = 0
        self.splitter_moved = False

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(AUTOSAVE_DELAY_MS)
        self.timer.timeout.connect(self.save)

        self.title_edit = QLineEdit(note.title)
        self.title_edit.setFrame(False)
        self.title_edit.setFont(pixel_font(self.title_edit.font(), TITLE_FONT_SIZE, bold=True))
        self.title_edit.setPlaceholderText(tr("title_placeholder"))
        self.title_edit.textChanged.connect(self._on_title_changed)

        self.color_button = QToolButton()
        self.color_button.setText(tr("color"))
        self.color_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.color_button)
        for name, color in PALETTE.items():
            action = QAction(color_icon(color), tr(name), menu)
            action.triggered.connect(lambda _=False, c=color: self.set_color(c))
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(tr("other_color"), self._choose_custom_color)
        self.color_button.setMenu(menu)

        self.content_edit = QPlainTextEdit(note.content)
        self.content_edit.setFrameShape(QFrame.NoFrame)
        self.markdown = False
        self.highlighter = MarkdownHighlighter(self.content_edit.document(), DEFAULT_FONT_SIZE,
                                               text_color_for(note.color))
        self.markdown_editing = MarkdownEditing(self.content_edit)
        self.content_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.content_edit.customContextMenuRequested.connect(self._show_context_menu)
        self.content_edit.setPlaceholderText(tr("content_placeholder"))
        # textChanged also fires when the Markdown highlighting repaints the text: only a
        # text that differs from the last one seen is an edit.
        self.last_text = note.content
        self.content_edit.textChanged.connect(self._on_text_changed)

        self.on_top_button = QToolButton()
        self.on_top_button.setCheckable(True)
        self.on_top_button.setIcon(pin_icon())
        self.on_top_button.setIconSize(QSize(22, 22))
        self.on_top_button.setToolTip(tr("on_top"))
        self.on_top_button.toggled.connect(self._on_top_toggled)

        self.history_button = QToolButton()
        self.history_button.setText(tr("history"))
        self.history_button.setCheckable(True)
        self.history_button.toggled.connect(self._set_history_open)

        self.history = HistoryPanel()
        self.history.hide()
        self.history.shown.connect(self._highlight_differences)
        self.history.restore_requested.connect(self.restore_version)
        # Typing moves the differences; they follow once it pauses.
        self.differences_timer = QTimer(self)
        self.differences_timer.setSingleShot(True)
        self.differences_timer.setInterval(200)
        self.differences_timer.timeout.connect(self._highlight_differences)
        self.history.copy_requested.connect(self.copy_requested)
        self.history.close_requested.connect(lambda: self.history_button.setChecked(False))
        for keys, step in (("Alt+Left", 1), ("Alt+Right", -1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(
                lambda step=step: self.history.isVisible()
                and self.history.select(self.history.combo.currentIndex() + step))

        header = QHBoxLayout()
        header.addWidget(self.title_edit)
        header.addWidget(self.history_button)
        header.addWidget(self.color_button)
        header.addWidget(self.on_top_button)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addLayout(header)
        editor_layout.addWidget(self.content_edit)
        # Past on the left, present on the right.
        self.splitter = QSplitter()
        self.splitter.addWidget(self.history)
        self.splitter.addWidget(editor)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.splitterMoved.connect(lambda *_: setattr(self, "splitter_moved", True))
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)

        # Zooming, as in a browser: Ctrl with the wheel, +, - or 0 to go back to the default.
        self.content_edit.viewport().installEventFilter(self)
        self.history.content.viewport().installEventFilter(self)
        for keys, step in ((QKeySequence.ZoomIn, 1), ("Ctrl+=", 1), (QKeySequence.ZoomOut, -1)):
            QShortcut(QKeySequence(keys), self, lambda step=step: self.zoom(step))
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self.set_font_size(DEFAULT_FONT_SIZE))
        QShortcut(QKeySequence.Save, self, lambda: self.save())
        QShortcut(QKeySequence("F1"), self, self.shortcuts_requested)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)
        QShortcut(QKeySequence("Ctrl+L"), self, self.insert_tasks)
        QShortcut(QKeySequence("Ctrl+T"), self, self.insert_table)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.copy_all)
        # Ctrl+Delete is a key of the editor itself, which deletes the next word: it is
        # taken before the editor sees it.
        self.content_edit.installEventFilter(self)

        # Alt with a mouse button moves or resizes the window from anywhere in it: every
        # widget of the window passes its mouse events through here first.
        self.resize_origin: tuple[QPointF, QRect, Qt.Edge] | None = None
        self.eat_context_menu = False
        for widget in (self, *self.findChildren(QWidget)):
            widget.installEventFilter(self)

        self.font_size = DEFAULT_FONT_SIZE
        self.resize(320, 300)
        self._apply_color()
        self._update_window_title()

    def _on_title_changed(self, text: str) -> None:
        self.note.title = text
        self._update_window_title()
        self._mark_dirty()
        self.changed.emit(self.note)

    def _choose_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.note.color), self, tr("note_color"))
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, color: str) -> None:
        if color == self.note.color:
            return
        self.note.color = color
        self._apply_color()
        self._mark_dirty()
        self.changed.emit(self.note)

    def set_markdown(self, enabled: bool) -> None:
        """Show the text's Markdown formatted, or as plain text; the text is the same."""
        self.markdown = self.history.markdown = self.markdown_editing.enabled = enabled
        self._apply_color()
        if self.history.isVisible():
            self.history.select(self.history.combo.currentIndex())

    def _show_context_menu(self, position) -> None:
        editing = self.markdown_editing
        clicked = self.content_edit.cursorForPosition(position)
        # The table actions work at the text cursor: it goes where the click was, unless
        # a selection is being kept for copying.
        if self.markdown and not self.content_edit.textCursor().hasSelection() \
                and editing.table(clicked) is not None:
            self.content_edit.setTextCursor(clicked)
        menu = self.content_edit.createStandardContextMenu()
        # Undo and redo as the keys do them, an alignment with the edit it followed.
        for action in menu.actions():
            if action.objectName() in ("edit-undo", "edit-redo"):
                action.triggered.disconnect()
                action.triggered.connect(editing.undo if action.objectName() == "edit-undo"
                                         else editing.redo)
                if action.objectName() == "edit-redo":
                    action.setShortcut(QKeySequence("Ctrl+Y"))
        if self.markdown and editing.table() is not None:
            menu.addSeparator()
            for label, shortcut, action, enabled in (
                    ("table_insert_row", "Ctrl+Return", editing.insert_row, True),
                    ("table_insert_column", "Ctrl+Shift+Return", editing.insert_column, True),
                    ("table_delete_row", "Ctrl+Backspace", editing.delete_row,
                     editing.can_delete_row()),
                    ("table_delete_column", "Ctrl+Shift+Backspace", editing.delete_column,
                     editing.can_delete_column())):
                item = menu.addAction(tr(label), action)
                item.setEnabled(enabled)
                # Shown in the menu; the editor handles the keys itself.
                item.setShortcut(QKeySequence(shortcut))
        menu.addSeparator()
        for label, shortcut, action in (
                ("insert_tasks", "Ctrl+L", self.insert_tasks),
                ("insert_table", "Ctrl+T", self.insert_table),
                ("copy_all", "Ctrl+Shift+C", self.copy_all),
                ("clear_all", "Ctrl+Del", self.clear_all)):
            item = menu.addAction(tr(label), action)
            item.setShortcut(QKeySequence(shortcut))  # shown only: the window handles the keys
        menu.exec(self.content_edit.viewport().mapToGlobal(position))
        menu.deleteLater()

    def insert_tasks(self) -> None:
        self._insert_block(TASKS_TEMPLATE)

    def insert_table(self) -> None:
        self._insert_block(tr("table_template"))
        # Ready to type the first column's name. By lines of text, not of screen, which a
        # narrow window wraps.
        cursor = self.content_edit.textCursor()
        cursor.movePosition(QTextCursor.PreviousBlock, n=2)
        header = cursor.block()
        name = header.text().split("|")[1].strip()
        start = header.position() + header.text().index(name)
        cursor.setPosition(start)
        cursor.setPosition(start + len(name), QTextCursor.KeepAnchor)
        self.content_edit.setTextCursor(cursor)

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.content_edit.toPlainText())

    def clear_all(self) -> None:
        """Empty the note, as one edit that undo takes back; the history keeps it too."""
        cursor = self.content_edit.textCursor()
        cursor.select(QTextCursor.Document)
        cursor.removeSelectedText()
        self.content_edit.setFocus()

    def _insert_block(self, text: str) -> None:
        """Insert lines of Markdown on lines of their own, at the cursor."""
        cursor = self.content_edit.textCursor()
        cursor.beginEditBlock()
        if cursor.block().text().strip():
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertText("\n")
        cursor.insertText(text)
        cursor.endEditBlock()
        self.content_edit.setTextCursor(cursor)
        self.content_edit.setFocus()

    def _apply_color(self) -> None:
        foreground = text_color_for(self.note.color)
        self.highlighter.configure(self.markdown, self.font_size, foreground)
        # A palette rather than a style sheet: a style sheet stops a palette from reaching
        # the widgets inside, which then keep the system theme's colors, white text of a
        # dark theme on the note's yellow.
        self.setPalette(note_palette(self.note.color))
        self.content_edit.setFont(pixel_font(self.content_edit.font(), self.font_size))

    def eventFilter(self, watched, event) -> bool:
        if self._move_or_resize(event):
            return True
        if watched is self.content_edit and event.type() == QEvent.KeyPress:
            modifiers = event.modifiers() & ~Qt.KeypadModifier
            if event.key() == Qt.Key_Delete and modifiers == Qt.ControlModifier:
                self.clear_all()
                return True
            # Ctrl+Y redoes as well as Ctrl+Shift+Z, the usual key on Linux.
            if event.matches(QKeySequence.Undo):
                self.markdown_editing.undo()
                return True
            if event.matches(QKeySequence.Redo) \
                    or (event.key() == Qt.Key_Y and modifiers == Qt.ControlModifier):
                self.markdown_editing.redo()
                return True
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y():
                self.zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(watched, event)

    def _move_or_resize(self, event) -> bool:
        """Alt and the left button move the window, as its title bar does; Alt and the
        right button resize it from the corner nearest to where it was pressed, the
        opposite corner staying put, so that moving the mouse away grows it."""
        kind = event.type()
        if kind == QEvent.ContextMenu and self.eat_context_menu:
            self.eat_context_menu = False  # the press was the start of a resize
            return True
        if kind == QEvent.MouseButtonPress and event.modifiers() & Qt.AltModifier:
            if event.button() == Qt.LeftButton:
                handle = self.windowHandle()
                # The window manager moves the window, snapping to the edges included.
                if handle is None or not handle.startSystemMove():
                    self.resize_origin = (event.globalPosition(), self.geometry(), Qt.Edge(0))
                return True
            if event.button() == Qt.RightButton:
                local = self.mapFromGlobal(event.globalPosition().toPoint())
                edges = (Qt.LeftEdge if local.x() < self.width() / 2 else Qt.RightEdge) \
                    | (Qt.TopEdge if local.y() < self.height() / 2 else Qt.BottomEdge)
                self.resize_origin = (event.globalPosition(), self.geometry(), edges)
                self.eat_context_menu = True
                return True
        if self.resize_origin is None:
            return False
        if kind == QEvent.MouseMove:
            origin, start, edges = self.resize_origin
            delta = (event.globalPosition() - origin).toPoint()
            self.setGeometry(resized(start, edges, delta.x(), delta.y(),
                                     self.minimumSizeHint().expandedTo(self.minimumSize())))
            return True
        if kind == QEvent.MouseButtonRelease:
            self.resize_origin = None
            return True
        return False

    def zoom(self, step: int) -> None:
        self.set_font_size(self.font_size + step)

    def set_font_size(self, size: int) -> None:
        """The size of the text, in pixels, for this note and its history."""
        size = max(MIN_FONT_SIZE, min(size, MAX_FONT_SIZE))
        if size == self.font_size:
            return
        self.font_size = self.history.font_size = size
        self._apply_color()
        if self.history.isVisible():
            self.history.select(self.history.combo.currentIndex())
        self.font_size_changed.emit(self)

    def _update_window_title(self) -> None:
        self.setWindowTitle(self.note.display_title)

    def _on_text_changed(self) -> None:
        text = self.content_edit.toPlainText()
        if text == self.last_text:
            return
        self.last_text = text
        self._mark_dirty()
        if self.history.isVisible():
            self.differences_timer.start()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self.timer.start()  # restarting it delays the save until 10 s of inactivity

    def save(self, message: str | None = None) -> None:
        self.timer.stop()
        if not self.dirty or self.discarded:
            return
        self.note.content = self.content_edit.toPlainText()
        self.note.modified = datetime.now().isoformat(timespec="seconds")
        try:
            self.store.save(self.note, message or f'Update "{self.note.display_title}"')
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("save_failed", error=error))
            return
        self.dirty = False
        self.changed.emit(self.note)
        if self.history.isVisible():
            self._load_history()

    @property
    def history_open(self) -> bool:
        return self.geometry_before_history is not None

    def session_geometry(self) -> QByteArray:
        """The geometry to restore next time: the history panel's widening is not kept."""
        return self.geometry_before_history or self.saveGeometry()

    def _set_history_open(self, opened: bool) -> None:
        if opened == self.history_open:
            return
        if opened:
            self.save()  # so that the current text is the newest version listed
            self.geometry_before_history = self.saveGeometry()
            self.history.show()
            self._load_history()
            self.width_before_history = self.width()
            if not self.isMaximized():
                self.resize(max(self.width() * 2, 640), self.height())
            self.splitter.setSizes([self.width() // 2, self.width() // 2])
            self.width_with_history = self.width()
            self.splitter_moved = False
        else:
            if self.width() == self.width_with_history and not self.splitter_moved:
                width = self.width_before_history  # left as the history opened it
            else:  # the note keeps the width it was given beside the history
                width = self.splitter.sizes()[1] + self.width() - sum(self.splitter.sizes())
            self.history.hide()
            self.differences_timer.stop()
            self.content_edit.setExtraSelections([])
            self.geometry_before_history = None
            if not self.isMaximized():
                # The window's minimum width counts the panel until the layout is redone.
                self.splitter.updateGeometry()
                self.layout().activate()
                self.resize(width, self.height())

    def set_on_top(self, on_top: bool) -> None:
        self.on_top_button.blockSignals(True)
        self.on_top_button.setChecked(on_top)
        self.on_top_button.blockSignals(False)
        if on_top == bool(self.windowFlags() & Qt.WindowStaysOnTopHint):
            return
        # Changing the flags recreates the native window, which then needs showing again
        # where it was.
        visible, geometry = self.isVisible(), self.saveGeometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on_top)
        if visible:
            self.restoreGeometry(geometry)
            self.show()

    def _on_top_toggled(self, on_top: bool) -> None:
        self.set_on_top(on_top)
        self.on_top_changed.emit(self)

    def _highlight_differences(self) -> None:
        """Mark, over the text, what the note lost since the version shown (in the
        history, in red) and what it gained (in the note, in green)."""
        version = self.history.current()
        current = self.content_edit.toPlainText()
        removed, added = differences(version.content, current) if version else ([], [])
        self.history.content.setExtraSelections(
            highlights(self.history.content, version.content if version else "", removed,
                       REMOVED_COLOR))
        self.content_edit.setExtraSelections(
            highlights(self.content_edit, current, added, ADDED_COLOR))

    def _load_history(self) -> None:
        try:
            self.history.set_versions(self.store.history(self.note))
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("history_failed", error=error))

    def restore_version(self, version: Version) -> None:
        """Overwrite the note with a previous version; the overwritten text stays in history."""
        self.title_edit.setText(version.title)
        self.set_color(version.color)
        self.content_edit.setPlainText(version.content)
        self.dirty = True
        self.save(f'Restore "{self.note.display_title}" from {version.commit[:7]}')

    def discard(self) -> None:
        """Close without saving, for a note that is being deleted."""
        self.discarded = True
        self.timer.stop()
        self.close()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # While the history is open, a resize from the application itself, the layout
        # making room for the panel included, is not the user's: the width to give back
        # on closing stays the one from before the history.
        if self.history_open and not event.spontaneous():
            self.width_with_history = self.width()

    def closeEvent(self, event) -> None:
        self.save()
        self.closing.emit(self)
        super().closeEvent(event)
