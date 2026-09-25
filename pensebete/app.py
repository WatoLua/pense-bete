"""Starting the application: one instance per user, its windows back as they were."""

import getpass
import os
import signal
import socket
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSocketNotifier, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import (
    APP_ID, APP_NAME, DATA_DIR, DATA_DIR_UNAVAILABLE, ICON_PATH, SESSION_FILE, WINDOWS,
)
from .i18n import LANGUAGE, tr
from .main_window import MainWindow
from .session import Session
from .storage import NoteStore


def save_on_shutdown(app: QApplication, window: MainWindow) -> list:
    """Save everything when the session ends or the process is told to stop.

    Returns the objects that must stay alive for as long as the application runs.
    """
    # Before a logout, which may still be cancelled: save, but keep running.
    app.commitDataRequest.connect(lambda _manager: (window.save_all(), window.save_session()))

    # A stop signal, as a shutdown may send, quits the usual way, saving the notes.
    # Python only runs signal handlers between its own instructions, never while Qt's
    # event loop waits, so the signal also wakes that loop through a socket.
    wakeup_read, wakeup_write = socket.socketpair()
    wakeup_read.setblocking(False)
    wakeup_write.setblocking(False)
    signal.set_wakeup_fd(wakeup_write.fileno())
    notifier = QSocketNotifier(wakeup_read.fileno(), QSocketNotifier.Read)
    notifier.activated.connect(lambda: wakeup_read.recv(64))
    # Windows has no SIGHUP; it ends a session through commitDataRequest above.
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: window.quit_app())
    return [wakeup_read, wakeup_write, notifier]


def linux_display_defaults() -> None:
    """How Qt draws on Linux, where a platform set by the user still wins."""
    # X11, through XWayland in a Wayland session, lets windows be put back where they
    # were: Wayland leaves window positions to the compositor. Qt's xcb plugin needs
    # libxcb-cursor0; without it, Qt falls back to Wayland.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb;wayland")
    # In the Wayland fallback, Qt draws the title bar itself. Its default decoration
    # centers the title over the whole bar, where the buttons cover it on narrow note
    # windows; bradient aligns it left.
    os.environ.setdefault("QT_WAYLAND_DECORATION", "bradient")


def main() -> None:
    if sys.platform.startswith("linux"):
        linux_display_defaults()
    elif WINDOWS:
        # The taskbar groups the windows under the application rather than Python.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    # The same style on every system, and one that draws with the palette it is given:
    # a note's window takes its colors from its paper, which the Windows 11 style
    # partly ignores, leaving white text of a dark theme on a yellow note.
    app.setStyle("Fusion")
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
    server_name = f"{APP_ID}-{getpass.getuser()}"
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
    if DATA_DIR_UNAVAILABLE is not None:
        QMessageBox.warning(window if window.isVisible() else None, APP_NAME,
                            tr("data_dir_unavailable", path=DATA_DIR_UNAVAILABLE))
    window.auto_update()
    keep_alive = save_on_shutdown(app, window)  # referenced until exec returns
    sys.exit(app.exec())


def self_test(report: Path) -> int:
    """Start what a launch starts, notes and windows included, in throwaway directories,
    and write what happened to report: a build is checked this way before it is
    published, a missing Qt plugin or module showing here rather than on a user's
    machine. Returns the exit code, 0 when everything worked."""
    import tempfile
    import traceback
    lines = []
    try:
        app = QApplication.instance() or QApplication([sys.argv[0]])
        app.setStyle("Fusion")
        icon = QIcon(str(ICON_PATH))
        if icon.pixmap(32, 32).isNull():
            raise RuntimeError(f"the icon {ICON_PATH} cannot be drawn: is the SVG plugin missing?")
        lines.append(f"icon: {ICON_PATH}")
        with tempfile.TemporaryDirectory() as temporary:
            from .about import AboutDialog, ShortcutsDialog
            window = MainWindow(NoteStore(Path(temporary) / "notes"),
                                Session(Path(temporary) / "session.json"), QLocalServer())
            window.create_note()
            note_window = next(iter(window.windows.values()))
            note_window.content_edit.setPlainText("self-test")
            note_window.save()
            AboutDialog(window)
            ShortcutsDialog(window)
            lines.append(f"notes: {[note.content for note in window.store.load_all()]}")
            window.quitting = True
            for note_window in list(window.windows.values()):
                note_window.discard()
        lines.append("ok")
        code = 0
    except Exception:  # everything is worth reporting here
        lines.append(traceback.format_exc())
        code = 1
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code
