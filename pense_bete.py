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
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QLibraryInfo, QLocale, QProcess, Qt, QTimer, QTranslator, Signal,
)
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
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
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

APP_DIR = Path(__file__).resolve().parent
# Run from a git clone, the application is the development version: it keeps its own
# notes, menu entry and window class, apart from the installed application.
DEV_MODE = (APP_DIR / ".git").exists()
APP_ID = "pense-bete-dev" if DEV_MODE else "pense-bete"
APP_NAME = "Pense-bête (dev)" if DEV_MODE else "Pense-bête"
DATA_DIR = Path(
    os.environ.get("PENSE_BETE_DIR")
    or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
)
# Window state, kept apart from the notes so that moving a window never creates a commit.
SESSION_FILE = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID / "session.json"
)
RECENT_NOTES = 3
ICON_PATH = APP_DIR / ("icon-dev.svg" if DEV_MODE else "icon.svg")
# Written by install.sh: the installed commit of the repository.
VERSION_FILE = APP_DIR / ".version"
REPO_URL = os.environ.get("PENSE_BETE_REPO", "https://github.com/WatoLua/pense-bete.git")
AUTOSAVE_DELAY_MS = 10_000
DEFAULT_COLOR = "#fff59d"
PALETTE = {
    "yellow": "#fff59d",
    "orange": "#ffcc80",
    "pink": "#f8bbd0",
    "purple": "#d1c4e9",
    "blue": "#b3e5fc",
    "green": "#c5e1a5",
    "grey": "#e0e0e0",
}

# The interface is in French when the system locale is French, in English otherwise.
LANGUAGE = "fr" if QLocale.system().language() == QLocale.French else "en"
TRANSLATIONS = {
    "untitled": {"en": "(untitled)", "fr": "(sans titre)"},
    "title_placeholder": {"en": "Title", "fr": "Titre"},
    "content_placeholder": {"en": "Write here…", "fr": "Écrire ici…"},
    "color": {"en": "Color", "fr": "Couleur"},
    "other_color": {"en": "Other…", "fr": "Autre…"},
    "note_color": {"en": "Note color", "fr": "Couleur du post-it"},
    "yellow": {"en": "Yellow", "fr": "Jaune"},
    "orange": {"en": "Orange", "fr": "Orange"},
    "pink": {"en": "Pink", "fr": "Rose"},
    "purple": {"en": "Purple", "fr": "Violet"},
    "blue": {"en": "Blue", "fr": "Bleu"},
    "green": {"en": "Green", "fr": "Vert"},
    "grey": {"en": "Grey", "fr": "Gris"},
    "new": {"en": "New", "fr": "Nouveau"},
    "delete": {"en": "Delete", "fr": "Supprimer"},
    "confirm_delete": {"en": "Delete the note “{title}”?",
                       "fr": "Supprimer le post-it « {title} » ?"},
    "save_failed": {"en": "Could not save the note:\n{error}",
                    "fr": "Échec de la sauvegarde :\n{error}"},
    "create_failed": {"en": "Could not create the note:\n{error}",
                      "fr": "Impossible de créer le post-it :\n{error}"},
    "delete_failed": {"en": "Could not delete the note:\n{error}",
                      "fr": "Échec de la suppression :\n{error}"},
    "options": {"en": "Options", "fr": "Options"},
    "keep_running": {"en": "Keep running in the background when closed",
                     "fr": "Rester en arrière-plan à la fermeture"},
    "open_main": {"en": "Open {app}", "fr": "Ouvrir {app}"},
    "quit": {"en": "Quit", "fr": "Quitter"},
    "update": {"en": "Update", "fr": "Mettre à jour"},
    "uninstall": {"en": "Uninstall", "fr": "Désinstaller"},
    "update_from_clone": {
        "en": "{app} runs from a git repository ({path}).\nUpdate it with git pull.",
        "fr": "{app} tourne depuis un dépôt git ({path}).\nMettez-le à jour avec git pull."},
    "up_to_date": {"en": "{app} is up to date.", "fr": "{app} est à jour."},
    "update_available": {"en": "A new version is available. Update now?",
                         "fr": "Une nouvelle version est disponible. Mettre à jour maintenant ?"},
    "update_failed": {"en": "The update failed:\n{error}", "fr": "La mise à jour a échoué :\n{error}"},
    "update_done": {"en": "{app} is updated. Restart it now?",
                    "fr": "{app} est mis à jour. Le redémarrer maintenant ?"},
    "confirm_uninstall": {
        "en": "Uninstall {app}?\nYour notes are kept in {path}.",
        "fr": "Désinstaller {app} ?\nVos post-its sont conservés dans {path}."},
    "uninstall_failed": {"en": "The uninstallation failed:\n{error}",
                         "fr": "La désinstallation a échoué :\n{error}"},
    "uninstalled": {"en": "{app} is uninstalled. Your notes are kept in {path}.",
                    "fr": "{app} est désinstallé. Vos post-its sont conservés dans {path}."},
}


