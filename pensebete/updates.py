"""Updating the installed application from its repository."""

import re
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


def parse_version(tag: str) -> tuple[int, int, int] | None:
    """(1, 2, 10) for "v1.2.10"; None for a tag that does not name a release."""
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def latest_release(runner=run) -> tuple[str, str] | None:
    """(tag, commit) of the newest vX.Y.Z tag of the repository, None when it has none."""
    remote = runner("git", "ls-remote", "--tags", REPO_URL, "refs/tags/v*")
    if remote.returncode:
        raise RuntimeError(command_error(remote))
    commits: dict[str, str] = {}
    for line in remote.stdout.splitlines():
        commit, _, ref = line.partition("\t")
        tag = ref.removeprefix("refs/tags/")
        # An annotated tag is listed twice: its own object, then as "tag^{}" the commit it
        # points to, which is what an installation records.
        if tag.endswith("^{}"):
            commits[tag[:-3]] = commit
        else:
            commits.setdefault(tag, commit)
    releases = [tag for tag in commits if parse_version(tag)]
    if not releases:
        return None
    tag = max(releases, key=parse_version)
    return tag, commits[tag]


def update_available(runner=run) -> str | None:
    """The tag of the newest release when it is not the installed commit."""
    release = latest_release(runner)
    installed = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
    if release is None or release[1] == installed:
        return None
    return release[0]


def install_release(tag: str, runner=run) -> None:
    """Install the given release over this installation; notes are not touched."""
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "pense-bete"
        result = runner("git", "clone", "--quiet", "--depth", "1", "--branch", tag, "--",
                        REPO_URL, str(source))
        if result.returncode == 0:
            result = runner("bash", str(source / "install.sh"), "--yes", str(APP_DIR))
    if result.returncode:
        raise RuntimeError(command_error(result))
