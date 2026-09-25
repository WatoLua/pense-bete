import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path

from conftest import commits
from pensebete.storage import NOTE_FILE, Note, NoteStore


def test_save_commits_the_note_in_its_own_repository(store):
    note = Note("a", "Groceries", "#ffcc80", "milk")
    store.save(note, "Create note")

    directory = store.path / "a"
    assert json.loads((directory / NOTE_FILE).read_text())["content"] == "milk"
    assert commits(directory) == ["Create note"]
    assert not (directory / "note.tmp").exists()


def test_each_note_has_a_separate_history(store):
    store.save(Note("a", content="1"), "Create a")
    store.save(Note("b", content="1"), "Create b")
    store.save(Note("b", content="2"), "Update b")

    assert commits(store.path / "a") == ["Create a"]
    assert commits(store.path / "b") == ["Update b", "Create b"]


def test_an_unchanged_note_creates_no_commit(store):
    note = Note("a", content="same")
    store.save(note, "Create note")
    store.save(note, "Update note")

    assert commits(store.path / "a") == ["Create note"]


def test_load_all_reads_back_the_notes_oldest_first(store, tmp_path):
    store.save(Note("new", "Second", created="2026-02-01T00:00:00"), "Create")
    store.save(Note("old", "First", created="2026-01-01T00:00:00"), "Create")

    notes = NoteStore(store.path).load_all()

    assert [(n.id, n.title) for n in notes] == [("old", "First"), ("new", "Second")]


def test_load_all_skips_an_unreadable_note(store):
    store.save(Note("good"), "Create")
    (store.path / "bad").mkdir()
    (store.path / "bad" / NOTE_FILE).write_text("{not json")

    assert [note.id for note in store.load_all()] == ["good"]


def test_history_lists_the_versions_newest_first(store):
    note = Note("a", "Title")
    for content in ("one", "two", "three"):
        note.content = content
        store.save(note, f"Save {content}")

    versions = store.history(note)

    assert [v.content for v in versions] == ["three", "two", "one"]
    assert all(v.title == "Title" and len(v.commit) == 40 for v in versions)


def test_history_keeps_contents_with_newlines_and_non_ascii_text(store):
    note = Note("a", content="première ligne\nseconde 📌")
    store.save(note, "Create")
    note.content = "autre"
    store.save(note, "Update")

    assert [v.content for v in store.history(note)] == ["autre", "première ligne\nseconde 📌"]


def test_trash_and_untrash_keep_the_note_and_its_history(store):
    note = Note("a", "Title", content="text")
    store.save(note, "Create")

    store.trash(note)
    assert note.deleted is not None
    assert NoteStore(store.path).load_all()[0].deleted == note.deleted

    store.untrash(note)
    assert note.deleted is None
    assert NoteStore(store.path).load_all()[0].deleted is None
    assert commits(store.path / "a") == [
        'Restore "Title" from the deleted notes', 'Delete "Title"', "Create"]


def test_erase_removes_the_note_and_its_repository(store):
    note = Note("a")
    store.save(note, "Create")

    store.erase(note)

    assert not (store.path / "a").exists()
    assert store.load_all() == []


def test_days_in_trash():
    note = Note("a", deleted=(datetime.now() - timedelta(days=3, hours=1)).isoformat())

    assert note.days_in_trash() == 3
    assert Note("b").days_in_trash() == 0


def test_to_dict_leaves_out_deleted_until_set():
    assert "deleted" not in Note("a").to_dict()
    note = Note.from_dict({"id": "a", "deleted": "2026-01-01T00:00:00"})
    assert note.to_dict()["deleted"] == "2026-01-01T00:00:00"


def test_display_title_falls_back_for_a_blank_title():
    assert Note("a", "  ").display_title == "(untitled)"
    assert Note("a", " Hi ").display_title == "Hi"


def test_erase_removes_read_only_files_too(store):
    import os
    import stat
    note = Note("a")
    store.save(note, "Create")
    for file in (store.path / "a" / ".git" / "objects").rglob("*"):
        if file.is_file():
            os.chmod(file, stat.S_IREAD)

    store.erase(note)

    assert not (store.path / "a").exists()


def test_without_versioning_notes_are_saved_alone(tmp_path):
    store = NoteStore(tmp_path / "notes", versioning=False)
    note = Note("a", content="text")

    store.save(note, "Create")

    assert (store.path / "a" / NOTE_FILE).is_file()
    assert not (store.path / "a" / ".git").exists()
    assert store.history(note) == []
    assert NoteStore(store.path, versioning=False).load_all()[0].content == "text"


def test_versioning_back_on_starts_a_note_history_from_its_text(tmp_path):
    store = NoteStore(tmp_path / "notes", versioning=False)
    note = Note("a", content="written without git")
    store.save(note, "Create")

    store.versioning = True
    note.content = "then with git"
    store.save(note, "Update")

    assert commits(store.path / "a") == ["Update"]
    assert [v.content for v in store.history(note)] == ["then with git"]


def test_versioning_off_keeps_the_existing_history(store):
    note = Note("a", content="v1")
    store.save(note, "Create")

    store.versioning = False
    note.content = "v2"
    store.save(note, "Update")
    store.versioning = True

    assert commits(store.path / "a") == ["Create"]
    assert store.load_all()[0].content == "v2"


def test_moving_the_notes_takes_their_history_and_leaves_the_rest(store, tmp_path):
    from pensebete.storage import move_notes, NoteStore
    note = Note("a", "Title", content="one")
    store.save(note, "Create")
    note.content = "two"
    store.save(note, "Update")
    (store.path / "unrelated.txt").write_text("mine")
    target = tmp_path / "elsewhere" / "notes"

    move_notes(store.path, target)

    moved = NoteStore(target)
    assert [n.content for n in moved.load_all()] == ["two"]
    assert len(moved.history(moved.load_all()[0])) == 2
    assert not (store.path / "a").exists()
    assert (store.path / "unrelated.txt").read_text() == "mine"


def test_the_emptied_folder_goes(store, tmp_path):
    from pensebete.storage import move_notes
    store.save(Note("a", "Title"), "Create")

    move_notes(store.path, tmp_path / "new")

    assert not store.path.exists()


def test_a_move_cut_short_leaves_the_notes_where_they_were(store, tmp_path, monkeypatch):
    import shutil
    from pensebete import storage
    for note_id in ("a", "b"):
        store.save(Note(note_id, note_id), "Create")
    copy = shutil.copytree

    def fail_on_the_second(source, target, *args, **options):
        if Path(source).name == "b":  # copytree calls itself for the directories inside
            copy(Path(source) / ".git", Path(target) / ".git")  # partly copied
            raise OSError("disk full")
        return copy(source, target, *args, **options)
    monkeypatch.setattr(storage.shutil, "copytree", fail_on_the_second)
    target = tmp_path / "new"

    with pytest.raises(OSError, match="disk full"):
        storage.move_notes(store.path, target)

    assert sorted(n.id for n in store.load_all()) == ["a", "b"]
    assert list(target.iterdir()) == []


def test_a_move_into_the_folder_itself_or_onto_a_note_is_refused(store, tmp_path):
    from pensebete.storage import move_notes
    store.save(Note("a", "Title"), "Create")
    (tmp_path / "taken" / "a").mkdir(parents=True)

    with pytest.raises(OSError):
        move_notes(store.path, store.path / "inside")
    with pytest.raises(FileExistsError):
        move_notes(store.path, tmp_path / "taken")
    assert (store.path / "a" / "note.json").exists()