def tr(key: str, **values) -> str:
    return TRANSLATIONS[key][LANGUAGE].format(app=APP_NAME, **values)


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on the given background."""
    color = QColor(background)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def run_command(*args: str) -> subprocess.CompletedProcess:
    """Run a command with a busy cursor; its output is captured for error messages."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=300)
    finally:
        QApplication.restoreOverrideCursor()


def command_error(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"


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
        return self.title.strip() or tr("untitled")

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


class Session:
    """What is open across runs: windows and their geometry, recent notes, options.

    Keys: "background" (bool), "main_open" (bool), "open_notes" and "recent" (note
    ids, most recent first for "recent"), "geometries" (window key -> base64).
    """

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def geometry(self, key: str) -> QByteArray | None:
        value = self.data.get("geometries", {}).get(key)
        return QByteArray.fromBase64(value.encode()) if value else None

    def set_geometry(self, key: str, geometry: QByteArray) -> None:
        self.data.setdefault("geometries", {})[key] = bytes(geometry.toBase64()).decode()

    def forget(self, note_id: str) -> None:
        self.data.get("geometries", {}).pop(note_id, None)
        for key in ("open_notes", "recent"):
            self.data[key] = [i for i in self.data.get(key, []) if i != note_id]

    def write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
            print(f"Could not save the session: {error}", file=sys.stderr)


class NoteWindow(QWidget):
    """Editor window for a single note."""

    changed = Signal(object)  # title or color changed, the list must be refreshed
    closing = Signal(object)  # the window is closing, after its note was saved

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
        self.content_edit.setPlaceholderText(tr("content_placeholder"))
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

    def _apply_color(self) -> None:
        foreground = text_color_for(self.note.color)
        self.setStyleSheet(
            f"NoteWindow, QPlainTextEdit, QLineEdit {{ background: {self.note.color};"
            f" color: {foreground}; }}"
            " QLineEdit { font-weight: bold; border: none; font-size: 14px; }"
            " QPlainTextEdit { border: none; font-size: 13px; }"
        )

    def _update_window_title(self) -> None:
        self.setWindowTitle(self.note.display_title)

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
            QMessageBox.warning(self, APP_NAME, tr("save_failed", error=error))
            return
        self.dirty = False

    def discard(self) -> None:
        """Close without saving, for a note that is being deleted."""
        self.discarded = True
        self.timer.stop()
        self.close()

    def closeEvent(self, event) -> None:
        self.save()
        self.closing.emit(self)
        super().closeEvent(event)


class MainWindow(QWidget):
    def __init__(self, store: NoteStore, session: Session, server: QLocalServer):
        super().__init__()
        self.store = store
        self.session = session
        self.server = server
        self.notes: list[Note] = store.load_all()
        self.windows: dict[str, NoteWindow] = {}
        self.quitting = False
        server.newConnection.connect(self._on_other_instance)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda item: self.open_note(item.data(Qt.UserRole)))

        new_button = QPushButton(tr("new"))
        new_button.clicked.connect(self.create_note)
        delete_button = QPushButton(tr("delete"))
        delete_button.clicked.connect(self.delete_selected)

        options_button = QToolButton()
        options_button.setText("⋮")
        options_button.setToolTip(tr("options"))
        options_button.setPopupMode(QToolButton.InstantPopup)
        options_button.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        options_button.setFixedSize(new_button.sizeHint().height(), new_button.sizeHint().height())
        options_menu = QMenu(options_button)
        self.background_action = options_menu.addAction(tr("keep_running"))
        self.background_action.setCheckable(True)
        self.background_action.setChecked(session.get("background", False))
        self.background_action.toggled.connect(self._set_background)
        options_menu.addSeparator()
        options_menu.addAction(tr("update"), self.update_app)
        options_menu.addAction(tr("uninstall"), self.uninstall_app)
        options_menu.addSeparator()
        options_menu.addAction(tr("quit"), self.quit_app)
        options_button.setMenu(options_menu)

        # The tray icon's menu reopens this window or one of the recent notes.
        self.tray_menu = QMenu(self)
        self.tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), self)
        self.tray.setToolTip(APP_NAME)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(self.background_action.isChecked())

        buttons = QHBoxLayout()
        buttons.addWidget(new_button)
        buttons.addWidget(delete_button)
        buttons.addWidget(options_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(buttons)

        self.setWindowTitle(APP_NAME)
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
        self.refresh_tray_menu()

    def refresh_tray_menu(self) -> None:
        self.tray_menu.clear()
        self.tray_menu.addAction(tr("open_main"), self.show_main)
        recent = [note for note in map(self._note_by_id, self.session.get("recent", [])) if note]
        if recent:
            self.tray_menu.addSeparator()
        for note in recent[:RECENT_NOTES]:
            self.tray_menu.addAction(color_icon(note.color), note.display_title,
                                     lambda i=note.id: self.open_note(i))
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(tr("quit"), self.quit_app)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A click usually opens the menu; activating the icon itself shows this window.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_main()

    def _on_other_instance(self) -> None:
        """Another launch of the application asks this one to show itself."""
        connection = self.server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        self.show_main()

    def _set_background(self, enabled: bool) -> None:
        self.session.set("background", enabled)
        self.tray.setVisible(enabled)
        self.save_session()

    def save_session(self) -> None:
        """Record the open windows and their geometry."""
        if self.quitting:
            return
        self.session.set("main_open", self.isVisible())
        self.session.set_geometry("main", self.saveGeometry())
        self.session.set("open_notes", list(self.windows))
        for note_id, window in self.windows.items():
            self.session.set_geometry(note_id, window.saveGeometry())
        self.session.write()

    def restore_session(self) -> None:
        """Reopen the windows that were open when the application last quit."""
        geometry = self.session.geometry("main")
        if geometry is not None:
            self.restoreGeometry(geometry)
        open_notes = [i for i in self.session.get("open_notes", []) if self._note_by_id(i)]
        # Nothing on screen after a launch would look like a failure, so the list shows then.
        if self.session.get("main_open", True) or not open_notes:
            self.show_main()
        for note_id in open_notes:
            self.open_note(note_id, recent=False)
        self.save_session()

    def show_main(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.save_session()

    def create_note(self) -> None:
        note = Note(uuid.uuid4().hex)
        try:
            self.store.save(note, "Create note")
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("create_failed", error=error))
            return
        self.notes.append(note)
        self.refresh_list()
        self.list.setCurrentRow(self.list.count() - 1)
        self.open_note(note.id)
        self.windows[note.id].title_edit.setFocus()

    def open_note(self, note_id: str, recent: bool = True) -> None:
        """Show a note's window; recent=False when restoring, which keeps the recent order."""
        window = self.windows.get(note_id)
        if window is None:
            note = self._note_by_id(note_id)
            if note is None:
                return
            window = NoteWindow(note, self.store)
            window.changed.connect(lambda _note: self.refresh_list())
            window.closing.connect(self._on_note_closing)
            window.setAttribute(Qt.WA_DeleteOnClose)
            geometry = self.session.geometry(note_id)
            if geometry is not None:
                window.restoreGeometry(geometry)
            self.windows[note_id] = window
        window.show()
        window.raise_()
        window.activateWindow()
        if recent:
            others = [i for i in self.session.get("recent", []) if i != note_id]
            self.session.set("recent", [note_id, *others][:RECENT_NOTES])
            self.refresh_tray_menu()
        self.save_session()

    def _on_note_closing(self, window: NoteWindow) -> None:
        if self.quitting:
            return  # the session was recorded before the windows started closing
        self.session.set_geometry(window.note.id, window.saveGeometry())
        self.windows.pop(window.note.id, None)
        self.save_session()

    def delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        note = self._note_by_id(item.data(Qt.UserRole))
        answer = QMessageBox.question(
            self, tr("delete"), tr("confirm_delete", title=note.display_title)
        )
        if answer != QMessageBox.Yes:
            return
        window = self.windows.pop(note.id, None)
        if window is not None:
            window.discard()
        try:
            self.store.delete(note)
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("delete_failed", error=error))
        self.notes.remove(note)
        self.session.forget(note.id)
        self.refresh_list()
        self.save_session()

    def save_all(self) -> None:
        for window in self.windows.values():
            window.save()

    def update_app(self) -> None:
        # A clone is the user's own checkout: overwriting its files would clobber their work.
        if (APP_DIR / ".git").exists():
            QMessageBox.information(self, APP_NAME, tr("update_from_clone", path=APP_DIR))
            return
        try:
            remote = run_command("git", "ls-remote", REPO_URL, "HEAD")
            if remote.returncode:
                raise RuntimeError(command_error(remote))
            latest = remote.stdout.split()[0] if remote.stdout.split() else ""
            installed = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
            if latest and latest == installed:
                QMessageBox.information(self, APP_NAME, tr("up_to_date"))
                return
            if QMessageBox.question(self, tr("update"), tr("update_available")) != QMessageBox.Yes:
                return
            self.save_all()
            with tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / "pense-bete"
                result = run_command("git", "clone", "--quiet", "--depth", "1", "--",
                                     REPO_URL, str(source))
                if result.returncode == 0:
                    result = run_command("bash", str(source / "install.sh"), "--yes", str(APP_DIR))
            if result.returncode:
                raise RuntimeError(command_error(result))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("update_failed", error=error))
            return
        if QMessageBox.question(self, tr("update"), tr("update_done")) == QMessageBox.Yes:
            # Closed first, so the new instance does not hand itself over to this one.
            self.server.close()
            self.quit_app()
            QProcess.startDetached(str(APP_DIR / "pense-bete"), [])

    def uninstall_app(self) -> None:
        if QMessageBox.question(
            self, tr("uninstall"), tr("confirm_uninstall", path=DATA_DIR)
        ) != QMessageBox.Yes:
            return
        self.save_all()
        try:
            result = run_command("bash", str(APP_DIR / "install.sh"), "--uninstall", "--yes",
                                 *(["--dev"] if DEV_MODE else []))
            if result.returncode:
                raise RuntimeError(command_error(result))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("uninstall_failed", error=error))
            return
        QMessageBox.information(self, APP_NAME, tr("uninstalled", path=DATA_DIR))
        self.quit_app()

    def quit_app(self) -> None:
        """Record the session, then close every window, saving the notes, and quit."""
        if self.quitting:
            return
        self.save_session()
        self.quitting = True
        for window in list(self.windows.values()):
            window.close()
        self.tray.hide()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if self.quitting:
            return
        if self.background_action.isChecked():
            # Only the list goes away: the notes stay open and the application keeps running.
            self.hide()
            self.save_session()
        else:
            self.quit_app()


