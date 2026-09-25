"""Every test runs away from the user's notes, settings and desktop.

The environment is set before the application is imported, since its paths are
computed at import time: HOME and the XDG directories point into a throwaway
directory, Qt draws offscreen, and the interface is in English.
"""

import atexit
import os
import shutil
import site
import tempfile
from pathlib import Path

import pytest

HOME = Path(tempfile.mkdtemp(prefix="pense-bete-tests-"))
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
# Where pip --user put PySide6, resolved from the real HOME before it is replaced, for
# the scripts the tests run.
os.environ["PYTHONUSERBASE"] = site.getuserbase()
os.environ["HOME"] = str(HOME)
os.environ["XDG_DATA_HOME"] = str(HOME / ".local" / "share")
os.environ["XDG_CONFIG_HOME"] = str(HOME / ".config")
os.environ.pop("PENSE_BETE_DIR", None)
os.environ.pop("PENSE_BETE_REPO", None)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LC_ALL"] = "C"
os.environ["LANG"] = "C"

REPO_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path):
    from pensebete.storage import NoteStore
    return NoteStore(tmp_path / "notes")


@pytest.fixture
def session(tmp_path):
    from pensebete.session import Session
    return Session(tmp_path / "config" / "session.json")


@pytest.fixture
def answer_yes(monkeypatch):
    """Every confirmation is accepted; warnings are recorded instead of shown."""
    from PySide6.QtWidgets import QMessageBox
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    return warnings


@pytest.fixture
def main_window(qtbot, store, session, answer_yes, request):
    from PySide6.QtNetwork import QLocalServer
    from pensebete.main_window import MainWindow
    server = QLocalServer()
    server.listen(f"pense-bete-tests-{os.getpid()}-{request.node.name}")
    window = MainWindow(store, session, server)
    yield window
    # Not handed to qtbot, whose closing would quit the application the usual way.
    if not window.quitting:  # otherwise quit_app already closed the notes
        window.quitting = True
        for note_window in list(window.windows.values()):
            note_window.discard()
    window.tray.hide()
    window.close()
    window.deleteLater()
    server.close()


def commits(repo_dir: Path) -> list[str]:
    """The commit subjects of a repository, newest first."""
    import subprocess
    output = subprocess.run(["git", "-C", str(repo_dir), "log", "--format=%s"],
                            capture_output=True, text=True, check=True).stdout
    return output.splitlines()
