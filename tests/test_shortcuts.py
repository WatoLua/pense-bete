import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from pensebete.session import Session
from pensebete.shortcuts import ACTIONS, BY_ID, Shortcuts, event_sequence, settings


def press(key, modifiers=Qt.NoModifier):
    return QKeyEvent(QEvent.KeyPress, key, modifiers)


def test_the_defaults_are_the_documented_keys():
    assert settings.keys("save") == ["Ctrl+S"]
    assert settings.keys("redo") == ["Ctrl+Y", "Ctrl+Shift+Z"]
    assert settings.enabled("move") and settings.is_default("move")


def test_key_presses_match_their_actions():
    assert settings.matches("undo", press(Qt.Key_Z, Qt.ControlModifier))
    assert settings.matches("table_previous", press(Qt.Key_Backtab, Qt.ShiftModifier))
    assert settings.matches("continue_list", press(Qt.Key_Enter, Qt.KeypadModifier))
    assert not settings.matches("undo", press(Qt.Key_Z))
    assert event_sequence(press(Qt.Key_Control, Qt.ControlModifier)) == ""


def test_changed_keys_are_kept_in_the_session_and_come_back(tmp_path):
    session = Session(tmp_path / "session.json")
    shortcuts = Shortcuts()
    shortcuts.attach(session)

    shortcuts.set_keys("save", ["Ctrl+Shift+S"])
    shortcuts.set_keys("clear_all", [])
    shortcuts.set_enabled("move", False)

    again = Shortcuts()
    again.attach(Session(tmp_path / "session.json"))
    assert again.keys("save") == ["Ctrl+Shift+S"]
    assert not again.enabled("clear_all")
    assert not again.enabled("move")
    assert again.keys("undo") == ["Ctrl+Z"]  # untouched: the default


def test_setting_the_default_keys_again_forgets_the_change(tmp_path):
    shortcuts = Shortcuts()
    shortcuts.attach(Session(tmp_path / "session.json"))
    shortcuts.set_keys("save", ["Ctrl+Shift+S"])

    shortcuts.set_keys("save", ["Ctrl+S"])

    assert shortcuts.is_default("save")


def test_a_key_is_taken_only_where_the_actions_meet():
    assert settings.conflict("save", "Ctrl+L") == "insert_task"  # both in a note
    assert settings.conflict("close_note", "Ctrl+F") is None  # the search is the list's
    assert settings.conflict("save", "F1") == "shortcuts"  # F1 works everywhere
    assert settings.conflict("save", "Ctrl+S") is None  # its own key


def test_reset_puts_back_one_or_every_default(tmp_path):
    shortcuts = Shortcuts()
    shortcuts.attach(Session(tmp_path / "session.json"))
    shortcuts.set_keys("save", [])
    shortcuts.set_keys("undo", [])

    shortcuts.reset("save")
    assert shortcuts.keys("save") == ["Ctrl+S"] and not shortcuts.enabled("undo")
    shortcuts.reset()
    assert all(shortcuts.is_default(action.id) for action in ACTIONS)


def test_unknown_entries_in_the_session_are_ignored(tmp_path):
    session = Session(tmp_path / "session.json")
    session.set("shortcuts", {"keys": {"gone": ["Ctrl+Q"], "move": ["Ctrl+M"]},
                              "gestures": {"save": False}})
    shortcuts = Shortcuts()
    shortcuts.attach(session)

    assert all(shortcuts.is_default(action.id) for action in ACTIONS)


def test_a_rebound_shortcut_works_at_once_and_the_old_key_no_longer(qtbot, store, answer_yes):
    from pensebete.note_window import NoteWindow
    from pensebete.storage import Note
    note = Note("a", content="text")
    store.save(note, "Create")
    window = NoteWindow(note, store)
    qtbot.addWidget(window)
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()
    window.content_edit.setFocus()
    # At the end, where the editor's own Ctrl+Delete, deleting the next word, does nothing.
    window.content_edit.moveCursor(window.content_edit.textCursor().MoveOperation.End)

    settings.set_keys("clear_all", ["Ctrl+K"])
    qtbot.keyClick(window.content_edit, Qt.Key_Delete, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == "text"
    qtbot.keyClick(window.content_edit, Qt.Key_K, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == ""

    settings.set_keys("insert_task", ["Ctrl+J"])
    qtbot.keyClick(window.content_edit, Qt.Key_J, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == "- [ ] "


def test_turned_off_undo_leaves_the_editor_keys_inert(qtbot, store, answer_yes):
    from pensebete.note_window import NoteWindow
    from pensebete.storage import Note
    note = Note("a", content="")
    store.save(note, "Create")
    window = NoteWindow(note, store)
    qtbot.addWidget(window)
    window.show()
    qtbot.keyClicks(window.content_edit, "typed")

    settings.set_keys("undo", [])
    qtbot.keyClick(window.content_edit, Qt.Key_Z, Qt.ControlModifier)

    assert window.content_edit.toPlainText() == "typed"


def test_a_turned_off_gesture_no_longer_moves_the_window(qtbot, store, answer_yes):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from pensebete.note_window import NoteWindow
    from pensebete.storage import Note
    note = Note("a")
    store.save(note, "Create")
    window = NoteWindow(note, store)
    qtbot.addWidget(window)
    window.show()
    settings.set_enabled("resize", False)

    viewport = window.content_edit.viewport()
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(10, 10),
                        QPointF(viewport.mapToGlobal(QPoint(10, 10))), Qt.RightButton,
                        Qt.RightButton, Qt.AltModifier)
    QApplication.sendEvent(viewport, event)

    assert window.resize_origin is None


def test_the_dialog_turns_a_shortcut_off_and_back_to_its_default(qtbot):
    from pensebete.about import ShortcutsDialog
    dialog = ShortcutsDialog()
    qtbot.addWidget(dialog)
    item = next(dialog.tree.topLevelItem(row) for row in range(dialog.tree.topLevelItemCount())
                if dialog.tree.topLevelItem(row).data(0, Qt.UserRole) == "save")
    dialog.tree.setCurrentItem(item)

    dialog.disable()
    assert settings.keys("save") == []
    row = [dialog.tree.topLevelItem(r) for r in range(dialog.tree.topLevelItemCount())
           if dialog.tree.topLevelItem(r).data(0, Qt.UserRole) == "save"][0]
    assert row.font(0).bold() and row.text(1) == "(off)"

    dialog.reset()
    assert settings.keys("save") == ["Ctrl+S"]


def test_the_key_dialog_refuses_a_key_already_taken(qtbot, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QMessageBox
    from pensebete.about import KeyDialog
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warnings.append(a)))
    dialog = KeyDialog("save")
    qtbot.addWidget(dialog)

    dialog.edits[0].setKeySequence(QKeySequence("Ctrl+T"))  # insert_table's
    dialog.accept()
    assert warnings and settings.keys("save") == ["Ctrl+S"]

    dialog.edits[0].setKeySequence(QKeySequence("Ctrl+Shift+S"))
    dialog.edits[1].setKeySequence(QKeySequence("F5"))
    dialog.accept()
    assert settings.keys("save") == ["Ctrl+Shift+S", "F5"]


def test_every_action_has_a_translated_description_and_section():
    from pensebete.i18n import TRANSLATIONS
    for action in ACTIONS:
        assert action.description in TRANSLATIONS and action.section in TRANSLATIONS
        if action.gesture:
            assert action.gesture in TRANSLATIONS and not action.defaults
    assert len(BY_ID) == len(ACTIONS)
