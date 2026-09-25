from PySide6.QtCore import Qt
from datetime import datetime, timedelta

from pensebete.main_window import MainWindow
from pensebete.session import Session
from pensebete.storage import Note, NoteStore
from pensebete.trash import TrashDialog


def listed(window):
    return [window.list.item(row).text() for row in range(window.list.count())]


def test_creating_a_note_saves_and_opens_it(main_window, store):
    main_window.create_note()

    [note] = store.load_all()
    assert list(main_window.windows) == [note.id]
    assert main_window.session.get("recent", []) == [note.id]
    assert listed(main_window) == ["(untitled)"]


def test_the_list_follows_title_changes(main_window):
    main_window.create_note()
    note_window = next(iter(main_window.windows.values()))

    note_window.title_edit.setText("Shopping")

    assert listed(main_window) == ["Shopping"]


def test_deleting_moves_the_note_to_the_trash(main_window, store):
    main_window.create_note()
    note_window = next(iter(main_window.windows.values()))
    note_window.content_edit.setPlainText("unsaved edit")
    main_window.list.setCurrentRow(0)

    main_window.delete_selected()

    [note] = store.load_all()
    assert note.deleted is not None
    assert note.content == "unsaved edit"
    assert main_window.windows == {}
    assert listed(main_window) == []
    assert main_window.session.get("recent", None) == []


def test_a_deleted_note_can_be_restored(main_window, store):
    main_window.create_note()
    main_window.list.setCurrentRow(0)
    main_window.delete_selected()
    [note] = main_window.deleted_notes()

    main_window.restore_note(note)

    assert store.load_all()[0].deleted is None
    assert note.id in main_window.windows
    assert listed(main_window) == ["(untitled)"]


def test_the_trash_dialog_erases_a_note(main_window, store):
    main_window.create_note()
    main_window.list.setCurrentRow(0)
    main_window.delete_selected()
    dialog = TrashDialog(main_window)
    assert dialog.list.count() == 1

    dialog.erase_selected()

    assert store.load_all() == []
    assert main_window.notes == []


def test_expired_deleted_notes_are_erased(main_window, store):
    old = Note("old", deleted=(datetime.now() - timedelta(days=31)).isoformat())
    recent = Note("recent", deleted=(datetime.now() - timedelta(days=29)).isoformat())
    for note in (old, recent):
        store.save(note, "Create")
        main_window.notes.append(note)

    main_window.erase_expired()

    assert [n.id for n in store.load_all()] == ["recent"]


def test_the_retention_delay_is_taken_from_the_session(main_window, store):
    note = Note("a", deleted=(datetime.now() - timedelta(days=3)).isoformat())
    store.save(note, "Create")
    main_window.notes.append(note)
    main_window.session.set("retention_days", 2)

    main_window.erase_expired()

    assert store.load_all() == []


def test_the_session_brings_the_windows_back(qtbot, main_window, store, session, answer_yes):
    main_window.create_note()
    main_window.create_note()
    first, second = main_window.windows
    main_window.windows[second].close()
    main_window.windows[first].on_top_button.click()
    main_window.hide()
    main_window.save_session()

    from PySide6.QtNetwork import QLocalServer
    restored = MainWindow(NoteStore(store.path), Session(session.path), QLocalServer())
    restored.restore_session()

    assert list(restored.windows) == [first]
    assert restored.windows[first].on_top_button.isChecked()
    assert not restored.isVisible()
    restored.quitting = True
    restored.windows[first].discard()
    restored.close()


def test_the_list_shows_when_nothing_else_would(qtbot, store, session, answer_yes):
    from PySide6.QtNetwork import QLocalServer
    session.set("main_open", False)
    session.set("open_notes", ["gone"])
    window = MainWindow(store, session, QLocalServer())

    window.restore_session()

    assert window.isVisible()
    window.quitting = True
    window.close()


def test_quitting_saves_the_open_notes_and_the_session(main_window, store, session):
    main_window.create_note()
    note_id = next(iter(main_window.windows))
    main_window.windows[note_id].content_edit.setPlainText("before quitting")

    main_window.quit_app()

    assert store.load_all()[0].content == "before quitting"
    assert Session(session.path).get("open_notes", []) == [note_id]


def test_closing_the_list_in_the_background_keeps_the_notes_open(main_window):
    main_window.show()
    main_window.background_action.setChecked(True)
    main_window.create_note()

    main_window.close()

    assert not main_window.quitting
    assert main_window.windows
    assert main_window.session.get("main_open", True) is False


def test_a_copy_of_a_version_becomes_a_new_note(main_window, store):
    main_window.create_note()
    source = next(iter(main_window.windows.values()))
    source.title_edit.setText("Source")
    source.content_edit.setPlainText("old text")
    source.save()
    [version] = [v for v in store.history(source.note) if v.content == "old text"]

    main_window.create_note(version)

    copies = [n for n in store.load_all() if n.id != source.note.id]
    assert [(n.title, n.content) for n in copies] == [("Source", "old text")]


