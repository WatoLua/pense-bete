"""Updating the installed application from its repository."""

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .config import APP_DIR, REPO_URL, VERSION_FILE


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
