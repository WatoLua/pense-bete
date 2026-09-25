#!/usr/bin/env python3
"""Pense-bête: sticky notes, one window per note, versioned in a local git repository.

Each note is stored as a JSON file in the data directory, which is a git
repository. A note is saved (and committed) 10 seconds after its last
modification, and immediately when its window is closed.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QDateTime, QLibraryInfo, QLocale, QProcess, Qt, QTimer, QTranslator, Signal,
)
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
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
# Each note lives in its own directory and git repository: <DATA_DIR>/<note id>/note.json.
NOTE_FILE = "note.json"
DEFAULT_RETENTION_DAYS = 30
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
    "confirm_delete": {
        "en": "Delete the note “{title}”?\nIt stays {days} days among the deleted notes.",
        "fr": "Supprimer le post-it « {title} » ?\nIl reste {days} jours dans les post-its supprimés."},
    "deleted_notes": {"en": "Deleted notes…", "fr": "Post-its supprimés…"},
    "trash_title": {"en": "Deleted notes", "fr": "Post-its supprimés"},
    "trash_empty": {"en": "No deleted notes.", "fr": "Aucun post-it supprimé."},
    "trash_item": {"en": "{title} — deleted {date}, erased in {days} d",
                   "fr": "{title} — supprimé le {date}, effacé dans {days} j"},
    "retention_before": {"en": "Erase deleted notes after", "fr": "Effacer les post-its supprimés après"},
    "retention_after": {"en": "days", "fr": "jours"},
    "restore": {"en": "Restore", "fr": "Restaurer"},
    "erase": {"en": "Erase permanently", "fr": "Supprimer définitivement"},
    "confirm_erase": {"en": "Erase the note “{title}” permanently?",
                      "fr": "Supprimer définitivement le post-it « {title} » ?"},
    "close": {"en": "Close", "fr": "Fermer"},
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
    "history": {"en": "History", "fr": "Historique"},
    "history_older": {"en": "Older version (Alt+Left)", "fr": "Version précédente (Alt+←)"},
    "history_newer": {"en": "Newer version (Alt+Right)", "fr": "Version suivante (Alt+→)"},
    "history_current": {"en": "current version", "fr": "version actuelle"},
    "history_restore": {"en": "Restore", "fr": "Restaurer"},
    "history_restore_tip": {"en": "Replace the current note with this version",
                            "fr": "Remplacer le post-it actuel par cette version"},
    "history_copy": {"en": "New note", "fr": "Nouveau post-it"},
    "history_copy_tip": {"en": "Create a new note with this version",
                         "fr": "Créer un nouveau post-it avec cette version"},
    "history_close": {"en": "Close history", "fr": "Quitter l'historique"},
    "history_empty": {"en": "No history for this note.", "fr": "Aucun historique pour ce post-it."},
    "history_failed": {"en": "Could not read the history:\n{error}",
                       "fr": "Impossible de lire l'historique :\n{error}"},
    "quit": {"en": "Quit", "fr": "Quitter"},
    "update": {"en": "Update", "fr": "Mettre à jour"},
    "auto_update": {"en": "Update automatically at launch",
                    "fr": "Mettre à jour automatiquement au démarrage"},
    "auto_updated": {"en": "{app} was updated; the new version runs from the next launch.",
                     "fr": "{app} a été mis à jour : la nouvelle version s'appliquera au prochain démarrage."},
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
    "confirm_uninstall": {"en": "Uninstall {app}?", "fr": "Désinstaller {app} ?"},
    "uninstall_purge": {
        "en": "Also delete the notes and settings (cannot be undone)",
        "fr": "Supprimer aussi les post-its et les réglages (irréversible)"},
    "uninstall_failed": {"en": "The uninstallation failed:\n{error}",
                         "fr": "La désinstallation a échoué :\n{error}"},
    "uninstalled": {"en": "{app} is uninstalled. Your notes are kept in {path}.",
                    "fr": "{app} est désinstallé. Vos post-its sont conservés dans {path}."},
    "uninstalled_purged": {"en": "{app} is uninstalled, with its notes and settings.",
                           "fr": "{app} est désinstallé, avec ses post-its et ses réglages."},
}


def tr(key: str, **values) -> str:
    return TRANSLATIONS[key][LANGUAGE].format(app=APP_NAME, **values)


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on the given background."""
    color = QColor(background)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def run(*args: str) -> subprocess.CompletedProcess:
    """Run a command, its output captured for error messages."""
    return subprocess.run(args, capture_output=True, text=True, timeout=300)


