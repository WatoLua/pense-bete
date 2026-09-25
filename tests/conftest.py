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


@pytest.fixture(autouse=True)
def default_shortcuts():
    """Every test starts with the default shortcuts, whatever the one before changed."""
    yield
    from pensebete.shortcuts import settings
    settings.detach()


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


@pytest.fixture
def no_git_path(tmp_path):
    """A PATH with every command of this one but git, as on a machine without git."""
    import shutil
    names = {"git", "git.exe", "git.cmd"}
    directories = [d for d in os.environ.get("PATH", "").split(os.pathsep) if os.path.isdir(d)]
    if sys.platform == "win32":
        # Git for Windows has directories of its own: the PATH goes without them.
        path = os.pathsep.join(d for d in directories
                               if not any(os.path.exists(os.path.join(d, n)) for n in names))
    else:
        # git shares /usr/bin with everything else: the PATH is links to all but git.
        bin_dir = tmp_path / "no-git-bin"
        bin_dir.mkdir()
        for directory in directories:
            for entry in os.scandir(directory):
                link = bin_dir / entry.name
                if entry.name not in names and not link.exists() and os.access(entry.path, os.X_OK):
                    os.symlink(entry.path, link)
        path = str(bin_dir)
    assert shutil.which("git", path=path) is None
    return path


@pytest.fixture
def fake_github():
    """A local stand-in for the GitHub API: its tags and the archive of v1.10.0, made
    of this working tree's files. Yields the API address and the release's commit."""
    import io
    import json
    import threading
    import zipfile
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        for file in REPO_DIR.rglob("*"):
            relative = file.relative_to(REPO_DIR)
            if file.is_file() and not {".git", "__pycache__", ".pytest_cache"} & set(relative.parts):
                output.write(file, f"someone-pense-bete-1a2b3c4/{relative.as_posix()}")
    commit = "1a2b3c4d" * 5
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as output:
        for name, data in fake_bundle_files().items():
            output.writestr(f"Pense-bete/{name}", data)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path.startswith("/tags"):
                body = json.dumps([
                    {"name": "v1.9.0", "commit": {"sha": "0" * 40}, "zipball_url": f"{base}/old"},
                    {"name": "v1.10.0", "commit": {"sha": commit}, "zipball_url": f"{base}/zip"},
                ]).encode()
            elif self.path == "/zip":
                body = archive.getvalue()
            elif self.path == "/releases/tags/v1.10.0":
                body = json.dumps({"assets": [{"name": "pense-bete-windows.zip",
                                               "browser_download_url": f"{base}/bundle"}]}).encode()
            elif self.path == "/bundle":
                body = bundle.getvalue()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", commit
    server.shutdown()


def fake_bundle_files() -> dict[str, bytes]:
    """A standalone build's files, its executable a harmless program of the system that
    prints and exits, so that launching it does no harm."""
    whoami = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "whoami.exe"
    files = {"Pense-bete.exe": whoami.read_bytes() if whoami.exists() else b"MZ",
             "_internal/python312.dll": b"library"}
    for name in ("icon.svg", "icon.ico", "LICENSE", "install.ps1"):
        files[name] = (REPO_DIR / name).read_bytes()
    return files
