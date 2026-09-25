import pytest
from PySide6.QtCore import Qt

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
    assert len(changes) == 3  # the title, the color, then the save for the last edit
    assert note.modified is not None


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


def highlighted(editor):
    return [selection.cursor.selectedText() for selection in editor.extraSelections()]


def test_the_history_highlights_what_changed_since_the_version_shown(qtbot, window):
    window.show()
    window.content_edit.setPlainText("first line\nsecond")
    window.history_button.setChecked(True)

    assert window.history.current().content == "first"
    assert highlighted(window.history.content) == []
    # Qt separates the paragraphs of a selection with U+2029.
    assert highlighted(window.content_edit) == [" line\u2029second"]
    assert window.content_edit.toPlainText() == "first line\nsecond"  # the text is untouched


def test_the_highlights_follow_the_typing_and_go_with_the_history(qtbot, window):
    window.show()
    window.history_button.setChecked(True)
    window.content_edit.setPlainText("first draft")

    qtbot.waitUntil(lambda: highlighted(window.content_edit) == [" draft"], timeout=2000)

    window.history_button.setChecked(False)
    assert window.content_edit.extraSelections() == []


def test_ctrl_and_the_wheel_zoom_the_text(qtbot, window):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    zoomed = []
    window.font_size_changed.connect(zoomed.append)
    window.show()

    def wheel(delta, modifiers):
        viewport = window.content_edit.viewport()
        QApplication.sendEvent(viewport, QWheelEvent(
            QPointF(10, 10), QPointF(viewport.mapToGlobal(QPoint(10, 10))), QPoint(),
            QPoint(0, delta), Qt.NoButton, modifiers, Qt.NoScrollPhase, False))

    wheel(120, Qt.ControlModifier)
    wheel(120, Qt.ControlModifier)
    assert window.font_size == 15
    wheel(-120, Qt.ControlModifier)
    assert window.font_size == 14
    wheel(120, Qt.NoModifier)  # scrolls, as usual
    assert window.font_size == 14
    assert "font-size: 14px" in window.styleSheet()
    assert len(zoomed) == 3


def test_the_text_size_stays_within_bounds(window):
    window.set_font_size(100)
    assert window.font_size == 40
    window.set_font_size(1)
    assert window.font_size == 8


@pytest.fixture
def focused(qtbot, window):
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()
    window.content_edit.setFocus()
    window.content_edit.moveCursor(window.content_edit.textCursor().MoveOperation.End)
    return window


def test_ctrl_t_inserts_a_table_with_its_first_header_selected(qtbot, focused):
    qtbot.keyClick(focused.content_edit, Qt.Key_T, Qt.ControlModifier)

    text = focused.content_edit.toPlainText().splitlines()
    assert text[0] == "first"
    assert text[1].startswith("| Column 1 | Column 2 |")
    assert focused.content_edit.textCursor().selectedText() == "Column 1"


def test_ctrl_l_inserts_a_task(qtbot, focused):
    qtbot.keyClick(focused.content_edit, Qt.Key_L, Qt.ControlModifier)

    assert focused.content_edit.toPlainText() == "first\n- [ ] "


def test_ctrl_shift_c_copies_the_whole_note(qtbot, focused):
    from PySide6.QtWidgets import QApplication
    focused.content_edit.setPlainText("line one\nline two")
    focused.title_edit.setFocus()  # from anywhere in the window

    qtbot.keyClick(focused.title_edit, Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)

    assert QApplication.clipboard().text() == "line one\nline two"


def test_ctrl_delete_clears_the_note_and_undo_brings_it_back(qtbot, focused):
    focused.content_edit.setPlainText("line one\nline two")

    qtbot.keyClick(focused.content_edit, Qt.Key_Delete, Qt.ControlModifier)
    assert focused.content_edit.toPlainText() == ""
    assert focused.dirty

    focused.content_edit.undo()
    assert focused.content_edit.toPlainText() == "line one\nline two"


def test_ctrl_s_saves_at_once(qtbot, focused, store):
    qtbot.keyClicks(focused.content_edit, " edited")

    qtbot.keyClick(focused.content_edit, Qt.Key_S, Qt.ControlModifier)

    assert not focused.dirty
    assert store.load_all()[0].content == "first edited"


def test_ctrl_w_closes_the_note_after_saving_it(qtbot, focused, store):
    closed = []
    focused.closing.connect(closed.append)
    qtbot.keyClicks(focused.content_edit, " edited")

    qtbot.keyClick(focused.content_edit, Qt.Key_W, Qt.ControlModifier)

    assert closed == [focused]
    assert store.load_all()[0].content == "first edited"


