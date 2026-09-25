"""Updating the installed application from its repository."""

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .config import APP_DIR, RELEASE_FILE, REPO_URL, SUBPROCESS_OPTIONS, VERSION_FILE, WINDOWS
from .i18n import tr
from .storage import remove_tree


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


class Release(NamedTuple):
    tag: str
    commit: str  # what an installation records in .version
    archive: str = ""  # without git: where to download it as a zip


def git_available() -> bool:
    return shutil.which("git") is not None


def github_api() -> str:
    """The GitHub API address of the repository, "" for a repository elsewhere, which
    only git can reach. PENSE_BETE_API stands in for GitHub in the tests."""
    if os.environ.get("PENSE_BETE_API"):
        return os.environ["PENSE_BETE_API"].rstrip("/")
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?", REPO_URL)
    return f"https://api.github.com/repos/{match[1]}/{match[2]}" if match else ""


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pense-bete",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except (OSError, ValueError) as error:  # URLError and HTTPError are OSErrors
        raise RuntimeError(f"{url}: {error}") from error


def latest_release(runner=run, fetcher=http_get, use_git: bool | None = None) -> Release | None:
    """The newest vX.Y.Z tag of the repository, None when it has none: through git, or
    without it through the GitHub API."""
    if use_git is None:
        use_git = git_available()
    if not use_git:
        api = github_api()
        if not api:
            raise RuntimeError(tr("update_needs_git", url=REPO_URL))
        tags = json.loads(fetcher(f"{api}/tags?per_page=100"))
        releases = [tag for tag in tags if parse_version(tag["name"])]
        if not releases:
            return None
        tag = max(releases, key=lambda tag: parse_version(tag["name"]))
        return Release(tag["name"], tag["commit"]["sha"], tag["zipball_url"])
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
    return Release(tag, commits[tag])


def installer(directory: Path, *options: str, target: Path | None = None,
              release: Release | None = None, wait_pid: int | None = None) -> list[str]:
    """The command running the installer of a directory with options such as "yes" or
    "uninstall": install.sh on Linux, install.ps1 on Windows, each with its own syntax.

    A release's tag and commit are passed on for the installer to record, which it
    cannot ask git for in a downloaded archive. wait_pid, on Windows, has it wait for
    that process to end first.
    """
    values = {"commit": release.commit, "release": release.tag} if release else {}
    if wait_pid is not None:
        values["waitpid"] = str(wait_pid)
    if WINDOWS:
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(directory / "install.ps1")]
        command += [f"-{option.capitalize()}" for option in options]
        for name, value in values.items():
            command += [f"-{name.capitalize()}", value]
        return command + (["-Target", str(target)] if target is not None else [])
    command = ["bash", str(directory / "install.sh")] + [f"--{option}" for option in options]
    command += [f"--{name}={value}" for name, value in values.items()]
    return command + ([str(target)] if target is not None else [])


def update_available(runner=run, fetcher=http_get) -> Release | None:
    """The newest release when it is not the installed commit."""
    release = latest_release(runner, fetcher)
    if release is None or release.commit == _read(VERSION_FILE):
        return None
    return release


def install_release(release: Release, runner=run, fetcher=http_get) -> None:
    """Install the given release over this installation; notes are not touched."""
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "pense-bete"
        if release.archive:
            try:
                extract_archive(fetcher(release.archive), source)
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                raise RuntimeError(f"{release.archive}: {error}") from error
            result = runner(*installer(source, "yes", target=APP_DIR, release=release))
        else:
            result = runner("git", "clone", "--quiet", "--depth", "1", "--branch", release.tag,
                            "--", REPO_URL, str(source))
            if result.returncode == 0:
                result = runner(*installer(source, "yes", target=APP_DIR, release=release))
    if result.returncode:
        raise RuntimeError(command_error(result))