def add_note(window, store, note_id, title, content):
    note = Note(note_id, title, content=content, created=f"2026-01-0{len(window.notes) + 1}")
    store.save(note, "Create")
    window.notes.append(note)
    window.refresh_list()
    return note


def test_the_search_filters_titles_and_contents(main_window, store):
    add_note(main_window, store, "a", "Courses", "lait, œufs, farine")
    add_note(main_window, store, "b", "Réunion", "ordre du jour")
    add_note(main_window, store, "c", "Idées", "une réunion de famille")

    main_window.search.setText("reunion")
    assert listed(main_window) == ["Réunion", "Idées"]

    main_window.search.setText("REUNION famille")
    assert listed(main_window) == ["Idées"]

    main_window.search.setText("ŒUFS")
    assert listed(main_window) == ["Courses"]

    main_window.search.clear()
    assert listed(main_window) == ["Courses", "Réunion", "Idées"]


def test_an_open_note_is_searched_as_it_is_on_screen(main_window, store):
    add_note(main_window, store, "a", "Note", "saved text")
    main_window.open_note("a")
    main_window.windows["a"].content_edit.setPlainText("typed but not saved yet")

    main_window.search.setText("typed")

    assert listed(main_window) == ["Note"]


def test_enter_in_the_search_opens_the_first_match(main_window, store):
    add_note(main_window, store, "a", "One", "")
    add_note(main_window, store, "b", "Two", "")
    main_window.search.setText("two")

    main_window.search.returnPressed.emit()

    assert list(main_window.windows) == ["b"]


def test_a_new_note_clears_the_search(main_window, store):
    add_note(main_window, store, "a", "One", "")
    main_window.search.setText("nothing matches this")

    main_window.create_note()

    assert main_window.search.text() == ""
    assert len(listed(main_window)) == 2


def test_a_zoomed_note_keeps_its_text_size(main_window, store):
    add_note(main_window, store, "a", "Big", "")
    main_window.open_note("a")
    main_window.windows["a"].set_font_size(20)
    main_window.windows["a"].close()

    main_window.open_note("a")

    assert main_window.windows["a"].font_size == 20
    main_window.windows["a"].set_font_size(13)
    assert main_window.session.get("font_sizes", None) == {}


def test_the_list_sorts_by_creation_last_edit_or_title(main_window, store):
    add_note(main_window, store, "a", "banana", "")
    add_note(main_window, store, "b", "Apple", "")
    add_note(main_window, store, "c", "cherry", "")
    main_window.notes[0].modified = "2026-03-01T00:00:00"
    assert listed(main_window) == ["banana", "Apple", "cherry"]

    main_window._set_sort_order("modified")
    assert listed(main_window) == ["banana", "cherry", "Apple"]

    main_window._set_sort_order("title")
    assert listed(main_window) == ["Apple", "banana", "cherry"]
    assert main_window.session.get("sort", None) == "title"


def test_an_edit_moves_the_note_up_when_sorted_by_last_edit(main_window, store):
    add_note(main_window, store, "a", "Old", "")
    add_note(main_window, store, "b", "New", "")
    main_window._set_sort_order("modified")
    main_window.open_note("a")

    main_window.windows["a"].content_edit.setPlainText("edited")
    main_window.windows["a"].save()

    assert listed(main_window)[0] == "Old"


def test_export_then_import_from_the_menu(main_window, store, tmp_path, monkeypatch, qtbot):
    from PySide6.QtWidgets import QFileDialog
    from pensebete.archive import export_notes
    archive = tmp_path / "out.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(archive), "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(archive), "")))
    main_window.create_note()
    note_window = next(iter(main_window.windows.values()))
    note_window.content_edit.setPlainText("unsaved, exported anyway")

    main_window.export_archive()

    other_store = NoteStore(tmp_path / "other")
    from pensebete.archive import import_notes
    [note], _ = import_notes(other_store, archive)
    assert note.content == "unsaved, exported anyway"

    other_store.save(Note("new-one", "From elsewhere"), "Create")
    export_notes(other_store, archive)
    main_window.import_archive()
    assert "From elsewhere" in listed(main_window)


def test_ctrl_w_closes_the_list_as_alt_f4_does(qtbot, main_window):
    main_window.background_action.setChecked(True)
    with qtbot.waitActive(main_window):
        main_window.show()
        main_window.activateWindow()

    qtbot.keyClick(main_window.list, Qt.Key_W, Qt.ControlModifier)

    assert not main_window.isVisible()
    assert not main_window.quitting  # kept running in the background, as asked


def test_an_update_in_the_background_says_which_version_it_installed(main_window, monkeypatch):
    messages = []
    main_window.background_action.setChecked(True)
    main_window.hide()
    monkeypatch.setattr(main_window.tray, "showMessage", lambda *args: messages.append(args[1]))

    main_window._on_auto_updated("v1.2.0", "Notes")

    assert messages and "v1.2.0" in messages[0]
