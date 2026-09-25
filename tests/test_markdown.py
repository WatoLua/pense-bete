import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QFont, QKeyEvent, QMouseEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication

from conftest import commits
from pensebete.markdown import continued_item
from pensebete.tables import align_table
from pensebete.note_window import NoteWindow
from pensebete.storage import Note


@pytest.fixture
def window(qtbot, store, answer_yes):
    note = Note("a", "Title", content="# Heading\nsome **bold** text\n- [ ] task\n- [x] failed\n- [v] passed")
    store.save(note, "Create note")
    window = NoteWindow(note, store)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def char_format(window, line, column):
    block = window.content_edit.document().findBlockByNumber(line)
    for format_range in block.layout().formats():
        if format_range.start <= column < format_range.start + format_range.length:
            return QTextCharFormat(format_range.format)
    return None


def click(window, line, column):
    editor = window.content_edit
    cursor = QTextCursor(editor.document().findBlockByNumber(line))
    cursor.movePosition(QTextCursor.Right, n=column)
    point = editor.cursorRect(cursor).center() + QPoint(2, 0)
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(editor.viewport(), QMouseEvent(
            kind, QPointF(point), QPointF(editor.viewport().mapToGlobal(point)),
            Qt.LeftButton, Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton,
            Qt.NoModifier))


def press_enter(window):
    QApplication.sendEvent(window.content_edit,
                           QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))


def end_of_line(window, line):
    cursor = QTextCursor(window.content_edit.document().findBlockByNumber(line))
    cursor.movePosition(QTextCursor.EndOfBlock)
    window.content_edit.setTextCursor(cursor)


def test_plain_text_is_the_default_and_shows_no_formatting(window):
    assert not window.markdown
    assert char_format(window, 1, 8) is None


def test_markdown_is_formatted_without_changing_the_text(qtbot, window, store):
    text = window.content_edit.toPlainText()

    window.set_markdown(True)
    qtbot.wait(20)

    assert char_format(window, 1, 8).fontWeight() == QFont.Bold  # "bold"
    assert char_format(window, 3, 3).foreground().color().name() == "#c62828"  # ko, in red
    assert char_format(window, 4, 3).foreground().color().name() == "#2e7d32"  # ok, in green
    assert char_format(window, 2, 3).foreground().color().name() != "#2e7d32"  # to do
    assert char_format(window, 4, 8).fontStrikeOut()  # an ok task is struck through
    ko_text = char_format(window, 3, 8)
    assert ko_text is None or not ko_text.fontStrikeOut()  # a ko task is not
    assert char_format(window, 0, 3).font().pixelSize() > 13  # the heading
    assert window.content_edit.toPlainText() == text
    assert not window.dirty
    window.close()
    assert commits(store.path / "a") == ["Create note"]


def test_a_click_on_a_box_turns_it_ok_then_ko_then_to_do(window):
    window.set_markdown(True)

    for expected in ("- [v] task", "- [x] task", "- [ ] task"):
        click(window, 2, 3)
        assert window.content_edit.toPlainText().splitlines()[2] == expected
    assert window.dirty

    window.content_edit.undo()
    assert window.content_edit.toPlainText().splitlines()[2] == "- [x] task"


def test_checkboxes_do_not_toggle_in_plain_text(window):
    click(window, 2, 3)

    assert window.content_edit.toPlainText().splitlines()[2] == "- [ ] task"


def test_enter_continues_a_task_list_and_an_empty_item_ends_it(window):
    window.set_markdown(True)
    end_of_line(window, 4)

    press_enter(window)
    assert window.content_edit.toPlainText().endswith("- [v] passed\n- [ ] ")
    press_enter(window)
    assert window.content_edit.toPlainText().endswith("- [v] passed\n")


def test_a_table_is_aligned_once_the_cursor_leaves_it(window):
    window.set_markdown(True)
    window.content_edit.setPlainText("| a | long header |\n|-|-|\n| wide cell | b |\nafter")
    end_of_line(window, 2)
    assert window.content_edit.toPlainText().startswith("| a | long")  # not while in it

    end_of_line(window, 3)

    assert window.content_edit.toPlainText().splitlines() == [
        "| a         | long header |",
        "| --------- | ----------- |",
        "| wide cell | b           |",
        "after",
    ]


def test_align_table_keeps_the_alignment_colons_and_fills_missing_cells():
    assert align_table(["|x|y|z|", "|:-|:-:|-:|", "|1|2|"]) == [
        "| x   | y   | z   |",
        "| :-- | :-: | --: |",
        "| 1   | 2   |     |",
    ]


@pytest.mark.parametrize("line, prefix", [
    ("- item", "- "),
    ("  * nested", "  * "),
    ("3. third", "4. "),
    ("- [x] done", "- [ ] "),
    ("- [v] ok", "- [ ] "),
    ("- ", ""),
    ("plain text", None),
])
def test_continued_item(line, prefix):
    assert continued_item(line) == prefix


def test_the_option_applies_to_open_and_new_windows(main_window):
    main_window.create_note()
    first = next(iter(main_window.windows.values()))

    main_window.markdown_action.setChecked(True)
    assert first.markdown
    main_window.create_note()
    assert all(window.markdown for window in main_window.windows.values())
    assert main_window.session.get("markdown", False) is True


