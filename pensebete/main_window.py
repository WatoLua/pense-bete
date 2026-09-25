"""The list of notes, which opens their windows and holds the application's menus."""

import os
import subprocess
import sys
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .about import AboutDialog, ShortcutsDialog
from .archive import ArchiveError, export_notes, import_notes
from .config import (
    APP_DIR, APP_ID, APP_NAME, DATA_DIR, DEFAULT_FONT_SIZE, DEFAULT_RETENTION_DAYS, DEV_MODE, FROZEN,
    ICON_PATH,
    RECENT_NOTES,
)
from .i18n import tr
from .note_window import NoteWindow
from .session import Session
from .shortcuts import Binding, first_key, settings
from .storage import Note, NoteStore, Version
from .style import color_icon, text_color_for
from .trash import TrashDialog
from .updates import (
    Release, can_update, command_error, git_available, hand_over, install_release, installer,
    release_notes, run_command, stage_update, update_available,
)


# The orders of the list, as arguments to sorted().
SORT_ORDERS = {
    "created": {"key": lambda note: note.created},
    "modified": {"key": lambda note: note.last_edited, "reverse": True},
    "title": {"key": lambda note: (searchable(note.display_title), note.created)},
}


def searchable(text: str) -> str:
    """The text folded for searching: case and accents do not count, "é" matches "e"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class MainWindow(QWidget):
    # (release, notes): emitted from the update thread, handled in the interface one.
    auto_updated = Signal(str, str)

    def __init__(self, store: NoteStore, session: Session, server: QLocalServer):
        super().__init__()
        self.store = store
        self.session = session
        settings.attach(session)
        self.server = server
        self.notes: list[Note] = store.load_all()
        self.windows: dict[str, NoteWindow] = {}
        self.quitting = False
        # A standalone build downloaded for an update: (its directory, the release).
        self.staged_update: tuple[Path, Release] | None = None
        server.newConnection.connect(self._on_other_instance)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh_list())
        Binding(self, "search", self._focus_search)
        Binding(self, "close_list", self.close)
        Binding(self, "shortcuts", self.show_shortcuts)
        Binding(self.search, "clear_search", self.search.clear, Qt.WidgetShortcut)
        self.search.installEventFilter(self)

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
        self.markdown_action = options_menu.addAction(tr("markdown"))
        self.markdown_action.setCheckable(True)
        self.markdown_action.setChecked(session.get("markdown", False))
        self.markdown_action.toggled.connect(self._set_markdown)
        # Versioning needs git: without it, the option is off and cannot be turned on.
        self.versioning_action = options_menu.addAction(tr("versioning"))
        self.versioning_action.setCheckable(True)
        self.versioning_action.setChecked(session.get("versioning", True) and git_available())
        self.versioning_action.setEnabled(git_available())
        if not git_available():
            self.versioning_action.setToolTip(tr("git_missing"))
            options_menu.setToolTipsVisible(True)
        self.versioning_action.toggled.connect(self._set_versioning)
        store.versioning = self.versioning_action.isChecked()
        sort_menu = options_menu.addMenu(tr("sort_by"))
        sort_group = QActionGroup(sort_menu)
        for key in SORT_ORDERS:
            action = sort_menu.addAction(tr(f"sort_{key}"))
            action.setCheckable(True)
            action.setChecked(key == self.sort_order())
            action.triggered.connect(lambda _=False, key=key: self._set_sort_order(key))
            sort_group.addAction(action)
        options_menu.addSeparator()
        options_menu.addAction(tr("deleted_notes"), self.open_trash)
        options_menu.addAction(tr("export"), self.export_archive)
        options_menu.addAction(tr("import"), self.import_archive)
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
        self.shortcuts_action = options_menu.addAction(tr("shortcuts_menu"), self.show_shortcuts)
        # A method rather than a lambda: Qt disconnects it when the window goes.
        settings.changed.connect(self._show_shortcut_keys)
        self._show_shortcut_keys()
        options_menu.addAction(tr("about_menu"), self.show_about)
        options_menu.addSeparator()
        if DEV_MODE:
            # Picks up changes to the code without closing and reopening by hand.
            options_menu.addAction(tr("restart"), self.restart)
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
        layout.addWidget(self.search)
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

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _show_shortcut_keys(self) -> None:
        self.shortcuts_action.setShortcut(first_key("shortcuts"))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.KeyPress \
                and settings.matches("open_first", event):
            self._open_first_match()
            return True
        return super().eventFilter(watched, event)

    def _open_first_match(self) -> None:
        if self.list.count() and self.list.item(0).data(Qt.UserRole):
            self.open_note(self.list.item(0).data(Qt.UserRole))

    def _matches(self, note: Note, words: list[str]) -> bool:
        """Whether every word of the search is in the note's title or text."""
        window = self.windows.get(note.id)
        # An open note is searched as it is on screen, saved or not.
        content = window.content_edit.toPlainText() if window is not None else note.content
        text = searchable(f"{note.title}\n{content}")
        return all(word in text for word in words)

    def _set_versioning(self, enabled: bool) -> None:
        self.session.set("versioning", enabled)
        self.session.write()
        self.store.versioning = enabled
        for window in self.windows.values():
            window.set_versioning(enabled)

    def _set_markdown(self, enabled: bool) -> None:
        self.session.set("markdown", enabled)
        self.session.write()
        for window in self.windows.values():
            window.set_markdown(enabled)

    def sort_order(self) -> str:
        order = self.session.get("sort", "created")
        return order if order in SORT_ORDERS else "created"

    def _set_sort_order(self, order: str) -> None:
        self.session.set("sort", order)
        self.session.write()
        self.refresh_list()

    def refresh_list(self) -> None:
        selected = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        words = searchable(self.search.text()).split()
        for note in sorted(self.notes, **SORT_ORDERS[self.sort_order()]):
            if note.deleted or not self._matches(note, words):
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
        self.search.clear()  # the new note, empty, would not match
        self.refresh_list()
        self.list.setCurrentRow(next(row for row in range(self.list.count())
                                     if self.list.item(row).data(Qt.UserRole) == note.id))
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
            window.on_top_changed.connect(self._on_note_on_top_changed)
            window.font_size_changed.connect(self._on_note_font_size_changed)
            window.shortcuts_requested.connect(self.show_shortcuts)
            window.setAttribute(Qt.WA_DeleteOnClose)
            geometry = self.session.geometry(note_id)
            if geometry is not None:
                window.restoreGeometry(geometry)
            window.set_on_top(note_id in self.session.get("on_top", []))
            window.set_font_size(self.session.get("font_sizes", {}).get(note_id, DEFAULT_FONT_SIZE))
            window.set_markdown(self.markdown_action.isChecked())
            window.set_versioning(self.store.versioning)
            self.windows[note_id] = window
        window.show()
        window.raise_()
        window.activateWindow()
        if recent:
            others = [i for i in self.session.get("recent", []) if i != note_id]
            self.session.set("recent", [note_id, *others][:RECENT_NOTES])
            self.refresh_tray_menu()
        self.save_session()

    def _on_note_on_top_changed(self, window: NoteWindow) -> None:
        on_top = [i for i in self.session.get("on_top", []) if i != window.note.id]
        if window.on_top_button.isChecked():
            on_top.append(window.note.id)
        self.session.set("on_top", on_top)
        self.save_session()

    def _on_note_font_size_changed(self, window: NoteWindow) -> None:
        sizes = self.session.get("font_sizes", {})
        sizes.pop(window.note.id, None)
        if window.font_size != DEFAULT_FONT_SIZE:
            sizes[window.note.id] = window.font_size
        self.session.set("font_sizes", sizes)
        self.session.write()

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

    def export_archive(self) -> None:
        default = Path.home() / f"{APP_ID}-{datetime.now():%Y-%m-%d}.zip"
        path, _ = QFileDialog.getSaveFileName(self, tr("export_title"), str(default),
                                              tr("archive_filter"))
        if not path:
            return
        self.save_all()  # the archive holds what is on screen
        try:
            count = export_notes(self.store, Path(path))
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, tr("export_failed", error=error))
            return
        QMessageBox.information(self, APP_NAME, tr("exported", count=count, path=path))

    def import_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("import_title"), str(Path.home()),
                                              tr("archive_filter"))
        if not path:
            return
        try:
            added, skipped = import_notes(self.store, Path(path))
        except (OSError, ArchiveError, subprocess.CalledProcessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("import_failed", error=error))
            return
        self.notes.extend(added)
        self.refresh_list()
        QMessageBox.information(self, APP_NAME, tr("imported", count=len(added), skipped=skipped))

    def save_all(self) -> None:
        for window in self.windows.values():
            window.save()

    def update_app(self) -> None:
        if not can_update():
            QMessageBox.information(self, APP_NAME, tr("update_from_clone", path=APP_DIR))
            return
        try:
            release = update_available(run_command)
            if release is None:
                QMessageBox.information(self, APP_NAME, tr("up_to_date"))
                return
            text = tr("update_available", version=release.tag)
            if FROZEN:
                text += "\n" + tr("update_restarts")
            box = QMessageBox(QMessageBox.Question, tr("update"), text,
                              QMessageBox.Yes | QMessageBox.No, self)
            box.setInformativeText(release_notes(release, run_command))
            if box.exec() != QMessageBox.Yes:
                return
            self.save_all()
            if FROZEN:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    self.staged_update = (stage_update(release), release)
                finally:
                    QApplication.restoreOverrideCursor()
                self._apply_staged_update(launch=True)
                self.quit_app()
                return
            install_release(release, run_command)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("update_failed", error=error))
            return
        self._offer_restart()

    def _apply_staged_update(self, launch: bool) -> None:
        """Hand a downloaded standalone build over to its installer, which puts it in
        place once this process has ended, and launches it again when asked."""
        if self.staged_update is None:
            return
        staging, release = self.staged_update
        self.staged_update = None
        hand_over(installer(staging, "yes", "removesource", *(["launch"] if launch else []),
                            target=APP_DIR, release=release, wait_pid=os.getpid()))

    def _offer_restart(self, notes: str = "") -> None:
        box = QMessageBox(QMessageBox.Question, tr("update"), tr("update_done"),
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(notes)  # what the new version brings, when it says
        if box.exec() == QMessageBox.Yes:
            self.restart()

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def restart(self) -> None:
        """Quit, saving the session and the notes, and launch the application again."""
        # Closed first, so the new instance does not hand itself over to this one.
        self.server.close()
        if self.staged_update is not None:
            # The installer launches the new build once it is in place: the old one,
            # running meanwhile, would keep its files from being replaced.
            self._apply_staged_update(launch=True)
            self.quit_app()
            return
        self.quit_app()
        QProcess.startDetached(sys.executable, [] if FROZEN else [str(APP_DIR / "pense_bete.py")])

    def auto_update(self) -> None:
        """At launch, when enabled: update in a background thread, keeping the interface
        free; failures such as being offline stay silent until the next launch."""
        if not (self.auto_update_action.isChecked() and can_update()):
            return

        def check_and_install() -> None:
            try:
                release = update_available()
                if release is not None and FROZEN:
                    # Put in place once the application quits, which it may do at once.
                    self.staged_update = (stage_update(release), release)
                    self.auto_updated.emit(release.tag, release_notes(release))
                elif release is not None:
                    install_release(release)
                    self.auto_updated.emit(release.tag, release_notes(release))
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"Automatic update failed: {error}", file=sys.stderr)

        threading.Thread(target=check_and_install, daemon=True).start()

    def _on_auto_updated(self, release: str, notes: str) -> None:
        # The files are replaced, or for the standalone build ready to be; this process
        # keeps running the version it loaded.
        if self.tray.isVisible() and not self.isVisible():
            self.tray.showMessage(APP_NAME, tr("auto_updated", version=release),
                                  QIcon(str(ICON_PATH)))
        else:
            self._offer_restart(notes)

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
        if FROZEN:
            self._uninstall_after_exit(purging)
            return
        try:
            result = run_command(*installer(APP_DIR, "uninstall", "yes",
                                            *(["purge"] if purging else []),
                                            *(["dev"] if DEV_MODE else [])))
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

    def _uninstall_after_exit(self, purging: bool) -> None:
        """The standalone build cannot remove its own files while it runs: its installer
        does, once the application has quit, which it does at once."""
        hand_over(installer(APP_DIR, "uninstall", "yes", *(["purge"] if purging else []),
                            wait_pid=os.getpid()))
        QMessageBox.information(self, APP_NAME, tr("uninstall_after_exit"))
        if not purging:
            self.quit_app()
            return
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
        # An update downloaded and not installed yet goes in once the application is gone.
        self._apply_staged_update(launch=False)
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
