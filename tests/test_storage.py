import json
from datetime import datetime, timedelta

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
