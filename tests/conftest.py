"""Every test runs away from the user's notes, settings and desktop.

The environment is set before the application is imported, since its paths are
computed at import time: HOME, the XDG directories and their Windows counterparts point
into a throwaway directory, Qt draws offscreen, and the interface is in English.
"""

import atexit
import os
import shutil
import site
import sys
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
# On Windows, where the application and install.ps1 look instead, the Start menu included.
os.environ["USERPROFILE"] = str(HOME)
os.environ["APPDATA"] = str(HOME / "AppData" / "Roaming")
os.environ["LOCALAPPDATA"] = str(HOME / "AppData" / "Local")
os.environ["PENSE_BETE_SHORTCUT_DIR"] = str(HOME / "Start Menu")
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


@pytest.fixture
def tagged_repo(tmp_path):
    """A bare copy of this repository with releases v1.9.0 (on HEAD), v1.10.0 (annotated,
    on a commit made on top of it) and a v2.0.0-rc1 that is not a release.

    The newer commit is made here, with HEAD's files, so that the fixture does not
    depend on the history of the checkout, which CI clones one commit deep.
    Returns the repository and the commit of each tag.
    """
    import subprocess

    def git(*args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()

    repo = tmp_path / "remote.git"
    git("clone", "--quiet", "--bare", "--no-local", str(REPO_DIR), str(repo))
    identity = ("-c", "user.name=t", "-c", "user.email=t@t")
    older = git("rev-parse", "HEAD", cwd=repo)
    newer = git(*identity, "commit-tree", "HEAD^{tree}", "-p", older, "-m", "Newer", cwd=repo)
    git("update-ref", "HEAD", newer, cwd=repo)
    git("tag", "v1.9.0", older, cwd=repo)
    git(*identity, "tag", "-a", "-m", "Release", "v1.10.0", newer, cwd=repo)
    git("tag", "v2.0.0-rc1", newer, cwd=repo)
    return repo, {"v1.9.0": older, "v1.10.0": newer}


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Linux only")
