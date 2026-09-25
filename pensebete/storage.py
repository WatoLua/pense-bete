"""The notes on disk: one directory and git repository per note."""

import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale

from .config import DEFAULT_COLOR, SUBPROCESS_OPTIONS
from .i18n import tr

# Each note lives in its own directory and git repository: <DATA_DIR>/<note id>/note.json.
NOTE_FILE = "note.json"


def remove_tree(path: Path) -> None:
    """Delete a directory and everything in it, read-only files included: git makes its
    objects read-only, which Windows refuses to delete as they are."""
    def make_writable_and_retry(function, failed_path, _error) -> None:
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


def note_dirs(path: Path) -> list[Path]:
    """The note directories in a directory: those holding a note file."""
    if not path.is_dir():
        return []
    return sorted(child for child in path.iterdir() if (child / NOTE_FILE).is_file())


def move_notes(source: Path, target: Path) -> None:
    """Move every note directory, history included, from one directory to another.

    Everything is copied before anything is deleted, so that a failure halfway leaves
    the notes where they were, the copies made removed. Other files in the source stay;
    the source goes if that leaves it empty.
    """
    source, target = source.resolve(), target.resolve()
    if target == source or target.is_relative_to(source):
        raise OSError(tr("move_inside", path=source))
    notes = note_dirs(source)
    taken = [note.name for note in notes if (target / note.name).exists()]
    if taken:
        raise FileExistsError(tr("move_taken", path=target / taken[0]))
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    try:
        for note in notes:
            copied.append(target / note.name)  # before, so a copy cut short goes too
            shutil.copytree(note, target / note.name, symlinks=True)
    except (OSError, shutil.Error):
        for copy in copied:
            if copy.exists():
                remove_tree(copy)
        raise
    for note in notes:
        remove_tree(note)
    try:
        source.rmdir()
    except OSError:
        pass  # other files are in it


class GitRepo:
    """Thin wrapper around the git CLI for one repository."""

    def __init__(self, path: Path):
        self.path = path
        if not (path / ".git").exists():
            path.mkdir(parents=True, exist_ok=True)
            self._run("init", "--quiet")
            # The note is stored as written: Git for Windows would otherwise turn its line
            # ends into CRLF, and back, by default.
            self._run("config", "core.autocrlf", "false")
            # Commits must never fail for lack of an identity on this machine.
            if not self._run("config", "user.email", check=False).stdout.strip():
                self._run("config", "user.name", "Pense-bête")
                self._run("config", "user.email", "pense-bete@localhost")

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True, check=check,
                              **SUBPROCESS_OPTIONS)

    def commit_file(self, filename: str, message: str) -> None:
        """Stage one file and commit it if it changed."""
        self._run("add", "--all", "--", filename)
        if self._run("diff", "--cached", "--quiet", "--", filename, check=False).returncode:
            self._run("commit", "--quiet", "-m", message, "--", filename)

    def file_versions(self, filename: str) -> list[tuple[str, int, str]]:
        """(commit, timestamp, content) of each commit that changed the file, newest first."""
        log = self._run("log", "--format=%H %at", "--", filename).stdout.split()
        commits = list(zip(log[0::2], map(int, log[1::2])))
        if not commits:
            return []
        # All contents in one git process, which keeps long histories fast to open.
        requests = "".join(f"{commit}:{filename}\n" for commit, _ in commits).encode()
        # In bytes: sizes are counted in bytes, and contents decoded once cut out.
        options = {key: value for key, value in SUBPROCESS_OPTIONS.items()
                   if key not in ("encoding", "errors")}
        output = subprocess.run(["git", "cat-file", "--batch"], cwd=self.path, input=requests,
                                capture_output=True, check=True, **options).stdout
        versions, position = [], 0
        for commit, timestamp in commits:
            end = output.index(b"\n", position)
            header = output[position:end].split()
            position = end + 1
            if header[-1] == b"missing":  # the commit that deleted the file
                continue
            size = int(header[2])
            versions.append((commit, timestamp, output[position:position + size].decode()))
            position += size + 1
        return versions


