"""The notes on disk: one directory and git repository per note."""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale

from .config import DEFAULT_COLOR
from .i18n import tr

# Each note lives in its own directory and git repository: <DATA_DIR>/<note id>/note.json.
NOTE_FILE = "note.json"


class GitRepo:
    """Thin wrapper around the git CLI for one repository."""

    def __init__(self, path: Path):
        self.path = path
        if not (path / ".git").exists():
            path.mkdir(parents=True, exist_ok=True)
            self._run("init", "--quiet")
            # Commits must never fail for lack of an identity on this machine.
            if not self._run("config", "user.email", check=False).stdout.strip():
                self._run("config", "user.name", "Pense-bête")
                self._run("config", "user.email", "pense-bete@localhost")

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=check
        )

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
        output = subprocess.run(["git", "cat-file", "--batch"], cwd=self.path, input=requests,
                                capture_output=True, check=True).stdout
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
    """The notes, one directory and git repository each, so every note has its own history."""

    def __init__(self, path: Path):
        self.path = path
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
        repo = self._repo(note)
        target = repo.path / NOTE_FILE
        # Written to a temporary file then renamed, so a crash never leaves a truncated note.
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(note.to_dict(), ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
        repo.commit_file(NOTE_FILE, message)

    def history(self, note: Note) -> list[Version]:
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
        shutil.rmtree(self.path / note.id)
