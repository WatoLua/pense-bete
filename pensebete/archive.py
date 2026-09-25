"""Exporting every note, with its history, to a zip archive, and importing one back."""

import json
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .storage import NOTE_FILE, Note, NoteStore

# A note's directory name: its id, as NoteStore creates them.
NOTE_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")


class ArchiveError(Exception):
    """The file is not an archive of notes."""


def export_notes(store: NoteStore, archive: Path) -> int:
    """Write every note, deleted ones included, with its git repository into the archive.

    Returns the number of notes exported. The archive is written next to its target,
    then renamed, so that a failed export never leaves a truncated file behind.
    """
    note_dirs = sorted(file.parent for file in store.path.glob(f"*/{NOTE_FILE}"))
    temporary = archive.with_name(f".{archive.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as output:
            for note_dir in note_dirs:
                for file in sorted(note_dir.rglob("*")):
                    if file.is_file() and not file.is_symlink():
                        output.write(file, file.relative_to(store.path).as_posix())
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return len(note_dirs)


def import_notes(store: NoteStore, archive: Path) -> tuple[list[Note], int]:
    """Add the archive's notes to the store, with their history.

    A note already in the store, unchanged, is skipped; one that differs from the
    store's is added as a separate note, so that nothing is overwritten. Returns the
    notes added and the number skipped.
    """
    try:
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            note_ids = _note_ids(members)
            with tempfile.TemporaryDirectory(dir=store.path, prefix=".import-") as temporary:
                source.extractall(temporary, members)
                return _add_notes(store, Path(temporary), note_ids)
    except zipfile.BadZipFile as error:
        raise ArchiveError(str(error)) from error


def _note_ids(members: list[zipfile.ZipInfo]) -> list[str]:
    """The notes of the archive, which must hold nothing but note directories."""
    note_ids = set()
    for member in members:
        path = PurePosixPath(member.filename)
        # Every entry inside a note directory: nothing absolute, nothing climbing out.
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 \
                or not NOTE_ID.fullmatch(path.parts[0]):
            raise ArchiveError(f"unexpected entry {member.filename!r}")
        if path.parts[1:] == (NOTE_FILE,):
            note_ids.add(path.parts[0])
    if not note_ids:
        raise ArchiveError("no notes in the archive")
    return sorted(note_ids)


def _add_notes(store: NoteStore, extracted: Path, note_ids: list[str]) -> tuple[list[Note], int]:
    added, skipped = [], 0
    for note_id in note_ids:
        source = extracted / note_id
        try:
            data = json.loads((source / NOTE_FILE).read_text(encoding="utf-8"))
            note = Note.from_dict({**data, "id": note_id})
        except (OSError, ValueError, KeyError, TypeError):
            continue  # not a note this version can read
        existing = store.path / note_id
        if existing.exists():
            if _same_note(existing / NOTE_FILE, note):
                skipped += 1
                continue
            note.id = uuid.uuid4().hex
        target = store.path / note.id
        shutil.move(source, target)
        # Without a repository in the archive, the note starts a history of its own.
        if not (target / ".git").is_dir():
            shutil.rmtree(target / ".git", ignore_errors=True)
        store.save(note, f'Import "{note.display_title}"')
        added.append(note)
    return added, skipped


def _same_note(file: Path, note: Note) -> bool:
    try:
        existing = Note.from_dict(json.loads(file.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return False
    return {**existing.to_dict(), "id": None} == {**note.to_dict(), "id": None}