def test_resized_moves_only_the_dragged_edges_and_keeps_the_minimum():
    from PySide6.QtCore import QRect, QSize
    from pensebete.note_window import resized
    start, minimum = QRect(100, 100, 300, 200), QSize(150, 100)

    assert resized(start, Qt.RightEdge | Qt.BottomEdge, 50, 20, minimum) == QRect(100, 100, 350, 220)
    assert resized(start, Qt.LeftEdge | Qt.TopEdge, 50, 20, minimum) == QRect(150, 120, 250, 180)
    assert resized(start, Qt.RightEdge | Qt.BottomEdge, -500, -500, minimum) == QRect(100, 100, 150, 100)
    assert resized(start, Qt.LeftEdge | Qt.TopEdge, 500, 500, minimum) == QRect(250, 200, 150, 100)
    assert resized(start, Qt.Edge(0), 10, -5, minimum) == QRect(110, 95, 300, 200)


def mouse(widget, kind, button, local, modifiers=Qt.AltModifier):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
    event = QMouseEvent(kind, QPointF(local), QPointF(widget.mapToGlobal(local)),
                        button if kind != QEvent.MouseMove else Qt.NoButton, buttons, modifiers)
    return QApplication.sendEvent(widget, event), event


def test_alt_and_the_right_button_resize_from_the_nearest_corner(qtbot, window):
    from PySide6.QtCore import QEvent, QPoint
    window.show()
    qtbot.waitExposed(window)
    window.setGeometry(100, 100, 400, 300)
    viewport = window.content_edit.viewport()
    right_edge = window.geometry().right()
    # Near the bottom right corner: that corner follows the mouse, the top left stays.
    press = viewport.mapFrom(window, QPoint(390, 290))

    mouse(viewport, QEvent.MouseButtonPress, Qt.RightButton, press)
    mouse(viewport, QEvent.MouseMove, Qt.RightButton, press + QPoint(60, 40))
    assert (window.width(), window.height()) == (460, 340)
    assert window.geometry().topLeft() == QPoint(100, 100)
    mouse(viewport, QEvent.MouseMove, Qt.RightButton, press + QPoint(-30, -10))
    assert (window.width(), window.height()) == (370, 290)
    mouse(viewport, QEvent.MouseButtonRelease, Qt.RightButton, press + QPoint(-30, -10))
    assert window.geometry().right() != right_edge

    # The context menu that follows a right click is not shown after a resize.
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication
    shown = []
    window.content_edit.customContextMenuRequested.disconnect()
    window.content_edit.customContextMenuRequested.connect(shown.append)
    QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Mouse, press, viewport.mapToGlobal(press)))
    assert shown == []


def test_alt_and_the_left_button_move_the_window(qtbot, window):
    from PySide6.QtCore import QEvent, QPoint
    window.show()
    qtbot.waitExposed(window)
    window.setGeometry(100, 100, 400, 300)
    viewport = window.content_edit.viewport()
    text = window.content_edit.toPlainText()

    mouse(viewport, QEvent.MouseButtonPress, Qt.LeftButton, QPoint(50, 50))
    # Where the window manager does not move it, as offscreen, the window moves itself.
    mouse(viewport, QEvent.MouseMove, Qt.LeftButton, QPoint(80, 70))
    mouse(viewport, QEvent.MouseButtonRelease, Qt.LeftButton, QPoint(80, 70))

    assert window.geometry().topLeft() == QPoint(130, 120)
    assert window.size().width() == 400
    assert window.content_edit.toPlainText() == text


def test_without_alt_the_mouse_edits_as_usual(qtbot, window):
    from PySide6.QtCore import QEvent, QPoint
    window.show()
    qtbot.waitExposed(window)
    geometry = window.geometry()

    handled, _ = mouse(window.content_edit.viewport(), QEvent.MouseButtonPress, Qt.RightButton,
                       QPoint(10, 10), Qt.NoModifier)

    assert window.geometry() == geometry
    assert window.resize_origin is None


def test_ctrl_t_selects_the_header_even_when_the_window_wraps_it(qtbot, focused):
    focused.resize(200, 300)  # "| Column 1 | Column 2 |" no longer fits on one line

    qtbot.keyClick(focused.content_edit, Qt.Key_T, Qt.ControlModifier)

    assert focused.content_edit.textCursor().selectedText() == "Column 1"