def run_command(*args: str) -> subprocess.CompletedProcess:
    """Run a command with a busy cursor, from the interface thread only."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return run(*args)
    finally:
        QApplication.restoreOverrideCursor()


def command_error(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"


def can_update() -> bool:
    # A clone is the user's own checkout: overwriting its files would clobber their work.
    return not (APP_DIR / ".git").exists()


def update_available(runner=run) -> bool:
    """Whether the repository's HEAD differs from the installed commit."""
    remote = runner("git", "ls-remote", REPO_URL, "HEAD")
    if remote.returncode:
        raise RuntimeError(command_error(remote))
    latest = remote.stdout.split()[0] if remote.stdout.split() else ""
    installed = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
    return bool(latest) and latest != installed


def install_latest(runner=run) -> None:
    """Install the repository's HEAD over this installation; notes are not touched."""
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "pense-bete"
        result = runner("git", "clone", "--quiet", "--depth", "1", "--", REPO_URL, str(source))
        if result.returncode == 0:
            result = runner("bash", str(source / "install.sh"), "--yes", str(APP_DIR))
    if result.returncode:
        raise RuntimeError(command_error(result))


def color_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class GitRepo:
    """Thin wrapper around the git CLI for one repository."""

    def __init__(self, path: Path):
        self.path = path
        if not (path / ".git").exists():
            path.mkdir(parents=True, exist_ok=True)
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
        """Stage one file and commit it if it changed."""
        self._run("add", "--all", "--", filename)
        if self._run("diff", "--cached", "--quiet", "--", filename, check=False).returncode:
            self._run("commit", "--quiet", "-m", message, "--", filename)

    def file_versions(self, filename: str) -> list[tuple[str, int, str]]:
        """(commit, timestamp, content) of each commit that changed the file, newest first."""
        log = self._run("log", "--format=%H %at", "--", filename).stdout.split()
        commits = list(zip(log[0::2], map(int, log[1::2])))
        if not commits:
            return []
        # All contents in one git process, which keeps long histories fast to open.
        requests = "".join(f"{commit}:{filename}\n" for commit, _ in commits).encode()
        output = subprocess.run(["git", "cat-file", "--batch"], cwd=self.path, input=requests,
                                capture_output=True, check=True).stdout
        versions, position = [], 0
        for commit, timestamp in commits:
            end = output.index(b"\n", position)
            header = output[position:end].split()
            position = end + 1
            if header[-1] == b"missing":  # the commit that deleted the file
                continue
            size = int(header[2])
            versions.append((commit, timestamp, output[position:position + size].decode()))
            position += size + 1
        return versions


@dataclass
class Version:
    """A note as saved by one commit."""

    commit: str
    timestamp: int
    title: str
    color: str
    content: str

    @property
    def date(self) -> str:
        # With seconds: saves come 10 seconds apart, so a minute often holds several.
        moment = QDateTime.fromSecsSinceEpoch(self.timestamp)
        return (f"{QLocale().toString(moment.date(), QLocale.FormatType.ShortFormat)}"
                f" {moment.toString('HH:mm:ss')}")


class Note:
    def __init__(self, note_id: str, title: str = "", color: str = DEFAULT_COLOR,
                 content: str = "", created: str | None = None, deleted: str | None = None):
        self.id = note_id
        self.title = title
        self.color = color
        self.content = content
        self.created = created or datetime.now().isoformat(timespec="seconds")
        # When the note was deleted: it stays in the trash, restorable, until it expires.
        self.deleted = deleted

    def days_in_trash(self) -> int:
        return (datetime.now() - datetime.fromisoformat(self.deleted)).days if self.deleted else 0

    @property
    def display_title(self) -> str:
        return self.title.strip() or tr("untitled")

    def to_dict(self) -> dict:
        data = {"id": self.id, "title": self.title, "color": self.color,
                "content": self.content, "created": self.created}
        if self.deleted:
            data["deleted"] = self.deleted
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(data["id"], data.get("title", ""), data.get("color", DEFAULT_COLOR),
                   data.get("content", ""), data.get("created"), data.get("deleted"))


