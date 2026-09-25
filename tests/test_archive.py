import zipfile

import pytest

from conftest import commits
from pensebete.archive import ArchiveError, export_notes, import_notes
from pensebete.storage import Note, NoteStore


@pytest.fixture
def exported(store, tmp_path):
    """An archive of two notes, one with two versions and one deleted."""
    note = Note("a", "Kept", content="v1")
    store.save(note, "Create")
    note.content = "v2"
    store.save(note, "Update")
    deleted = Note("b", "Deleted")
    store.save(deleted, "Create")
    store.trash(deleted)
    archive = tmp_path / "notes.zip"
    assert export_notes(store, archive) == 2
    return archive


def test_an_archive_brings_the_notes_back_with_their_history(exported, tmp_path):
    other = NoteStore(tmp_path / "other")

    added, skipped = import_notes(other, exported)

    assert sorted(note.id for note in added) == ["a", "b"]
    assert skipped == 0
    notes = {note.id: note for note in other.load_all()}
    assert notes["a"].content == "v2" and notes["b"].deleted
    assert [v.content for v in other.history(notes["a"])] == ["v2", "v1"]
    assert commits(other.path / "a") == ["Update", "Create"]


def test_importing_the_same_notes_again_skips_them(store, exported):
    added, skipped = import_notes(store, exported)

    assert (added, skipped) == ([], 2)
    assert len(store.load_all()) == 2


def test_a_note_that_differs_is_added_beside_the_existing_one(store, exported):
    note = next(n for n in store.load_all() if n.id == "a")
    note.content = "changed here since the export"
    store.save(note, "Update")

    added, skipped = import_notes(NoteStore(store.path), exported)

    assert skipped == 1
    [copy] = added
    assert copy.id != "a" and copy.content == "v2"
    contents = sorted(n.content for n in store.load_all() if not n.deleted)
    assert contents == ["changed here since the export", "v2"]
    assert commits(store.path / copy.id)[0] == 'Import "Kept"'


def test_the_export_leaves_no_temporary_file(store, exported, tmp_path):
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["notes.zip"]


@pytest.mark.parametrize("entry", ["../evil/note.json", "/etc/evil", "note.json",
                                   "a/../../evil"])
def test_an_archive_cannot_write_outside_the_notes(store, tmp_path, entry):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("good/note.json", '{"id": "good"}')
        output.writestr(entry, "x")

    with pytest.raises(ArchiveError):
        import_notes(store, archive)
    assert store.load_all() == []
    assert not (tmp_path / "evil").exists()


def test_a_file_that_is_not_an_archive_of_notes(store, tmp_path):
    not_zip = tmp_path / "notes.zip"
    not_zip.write_text("hello")
    with pytest.raises(ArchiveError):
        import_notes(store, not_zip)

    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as output:
        output.writestr("x/readme.txt", "no note here")
    with pytest.raises(ArchiveError):
        import_notes(store, empty)


def test_a_note_without_its_repository_starts_a_new_history(store, tmp_path):
    archive = tmp_path / "bare.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("n1/note.json", '{"id": "n1", "title": "Bare", "content": "text"}')

    [note], _ = import_notes(store, archive)

    assert commits(store.path / "n1") == ['Import "Bare"']
    assert [v.content for v in store.history(note)] == ["text"]