def main() -> None:
    # X11, through XWayland in a Wayland session, lets windows be put back where they
    # were: Wayland leaves window positions to the compositor. Qt's xcb plugin needs
    # libxcb-cursor0; without it, Qt falls back to Wayland. A platform set by the user
    # still wins.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb;wayland")
    # In the Wayland fallback, Qt draws the title bar itself. Its default decoration
    # centers the title over the whole bar, where the buttons cover it on narrow note
    # windows; bradient aligns it left.
    os.environ.setdefault("QT_WAYLAND_DECORATION", "bradient")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Matches the desktop entry install.sh writes, so the desktop shell groups the
    # windows under that entry.
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    # Qt's own strings (dialog buttons, color picker) follow the same language.
    qt_translator = QTranslator(app)
    if qt_translator.load(QLocale(LANGUAGE), "qtbase", "_",
                          QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_translator)
    app.setQuitOnLastWindowClosed(False)

    # One instance per user: a second launch asks the running one to show its window.
    server_name = f"{APP_ID}-{os.getuid()}"
    other = QLocalSocket()
    other.connectToServer(server_name)
    if other.waitForConnected(1000):
        other.disconnectFromServer()
        return
    QLocalServer.removeServer(server_name)  # left behind by an instance that crashed
    server = QLocalServer()
    server.listen(server_name)

    window = MainWindow(NoteStore(DATA_DIR), Session(SESSION_FILE), server)
    window.restore_session()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
