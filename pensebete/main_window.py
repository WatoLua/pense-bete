"""The list of notes, which opens their windows and holds the application's menus."""

import subprocess
import sys
import threading
import uuid

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
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

from .config import (
    APP_DIR, APP_NAME, DATA_DIR, DEFAULT_RETENTION_DAYS, DEV_MODE, ICON_PATH, RECENT_NOTES,
)
from .i18n import tr
from .note_window import NoteWindow
from .session import Session
from .storage import Note, NoteStore, Version
from .style import color_icon, text_color_for
from .trash import TrashDialog
from .updates import can_update, command_error, install_release, run_command, update_available


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
            window.on_top_changed.connect(self._on_note_on_top_changed)
            window.setAttribute(Qt.WA_DeleteOnClose)
            geometry = self.session.geometry(note_id)
            if geometry is not None:
                window.restoreGeometry(geometry)
            window.set_on_top(note_id in self.session.get("on_top", []))
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
            release = update_available(run_command)
            if release is None:
                QMessageBox.information(self, APP_NAME, tr("up_to_date"))
                return
            if QMessageBox.question(self, tr("update"), tr("update_available", version=release)
                                    ) != QMessageBox.Yes:
                return
            self.save_all()
            install_release(release, run_command)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            QMessageBox.warning(self, APP_NAME, tr("update_failed", error=error))
            return
        self._offer_restart()

    def _offer_restart(self) -> None:
        if QMessageBox.question(self, tr("update"), tr("update_done")) == QMessageBox.Yes:
            self.restart()

    def restart(self) -> None:
        """Quit, saving the session and the notes, and launch the application again."""
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
                release = update_available()
                if release is not None:
                    install_release(release)
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
