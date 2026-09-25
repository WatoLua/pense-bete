"""Starting the application: one instance per user, its windows back as they were."""

import getpass
import os
import signal
import socket
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QSocketNotifier, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .config import APP_ID, APP_NAME, DATA_DIR, ICON_PATH, SESSION_FILE, WINDOWS
from .i18n import LANGUAGE
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
    window.auto_update()
    keep_alive = save_on_shutdown(app, window)  # referenced until exec returns
    sys.exit(app.exec())
