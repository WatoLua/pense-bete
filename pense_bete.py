#!/usr/bin/env python3
"""Pense-bête: sticky notes, one window per note, versioned in a local git repository.

Each note is stored as a JSON file in the data directory, which is a git
repository. A note is saved (and committed) 10 seconds after its last
modification, and immediately when its window is closed.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DATA_DIR = Path(
    os.environ.get("PENSE_BETE_DIR")
    or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pense-bete"
)
ICON_PATH = Path(__file__).resolve().parent / "icon.svg"
AUTOSAVE_DELAY_MS = 10_000
DEFAULT_COLOR = "#fff59d"
PALETTE = {
    "Jaune": "#fff59d",
    "Orange": "#ffcc80",
    "Rose": "#f8bbd0",
    "Violet": "#d1c4e9",
    "Bleu": "#b3e5fc",
    "Vert": "#c5e1a5",
    "Gris": "#e0e0e0",
}
UNTITLED = "(sans titre)"


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on the given background."""
    color = QColor(background)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def color_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class GitRepo:
    """Thin wrapper around the git CLI for the notes directory."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        if not (path / ".git").exists():
            self._run("init", "--quiet")
        # Commits must never fail for lack of an identity on this machine.
        if not self._run("config", "user.email", check=False).stdout.strip():
            self._run("config", "user.name", "Pense-bête")
            self._run("config", "user.email", "pense-bete@localhost")

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=check
        )

    def commit_file(self, filename: str, message: str) -> None:
        """Stage one file (added, modified or removed) and commit it if it changed."""
        self._run("add", "--all", "--", filename)
        if self._run("diff", "--cached", "--quiet", "--", filename, check=False).returncode:
            self._run("commit", "--quiet", "-m", message, "--", filename)


class Note:
    def __init__(self, note_id: str, title: str = "", color: str = DEFAULT_COLOR,
                 content: str = "", created: str | None = None):
        self.id = note_id
        self.title = title
        self.color = color
        self.content = content
        self.created = created or datetime.now().isoformat(timespec="seconds")

    @property
    def filename(self) -> str:
        return f"{self.id}.json"

    @property
    def display_title(self) -> str:
        return self.title.strip() or UNTITLED

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "color": self.color,
                "content": self.content, "created": self.created}

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(data["id"], data.get("title", ""), data.get("color", DEFAULT_COLOR),
                   data.get("content", ""), data.get("created"))


class NoteStore:
    def __init__(self, path: Path):
        self.path = path
        self.git = GitRepo(path)

    def load_all(self) -> list[Note]:
        notes = []
        for file in self.path.glob("*.json"):
            try:
                notes.append(Note.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError) as error:
                print(f"Ignoring unreadable note {file.name}: {error}", file=sys.stderr)
        return sorted(notes, key=lambda note: note.created)

    def save(self, note: Note, message: str) -> None:
        target = self.path / note.filename
        # Written to a temporary file then renamed, so a crash never leaves a truncated note.
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(note.to_dict(), ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
        self.git.commit_file(note.filename, message)

    def delete(self, note: Note) -> None:
        (self.path / note.filename).unlink(missing_ok=True)
        self.git.commit_file(note.filename, f'Delete "{note.display_title}"')


class NoteWindow(QWidget):
    """Editor window for a single note."""

    changed = Signal(object)  # title or color changed, the list must be refreshed

    def __init__(self, note: Note, store: NoteStore):
        super().__init__()
        self.note = note
        self.store = store
        self.dirty = False
        self.discarded = False

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(AUTOSAVE_DELAY_MS)
        self.timer.timeout.connect(self.save)

        self.title_edit = QLineEdit(note.title)
        self.title_edit.setPlaceholderText("Titre")
        self.title_edit.textChanged.connect(self._on_title_changed)

        self.color_button = QToolButton()
        self.color_button.setText("Couleur")
        self.color_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.color_button)
        for name, color in PALETTE.items():
            action = QAction(color_icon(color), name, menu)
            action.triggered.connect(lambda _=False, c=color: self.set_color(c))
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction("Autre…", self._choose_custom_color)
        self.color_button.setMenu(menu)

        self.content_edit = QPlainTextEdit(note.content)
        self.content_edit.setPlaceholderText("Écrire ici…")
        self.content_edit.textChanged.connect(self._mark_dirty)

        header = QHBoxLayout()
        header.addWidget(self.title_edit)
        header.addWidget(self.color_button)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.content_edit)

        self.resize(320, 300)
        self._apply_color()
        self._update_window_title()

    def _on_title_changed(self, text: str) -> None:
        self.note.title = text
        self._update_window_title()
        self._mark_dirty()
        self.changed.emit(self.note)

    def _choose_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.note.color), self, "Couleur du post-it")
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, color: str) -> None:
        if color == self.note.color:
            return
        self.note.color = color
        self._apply_color()
        self._mark_dirty()
        self.changed.emit(self.note)

    def _apply_color(self) -> None:
        foreground = text_color_for(self.note.color)
        self.setStyleSheet(
            f"NoteWindow, QPlainTextEdit, QLineEdit {{ background: {self.note.color};"
            f" color: {foreground}; }}"
            " QLineEdit { font-weight: bold; border: none; font-size: 14px; }"
            " QPlainTextEdit { border: none; font-size: 13px; }"
        )

    def _update_window_title(self) -> None:
        self.setWindowTitle(f"{self.note.display_title} — Pense-bête")

    def _mark_dirty(self) -> None:
        self.dirty = True
        self.timer.start()  # restarting it delays the save until 10 s of inactivity

    def save(self) -> None:
        self.timer.stop()
        if not self.dirty or self.discarded:
            return
        self.note.content = self.content_edit.toPlainText()
        try:
            self.store.save(self.note, f'Update "{self.note.display_title}"')
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, "Pense-bête", f"Échec de la sauvegarde :\n{error}")
            return
        self.dirty = False

    def discard(self) -> None:
        """Close without saving, for a note that is being deleted."""
        self.discarded = True
        self.timer.stop()
        self.close()

    def closeEvent(self, event) -> None:
        self.save()
        super().closeEvent(event)


class MainWindow(QWidget):
    def __init__(self, store: NoteStore):
        super().__init__()
        self.store = store
        self.notes: list[Note] = store.load_all()
        self.windows: dict[str, NoteWindow] = {}

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda item: self.open_note(item.data(Qt.UserRole)))

        new_button = QPushButton("Nouveau")
        new_button.clicked.connect(self.create_note)
        delete_button = QPushButton("Supprimer")
        delete_button.clicked.connect(self.delete_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(new_button)
        buttons.addWidget(delete_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(buttons)

        self.setWindowTitle("Pense-bête")
        self.resize(300, 420)
        self.refresh_list()

    def _note_by_id(self, note_id: str) -> Note | None:
        return next((note for note in self.notes if note.id == note_id), None)

    def refresh_list(self) -> None:
        selected = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        for note in self.notes:
            item = QListWidgetItem(note.display_title)
            item.setData(Qt.UserRole, note.id)
            item.setBackground(QColor(note.color))
            item.setForeground(QColor(text_color_for(note.color)))
            self.list.addItem(item)
            if note.id == selected:
                self.list.setCurrentItem(item)

    def create_note(self) -> None:
        note = Note(uuid.uuid4().hex)
        try:
            self.store.save(note, "Create note")
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, "Pense-bête", f"Impossible de créer le post-it :\n{error}")
            return
        self.notes.append(note)
        self.refresh_list()
        self.list.setCurrentRow(self.list.count() - 1)
        self.open_note(note.id)
        self.windows[note.id].title_edit.setFocus()

    def open_note(self, note_id: str) -> None:
        window = self.windows.get(note_id)
        if window is None:
            note = self._note_by_id(note_id)
            if note is None:
                return
            window = NoteWindow(note, self.store)
            window.changed.connect(lambda _note: self.refresh_list())
            window.destroyed.connect(lambda _=None, i=note_id: self.windows.pop(i, None))
            window.setAttribute(Qt.WA_DeleteOnClose)
            self.windows[note_id] = window
        window.show()
        window.raise_()
        window.activateWindow()

    def delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        note = self._note_by_id(item.data(Qt.UserRole))
        answer = QMessageBox.question(
            self, "Supprimer", f"Supprimer le post-it « {note.display_title} » ?"
        )
        if answer != QMessageBox.Yes:
            return
        window = self.windows.pop(note.id, None)
        if window is not None:
            window.discard()
        try:
            self.store.delete(note)
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, "Pense-bête", f"Échec de la suppression :\n{error}")
        self.notes.remove(note)
        self.refresh_list()

    def closeEvent(self, event) -> None:
        # Closing the list quits the application; open notes are saved on the way out.
        for window in list(self.windows.values()):
            window.close()
        super().closeEvent(event)
        QApplication.quit()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Pense-bête")
    # Matches pense-bete.desktop, so the desktop shell groups the windows under its entry.
    app.setDesktopFileName("pense-bete")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(NoteStore(DATA_DIR))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