class NoteStore:
    """The notes, one directory and git repository each, so every note has its own history."""

    def __init__(self, path: Path):
        self.path = path
        self.repos: dict[str, GitRepo] = {}
        path.mkdir(parents=True, exist_ok=True)

    def _repo(self, note: Note) -> GitRepo:
        repo = self.repos.get(note.id)
        if repo is None:
            repo = self.repos[note.id] = GitRepo(self.path / note.id)
        return repo

    def load_all(self) -> list[Note]:
        notes = []
        for file in self.path.glob(f"*/{NOTE_FILE}"):
            try:
                notes.append(Note.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError) as error:
                print(f"Ignoring unreadable note {file.parent.name}: {error}", file=sys.stderr)
        return sorted(notes, key=lambda note: note.created)

    def save(self, note: Note, message: str) -> None:
        repo = self._repo(note)
        target = repo.path / NOTE_FILE
        # Written to a temporary file then renamed, so a crash never leaves a truncated note.
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(note.to_dict(), ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
        repo.commit_file(NOTE_FILE, message)

    def history(self, note: Note) -> list[Version]:
        versions = []
        for commit, timestamp, text in self._repo(note).file_versions(NOTE_FILE):
            try:
                data = json.loads(text)
            except ValueError:
                continue
            versions.append(Version(commit, timestamp, data.get("title", ""),
                                    data.get("color", DEFAULT_COLOR), data.get("content", "")))
        return versions

    def trash(self, note: Note) -> None:
        """Delete the note, restorably: its file stays, marked with the deletion time."""
        note.deleted = datetime.now().isoformat(timespec="seconds")
        try:
            self.save(note, f'Delete "{note.display_title}"')
        except (OSError, subprocess.CalledProcessError):
            note.deleted = None
            raise

    def untrash(self, note: Note) -> None:
        deleted, note.deleted = note.deleted, None
        try:
            self.save(note, f'Restore "{note.display_title}" from the deleted notes')
        except (OSError, subprocess.CalledProcessError):
            note.deleted = deleted
            raise

    def erase(self, note: Note) -> None:
        """Remove the note for good, with its repository and so its whole history."""
        self.repos.pop(note.id, None)
        shutil.rmtree(self.path / note.id)


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


class HistoryPanel(QFrame):
    """Read-only view of a note's previous versions, browsed from a dated list or arrows."""

    restore_requested = Signal(object)  # Version
    copy_requested = Signal(object)  # Version
    close_requested = Signal()

    def __init__(self):
        super().__init__()
        self.versions: list[Version] = []

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
        self.title.setObjectName("historyTitle")
        self.title.setWordWrap(True)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)

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
            return
        self.position.setText(f"{len(self.versions) - index} / {len(self.versions)}")
        self.title.setText(version.title.strip() or tr("untitled"))
        self.content.setPlainText(version.content)
        foreground = text_color_for(version.color)
        self.setStyleSheet(
            f"QPlainTextEdit, QLabel#historyTitle {{ background: {version.color};"
            f" color: {foreground}; border: none; font-size: 13px; }}"
            " QLabel#historyTitle { font-weight: bold; font-size: 14px; padding: 2px; }"
        )