def extract_archive(data: bytes, target: Path) -> None:
    """Unpack a GitHub archive, whose files are all in one top directory, into target."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [PurePosixPath(name) for name in archive.namelist()]
        if not names or any(name.is_absolute() or ".." in name.parts for name in names):
            raise ValueError("not an archive of the application")
        with tempfile.TemporaryDirectory() as temporary:
            archive.extractall(temporary)
            [top] = Path(temporary).iterdir()
            shutil.move(str(top), str(target))


def release_notes(release: Release, runner=run, fetcher=http_get) -> str:
    """The message of a release's annotated tag, "" for a tag without one or when it
    cannot be read: the notes are a bonus, never a reason for an update to fail."""
    if release.archive:
        try:
            api = github_api()
            ref = json.loads(fetcher(f"{api}/git/refs/tags/{release.tag}"))["object"]
            if ref["type"] != "tag":
                return ""  # a lightweight tag: its "message" would be the commit's
            return json.loads(fetcher(f"{api}/git/tags/{ref['sha']}"))["message"].strip()
        except (RuntimeError, ValueError, KeyError, TypeError):
            return ""
    with tempfile.TemporaryDirectory() as temporary:
        if runner("git", "init", "--quiet", "--bare", temporary).returncode:
            return ""
        ref = f"refs/tags/{release.tag}"
        if runner("git", "-C", temporary, "fetch", "--quiet", "--depth", "1", "--",
                  REPO_URL, f"{ref}:{ref}").returncode:
            return ""
        result = runner("git", "-C", temporary, "for-each-ref", "--format=%(objecttype)",
                        ref)
        if result.returncode or result.stdout.strip() != "tag":
            return ""  # a lightweight tag: its "message" would be the commit's
        result = runner("git", "-C", temporary, "for-each-ref", "--format=%(contents)", ref)
        return result.stdout.strip() if result.returncode == 0 else ""


BUNDLE_ASSET = "pense-bete-windows.zip"
# What the installer an update hands over to reports, since it runs without a window.
HANDOVER_LOG = Path(tempfile.gettempdir()) / "pense-bete-install.log"


def bundle_url(release: Release, fetcher=http_get) -> str:
    """Where the standalone build of a release is attached on GitHub."""
    api = github_api()
    if not api:
        raise RuntimeError(tr("update_needs_github", url=REPO_URL))
    try:
        assets = json.loads(fetcher(f"{api}/releases/tags/{release.tag}")).get("assets", [])
        return next(asset["browser_download_url"] for asset in assets
                    if asset["name"] == BUNDLE_ASSET)
    except (RuntimeError, ValueError, KeyError, TypeError, StopIteration) as error:
        # The build runs for a few minutes after a release is tagged.
        raise RuntimeError(tr("bundle_missing", version=release.tag)) from error


def stage_update(release: Release, fetcher=http_get) -> Path:
    """Download and unpack a release's standalone build, for the installer to put in
    place once the application has quit: Windows forbids replacing a running program.
    Returns its directory, which the installer removes afterwards."""
    staging = Path(tempfile.mkdtemp(prefix="pense-bete-update-"))
    try:
        extract_archive(fetcher(bundle_url(release, fetcher)), staging / "Pense-bete")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        remove_tree(staging)
        raise RuntimeError(str(error)) from error
    return staging / "Pense-bete"


def hand_over(command: list[str]) -> None:
    """Start an installer that waits for this process to end, and let it run on: it
    goes on once the application has quit, its output in HANDOVER_LOG."""
    with open(HANDOVER_LOG, "w", encoding="utf-8") as log:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def git_version(runner=run) -> str:
    """git's version, "" without git."""
    if not git_available():
        return ""
    result = runner("git", "--version")
    return result.stdout.strip().removeprefix("git version ") if result.returncode == 0 else ""


@dataclass
class InstalledVersion:
    """What runs: a release, or the commit of a clone in development."""

    release: str = ""  # vX.Y.Z, "" when unknown
    commit: str = ""  # abbreviated
    installed: datetime | None = None  # when the installer put it in place
    branch: str = ""  # in development only
    modified: bool = False  # in development: changes not committed


def installed_version(runner=run) -> InstalledVersion:
    if (APP_DIR / ".git").exists() and git_available():
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