@pytest.fixture
def table_window(window, qtbot):
    window.set_markdown(True)
    window.markdown_editing.align_timer.setInterval(50)
    window.content_edit.setPlainText("| Day | Who |\n| --- | --- |\n| Mon | Ann |\nafter")
    return window


def put_cursor(window, line, column):
    cursor = QTextCursor(window.content_edit.document().findBlockByNumber(line))
    cursor.movePosition(QTextCursor.Right, n=column)
    window.content_edit.setTextCursor(cursor)


def lines(window):
    return window.content_edit.toPlainText().splitlines()


def cursor_place(window):
    cursor = window.content_edit.textCursor()
    return cursor.blockNumber(), cursor.positionInBlock()


def key(window, key, modifiers=Qt.NoModifier):
    QApplication.sendEvent(window.content_edit, QKeyEvent(QEvent.KeyPress, key, modifiers))


def test_a_table_being_typed_in_is_aligned_once_the_typing_pauses(qtbot, table_window):
    put_cursor(table_window, 2, 11)  # after "Ann"
    table_window.content_edit.insertPlainText("abelle")

    qtbot.waitUntil(lambda: lines(table_window)[0] == "| Day | Who       |", timeout=2000)
    assert lines(table_window)[2] == "| Mon | Annabelle |"
    assert cursor_place(table_window) == (2, 17)  # still after what was typed


def test_a_space_just_typed_survives_the_alignment(qtbot, table_window):
    put_cursor(table_window, 2, 11)
    table_window.content_edit.insertPlainText("abelle ")

    qtbot.waitUntil(lambda: lines(table_window)[1] == "| --- | ---------- |", timeout=2000)
    table_window.content_edit.insertPlainText("B.")
    assert lines(table_window)[2].startswith("| Mon | Annabelle B.")


def test_undo_takes_back_the_typing_and_the_alignment_together(qtbot, table_window):
    put_cursor(table_window, 2, 11)
    table_window.content_edit.insertPlainText("abelle")
    qtbot.waitUntil(lambda: lines(table_window)[2] == "| Mon | Annabelle |", timeout=2000)

    table_window.content_edit.undo()

    assert lines(table_window)[:3] == ["| Day | Who |", "| --- | --- |", "| Mon | Ann |"]


def test_ctrl_enter_adds_a_row_and_ctrl_shift_enter_a_column(table_window):
    put_cursor(table_window, 2, 3)

    key(table_window, Qt.Key_Return, Qt.ControlModifier)
    assert lines(table_window)[3] == "|     |     |"
    assert cursor_place(table_window) == (3, 2)

    key(table_window, Qt.Key_Return, Qt.ControlModifier | Qt.ShiftModifier)
    assert lines(table_window)[0] == "| Day |     | Who |"
    assert cursor_place(table_window)[0] == 3
    assert lines(table_window)[-1] == "after"


def test_tab_moves_through_the_cells_and_adds_a_row_after_the_last(table_window):
    put_cursor(table_window, 0, 3)

    key(table_window, Qt.Key_Tab)
    assert cursor_place(table_window) == (0, 11)  # end of "Who"
    key(table_window, Qt.Key_Tab)
    assert cursor_place(table_window) == (2, 5)  # past the separator, end of "Mon"
    key(table_window, Qt.Key_Backtab)
    assert cursor_place(table_window) == (0, 11)
    put_cursor(table_window, 2, 8)
    key(table_window, Qt.Key_Tab)
    assert lines(table_window)[3] == "|     |     |"
    assert cursor_place(table_window) == (3, 2)


def test_tab_outside_a_table_types_a_tab(table_window):
    put_cursor(table_window, 3, 5)
    QApplication.sendEvent(table_window.content_edit,
                           QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier, "\t"))

    assert lines(table_window)[3] == "after\t"


def test_the_menu_actions_delete_rows_and_columns(table_window):
    editing = table_window.markdown_editing
    put_cursor(table_window, 0, 3)
    assert not editing.can_delete_row()

    put_cursor(table_window, 2, 8)
    assert editing.can_delete_row()
    editing.delete_column()
    assert lines(table_window)[:3] == ["| Day |", "| --- |", "| Mon |"]
    editing.delete_row()
    assert lines(table_window) == ["| Day |", "| --- |", "after"]
    assert not editing.can_delete_column()


def test_ctrl_backspace_deletes_the_row_and_ctrl_shift_backspace_the_column(table_window):
    put_cursor(table_window, 0, 3)
    key(table_window, Qt.Key_Backspace, Qt.ControlModifier)
    assert lines(table_window)[0] == "| Day | Who |"  # not the header

    put_cursor(table_window, 2, 3)
    key(table_window, Qt.Key_Backspace, Qt.ControlModifier | Qt.ShiftModifier)
    assert lines(table_window)[:3] == ["| Who |", "| --- |", "| Ann |"]
    key(table_window, Qt.Key_Backspace, Qt.ControlModifier)
    assert lines(table_window) == ["| Who |", "| --- |", "after"]
    key(table_window, Qt.Key_Backspace, Qt.ControlModifier | Qt.ShiftModifier)
    assert lines(table_window)[0] == "| Who |"  # the last column stays