class NoteWindow(QWidget):
    """Editor window for a single note."""

    changed = Signal(object)  # title or color changed, the list must be refreshed
    closing = Signal(object)  # the window is closing, after its note was saved
    copy_requested = Signal(object)  # Version to copy into a new note

    def __init__(self, note: Note, store: NoteStore):
        super().__init__()
        self.note = note
        self.store = store
        self.dirty = False
        self.discarded = False
        self.geometry_before_history: QByteArray | None = None

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

        self.history_button = QToolButton()
        self.history_button.setText(tr("history"))
        self.history_button.setCheckable(True)
        self.history_button.toggled.connect(self._set_history_open)

        self.history = HistoryPanel()
        self.history.hide()
        self.history.restore_requested.connect(self.restore_version)
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
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)

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

    def save(self, message: str | None = None) -> None:
        self.timer.stop()
        if not self.dirty or self.discarded:
            return
        self.note.content = self.content_edit.toPlainText()
        try:
            self.store.save(self.note, message or f'Update "{self.note.display_title}"')
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("save_failed", error=error))
            return
        self.dirty = False
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
            if not self.isMaximized():
                self.resize(max(self.width() * 2, 640), self.height())
            self.splitter.setSizes([self.width() // 2, self.width() // 2])
        else:
            width = self.splitter.sizes()[1] + self.width() - sum(self.splitter.sizes())
            self.history.hide()
            self.geometry_before_history = None
            if not self.isMaximized():
                self.resize(width, self.height())

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

    def closeEvent(self, event) -> None:
        self.save()
        self.closing.emit(self)
        super().closeEvent(event)


class TrashDialog(QDialog):
    """The deleted notes, to restore or erase, and how long they are kept."""

    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("trash_title"))
        self.resize(460, 360)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _item: self.restore_selected())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())

        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(main.retention_days())
        # Only recorded: erasing waits for the next check, so that typing a number
        # never erases notes on the way through a smaller one.
        self.days.valueChanged.connect(self._set_retention)
        retention = QHBoxLayout()
        retention.addWidget(QLabel(tr("retention_before")))
        retention.addWidget(self.days)
        retention.addWidget(QLabel(tr("retention_after")))
        retention.addStretch()

        self.restore_button = QPushButton(tr("restore"))
        self.restore_button.clicked.connect(self.restore_selected)
        self.erase_button = QPushButton(tr("erase"))
        self.erase_button.clicked.connect(self.erase_selected)
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.erase_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(retention)
        layout.addLayout(buttons)
        self.refresh()

    def _set_retention(self, days: int) -> None:
        self.main.session.set("retention_days", days)
        self.main.session.write()
        self.refresh()

    def refresh(self) -> None:
        selected = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        notes = sorted(self.main.deleted_notes(), key=lambda note: note.deleted, reverse=True)
        for note in notes:
            date = QLocale().toString(QDateTime.fromString(note.deleted, Qt.ISODate).date(),
                                      QLocale.FormatType.ShortFormat)
            days = max(self.days.value() - note.days_in_trash(), 0)
            item = QListWidgetItem(tr("trash_item", title=note.display_title, date=date, days=days))
            item.setData(Qt.UserRole, note.id)
            item.setBackground(QColor(note.color))
            item.setForeground(QColor(text_color_for(note.color)))
            item.setToolTip(note.content[:500])
            self.list.addItem(item)
            if note.id == selected:
                self.list.setCurrentItem(item)
        if not notes:
            item = QListWidgetItem(tr("trash_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
        elif self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _selected(self) -> Note | None:
        item = self.list.currentItem()
        note_id = item.data(Qt.UserRole) if item else None
        return next((n for n in self.main.deleted_notes() if n.id == note_id), None)

    def _update_buttons(self) -> None:
        enabled = self._selected() is not None
        self.restore_button.setEnabled(enabled)
        self.erase_button.setEnabled(enabled)

    def restore_selected(self) -> None:
        note = self._selected()
        if note is not None:
            self.main.restore_note(note)
            self.refresh()

    def erase_selected(self) -> None:
        note = self._selected()
        if note is None:
            return
        if QMessageBox.question(self, tr("erase"), tr("confirm_erase", title=note.display_title)
                                ) != QMessageBox.Yes:
            return
        self.main.erase_note(note)
        self.refresh()


class MainWindow(QWidget):
    auto_updated = Signal()  # emitted from the update thread, handled in the interface one

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
        new_button.clicked.connect(lambda: self.create_note())
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
        options_menu.addAction(tr("deleted_notes"), self.open_trash)
        options_menu.addSeparator()
        options_menu.addAction(tr("update"), self.update_app)
        self.auto_update_action = options_menu.addAction(tr("auto_update"))
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(session.get("auto_update", False))
        self.auto_update_action.setEnabled(can_update())
        self.auto_update_action.toggled.connect(self._set_auto_update)
        self.auto_updated.connect(self._on_auto_updated)
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
        """A note that is not deleted."""
        return next((note for note in self.notes if note.id == note_id and not note.deleted), None)

    def deleted_notes(self) -> list[Note]:
        return [note for note in self.notes if note.deleted]

    def retention_days(self) -> int:
        return self.session.get("retention_days", DEFAULT_RETENTION_DAYS)

    def refresh_list(self) -> None:
        selected = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        for note in self.notes:
            if note.deleted:
                continue
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

    def _set_auto_update(self, enabled: bool) -> None:
        # Only recorded: the check runs at the next launch.
        self.session.set("auto_update", enabled)
        self.session.write()

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
            self.session.set_geometry(note_id, window.session_geometry())
        self.session.write()

    def restore_session(self) -> None:
        """Reopen the windows that were open when the application last quit."""
        self.erase_expired()
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

    def create_note(self, version: Version | None = None) -> None:
        """Create a note, empty or with the contents of a previous version of another."""
        note = Note(uuid.uuid4().hex)
        if version is not None:
            note.title, note.color, note.content = version.title, version.color, version.content
        try:
            self.store.save(note, "Create note" if version is None
                            else f"Create note from {version.commit[:7]}")
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
            window.copy_requested.connect(self.create_note)
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
        self.session.set_geometry(window.note.id, window.session_geometry())
        self.windows.pop(window.note.id, None)
        self.save_session()

    def delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        note = self._note_by_id(item.data(Qt.UserRole))
        answer = QMessageBox.question(self, tr("delete"), tr(
            "confirm_delete", title=note.display_title, days=self.retention_days()))
        if answer != QMessageBox.Yes:
            return
        window = self.windows.get(note.id)
        if window is not None:
            window.save()  # its last edits belong to what a restore brings back
        try:
            self.store.trash(note)
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("delete_failed", error=error))
            return
        if window is not None:
            self.windows.pop(note.id)
            window.discard()
        self.session.forget(note.id)
        self.refresh_list()
        self.save_session()

    def restore_note(self, note: Note) -> None:
        try:
            self.store.untrash(note)
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("save_failed", error=error))
            return
        self.refresh_list()
        self.open_note(note.id)

    def erase_note(self, note: Note) -> None:
        try:
            self.store.erase(note)
        except (OSError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("delete_failed", error=error))
            return
        self.notes.remove(note)

    def erase_expired(self) -> None:
        """Erase the deleted notes kept longer than the retention delay."""
        for note in self.deleted_notes():
            if note.days_in_trash() >= self.retention_days():
                self.erase_note(note)

    def open_trash(self) -> None:
        self.erase_expired()
        TrashDialog(self).exec()

    def save_all(self) -> None:
        for window in self.windows.values():
            window.save()

    def update_app(self) -> None:
        if not can_update():
            QMessageBox.information(self, APP_NAME, tr("update_from_clone", path=APP_DIR))
            return
        try:
            if not update_available(run_command):
                QMessageBox.information(self, APP_NAME, tr("up_to_date"))
                return
            if QMessageBox.question(self, tr("update"), tr("update_available")) != QMessageBox.Yes:
                return
            self.save_all()
            install_latest(run_command)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("update_failed", error=error))
            return
        self._offer_restart()

    def _offer_restart(self) -> None:
        if QMessageBox.question(self, tr("update"), tr("update_done")) == QMessageBox.Yes:
            # Closed first, so the new instance does not hand itself over to this one.
            self.server.close()
            self.quit_app()
            QProcess.startDetached(str(APP_DIR / "pense-bete"), [])

    def auto_update(self) -> None:
        """At launch, when enabled: update in a background thread, keeping the interface
        free; failures such as being offline stay silent until the next launch."""
        if not (self.auto_update_action.isChecked() and can_update()):
            return

        def check_and_install() -> None:
            try:
                if update_available():
                    install_latest()
                    self.auto_updated.emit()
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"Automatic update failed: {error}", file=sys.stderr)

        threading.Thread(target=check_and_install, daemon=True).start()

    def _on_auto_updated(self) -> None:
        # The files are replaced; this process keeps running the version it loaded.
        if self.tray.isVisible() and not self.isVisible():
            self.tray.showMessage(APP_NAME, tr("auto_updated"), QIcon(str(ICON_PATH)))
        else:
            self._offer_restart()

    def uninstall_app(self) -> None:
        box = QMessageBox(QMessageBox.Question, tr("uninstall"), tr("confirm_uninstall"),
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        purge = QCheckBox(tr("uninstall_purge"))
        box.setCheckBox(purge)
        if box.exec() != QMessageBox.Yes:
            return
        purging = purge.isChecked()
        self.save_all()
        try:
            result = run_command("bash", str(APP_DIR / "install.sh"), "--uninstall", "--yes",
                                 *(["--purge"] if purging else []),
                                 *(["--dev"] if DEV_MODE else []))
            if result.returncode:
                raise RuntimeError(command_error(result))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("uninstall_failed", error=error))
            return
        if not purging:
            QMessageBox.information(self, APP_NAME, tr("uninstalled", path=DATA_DIR))
            self.quit_app()
            return
        QMessageBox.information(self, APP_NAME, tr("uninstalled_purged"))
        # Quitting as usual would write the session and the open notes back to disk.
        self.quitting = True
        for window in list(self.windows.values()):
            window.discard()
        self.tray.hide()
        self.close()
        QApplication.quit()

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
    window.auto_update()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