@dataclass
class Version:
    """A note as saved by one commit."""

    commit: str
    timestamp: int
    title: str
    color: str
    content: str

    @property
    def date(self) -> str:
        # With seconds: saves come 10 seconds apart, so a minute often holds several.
        moment = QDateTime.fromSecsSinceEpoch(self.timestamp)
        return (f"{QLocale().toString(moment.date(), QLocale.FormatType.ShortFormat)}"
                f" {moment.toString('HH:mm:ss')}")


class Note:
    def __init__(self, note_id: str, title: str = "", color: str = DEFAULT_COLOR,
                 content: str = "", created: str | None = None, deleted: str | None = None,
                 modified: str | None = None):
        self.id = note_id
        self.title = title
        self.color = color
        self.content = content
        self.created = created or datetime.now().isoformat(timespec="seconds")
        # When the note was last edited; absent from notes never edited since created.
        self.modified = modified
        # When the note was deleted: it stays in the trash, restorable, until it expires.
        self.deleted = deleted

    def days_in_trash(self) -> int:
        return (datetime.now() - datetime.fromisoformat(self.deleted)).days if self.deleted else 0

    @property
    def display_title(self) -> str:
        return self.title.strip() or tr("untitled")

    def to_dict(self) -> dict:
        data = {"id": self.id, "title": self.title, "color": self.color,
                "content": self.content, "created": self.created}
        if self.modified:
            data["modified"] = self.modified
        if self.deleted:
            data["deleted"] = self.deleted
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(data["id"], data.get("title", ""), data.get("color", DEFAULT_COLOR),
                   data.get("content", ""), data.get("created"), data.get("deleted"),
                   data.get("modified"))

    @property
    def last_edited(self) -> str:
        return self.modified or self.created


class NoteStore:
    """The notes, one directory each, and with versioning one git repository each, so that
    every note has its own history.

    Without versioning, when git is missing or turned off, notes are saved alone and
    have no history; repositories already there are kept, and saves are committed
    again once versioning is back, a note's first commit then holding its text as it is.
    """

    def __init__(self, path: Path, versioning: bool = True):
        self.path = path
        self.versioning = versioning
        self.repos: dict[str, GitRepo] = {}
        path.mkdir(parents=True, exist_ok=True)

    def _repo(self, note: Note) -> GitRepo:
        repo = self.repos.get(note.id)
        if repo is None:
            repo = self.repos[note.id] = GitRepo(self.path / note.id)
        return repo

    def load_all(self) -> list[Note]:
        notes = []
        for file in self.path.glob(f"*/{NOTE_FILE}"):
            try:
                notes.append(Note.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError) as error:
                print(f"Ignoring unreadable note {file.parent.name}: {error}", file=sys.stderr)
        return sorted(notes, key=lambda note: note.created)

    def save(self, note: Note, message: str) -> None:
        directory = self.path / note.id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / NOTE_FILE
        # Written to a temporary file then renamed, so a crash never leaves a truncated note.
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(note.to_dict(), ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
        if self.versioning:
            self._repo(note).commit_file(NOTE_FILE, message)

    def history(self, note: Note) -> list[Version]:
        if not self.versioning:
            return []
        versions = []
        for commit, timestamp, text in self._repo(note).file_versions(NOTE_FILE):
            try:
                data = json.loads(text)
            except ValueError:
                continue
            versions.append(Version(commit, timestamp, data.get("title", ""),
                                    data.get("color", DEFAULT_COLOR), data.get("content", "")))
        return versions

    def trash(self, note: Note) -> None:
        """Delete the note, restorably: its file stays, marked with the deletion time."""
        note.deleted = datetime.now().isoformat(timespec="seconds")
        try:
            self.save(note, f'Delete "{note.display_title}"')
        except (OSError, subprocess.CalledProcessError):
            note.deleted = None
            raise

    def untrash(self, note: Note) -> None:
        deleted, note.deleted = note.deleted, None
        try:
            self.save(note, f'Restore "{note.display_title}" from the deleted notes')
        except (OSError, subprocess.CalledProcessError):
            note.deleted = deleted
            raise

    def erase(self, note: Note) -> None:
        """Remove the note for good, with its repository and so its whole history."""
        self.repos.pop(note.id, None)
        remove_tree(self.path / note.id)
