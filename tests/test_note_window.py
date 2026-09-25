import pytest

from conftest import commits
from pensebete.note_window import NoteWindow
from pensebete.storage import Note


@pytest.fixture
def window(qtbot, store, answer_yes):
    note = Note("a", "Title", content="first")
    store.save(note, "Create note")
    window = NoteWindow(note, store)
    qtbot.addWidget(window)
    return window


def test_a_change_is_saved_once_the_editing_pauses(qtbot, window, store):
    window.timer.setInterval(50)
    window.content_edit.setPlainText("second")
    assert window.dirty

    qtbot.waitUntil(lambda: not window.dirty, timeout=2000)

    assert commits(store.path / "a") == ['Update "Title"', "Create note"]
    assert store.load_all()[0].content == "second"


def test_each_change_delays_the_save(qtbot, window, store):
    window.timer.setInterval(300)
    window.content_edit.setPlainText("x")
    qtbot.wait(200)
    window.content_edit.setPlainText("xy")
    qtbot.wait(200)

    assert window.dirty
    qtbot.waitUntil(lambda: not window.dirty, timeout=2000)
    assert len(commits(store.path / "a")) == 2


def test_closing_saves_at_once(window, store):
    window.show()
    window.content_edit.setPlainText("typed just before closing")

    window.close()

    assert store.load_all()[0].content == "typed just before closing"


def test_nothing_is_committed_without_a_change(window, store):
    window.save()
    window.close()

    assert commits(store.path / "a") == ["Create note"]


def test_title_and_color_changes_are_saved(window, store):
    changes = []
    window.changed.connect(changes.append)

    window.title_edit.setText("Renamed")
    window.set_color("#b3e5fc")
    window.save()

    note = store.load_all()[0]
    assert (note.title, note.color) == ("Renamed", "#b3e5fc")
    assert window.windowTitle() == "Renamed"
    assert len(changes) == 2


def test_a_discarded_window_does_not_save(window, store):
    window.show()
    window.content_edit.setPlainText("never saved")

    window.discard()

    assert store.load_all()[0].content == "first"


def test_the_history_opens_on_the_previous_version(window):
    window.show()
    window.content_edit.setPlainText("second")

    window.history_button.setChecked(True)

    panel = window.history
    assert [v.content for v in panel.versions] == ["second", "first"]
    assert panel.current().content == "first"
    assert panel.content.toPlainText() == "first"
    assert not panel.newer_button.isEnabled() is False
    assert not panel.older_button.isEnabled()


def test_the_arrows_browse_the_versions(window):
    window.show()
    for content in ("2", "3"):
        window.content_edit.setPlainText(content)
        window.save()
    window.history_button.setChecked(True)
    panel = window.history

    panel.older_button.click()
    assert panel.current().content == "first"
    assert panel.position.text() == "1 / 3"
    panel.newer_button.click()
    panel.newer_button.click()
    assert panel.current().content == "3"
    assert not panel.restore_button.isEnabled()  # the current version


def test_restoring_a_version_keeps_the_replaced_text_in_history(window, store):
    window.show()
    window.content_edit.setPlainText("second")
    window.history_button.setChecked(True)

    window.restore_version(window.history.current())

    assert window.content_edit.toPlainText() == "first"
    assert [v.content for v in store.history(window.note)] == ["first", "second", "first"]
    assert commits(store.path / "a")[0].startswith('Restore "Title" from ')


def test_the_history_does_not_widen_the_stored_geometry(qtbot, window):
    window.show()
    qtbot.waitExposed(window)
    before = window.saveGeometry()
    width = window.width()

    window.history_button.setChecked(True)
    qtbot.wait(50)
    assert window.width() >= width * 2
    assert window.session_geometry() == before

    window.history_button.setChecked(False)
    qtbot.wait(50)
    assert window.width() == width
    assert not window.history_open


def test_keeping_on_top_sets_the_window_flag(window):
    from PySide6.QtCore import Qt
    toggled = []
    window.on_top_changed.connect(toggled.append)
    window.show()

    window.on_top_button.click()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    assert window.isVisible()

    window.on_top_button.click()
    assert not window.windowFlags() & Qt.WindowStaysOnTopHint
    assert toggled == [window, window]
