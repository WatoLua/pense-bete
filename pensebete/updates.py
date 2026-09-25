"""Updating the installed application from its repository."""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .config import APP_DIR, RELEASE_FILE, REPO_URL, SUBPROCESS_OPTIONS, VERSION_FILE, WINDOWS


def run(*args: str) -> subprocess.CompletedProcess:
    """Run a command, its output captured for error messages."""
    return subprocess.run(args, capture_output=True, timeout=300, **SUBPROCESS_OPTIONS)


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


def installer(directory: Path, *options: str, target: Path | None = None) -> list[str]:
    """The command running the installer of a directory with options such as "yes" or
    "uninstall": install.sh on Linux, install.ps1 on Windows, each with its own syntax."""
    if WINDOWS:
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(directory / "install.ps1")]
        command += [f"-{option.capitalize()}" for option in options]
        return command + (["-Target", str(target)] if target is not None else [])
    command = ["bash", str(directory / "install.sh")] + [f"--{option}" for option in options]
    return command + ([str(target)] if target is not None else [])


def update_available(runner=run) -> str | None:
    """The tag of the newest release when it is not the installed commit."""
    release = latest_release(runner)
    if release is None or release[1] == _read(VERSION_FILE):
        return None
    return release[0]


def install_release(tag: str, runner=run) -> None:
    """Install the given release over this installation; notes are not touched."""
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "pense-bete"
        result = runner("git", "clone", "--quiet", "--depth", "1", "--branch", tag, "--",
                        REPO_URL, str(source))
        if result.returncode == 0:
            result = runner(*installer(source, "yes", target=APP_DIR))
    if result.returncode:
        raise RuntimeError(command_error(result))


def release_notes(tag: str, runner=run) -> str:
    """The message of a release's annotated tag, "" for a tag without one or when it
    cannot be read: the notes are a bonus, never a reason for an update to fail."""
    with tempfile.TemporaryDirectory() as temporary:
        if runner("git", "init", "--quiet", "--bare", temporary).returncode:
            return ""
        ref = f"refs/tags/{tag}"
        if runner("git", "-C", temporary, "fetch", "--quiet", "--depth", "1", "--",
                  REPO_URL, f"{ref}:{ref}").returncode:
            return ""
        result = runner("git", "-C", temporary, "for-each-ref", "--format=%(objecttype)",
                        ref)
        if result.returncode or result.stdout.strip() != "tag":
            return ""  # a lightweight tag: its "message" would be the commit's
        result = runner("git", "-C", temporary, "for-each-ref", "--format=%(contents)", ref)
        return result.stdout.strip() if result.returncode == 0 else ""


@dataclass
class InstalledVersion:
    """What runs: a release, or the commit of a clone in development."""

    release: str = ""  # vX.Y.Z, "" when unknown
    commit: str = ""  # abbreviated
    installed: datetime | None = None  # when the installer put it in place
    branch: str = ""  # in development only
    modified: bool = False  # in development: changes not committed


def installed_version(runner=run) -> InstalledVersion:
    if (APP_DIR / ".git").exists():
        branch = runner("git", "-C", str(APP_DIR), "rev-parse", "--abbrev-ref", "HEAD")
        commit = runner("git", "-C", str(APP_DIR), "rev-parse", "--short", "HEAD")
        status = runner("git", "-C", str(APP_DIR), "status", "--porcelain")
        return InstalledVersion(commit=commit.stdout.strip(), branch=branch.stdout.strip(),
                                modified=bool(status.stdout.strip()))
    installed = None
    if VERSION_FILE.exists():
        installed = datetime.fromtimestamp(VERSION_FILE.stat().st_mtime)
    return InstalledVersion(release=_read(RELEASE_FILE), commit=_read(VERSION_FILE)[:7],
                            installed=installed)


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""
