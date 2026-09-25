import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from pensebete.formatting import format, toggle_inline, toggle_lines


@pytest.mark.parametrize("line, start, end, kind, expected", [
    ("hello world", 0, 5, "bold", ("**hello** world", 2, 7)),
    ("**hello** world", 2, 7, "bold", ("hello world", 0, 5)),  # markers around
    ("**hello** world", 0, 9, "bold", ("hello world", 0, 5)),  # markers selected
    ("**hello** world", 4, 4, "bold", ("hello world", 2, 2)),  # cursor inside
    ("ab", 1, 1, "bold", ("a****b", 3, 3)),  # no selection: a pair to type in
    ("a****b", 3, 3, "bold", ("ab", 1, 1)),  # and again, gone
    ("***t***", 3, 4, "italic", ("**t**", 2, 3)),  # bold stays
    ("***t***", 3, 4, "bold", ("*t*", 1, 2)),  # italic stays
    ("*t*", 1, 2, "bold", ("***t***", 3, 4)),
    ("**t**", 2, 3, "italic", ("***t***", 3, 4)),  # bold is not italic
    ("x ~~y~~", 4, 5, "strike", ("x y", 2, 3)),
    ("a `c` b", 3, 4, "code", ("a c b", 2, 3)),
    (" hi ", 0, 4, "italic", (" *hi* ", 2, 4)),  # markers touch the text
    ("_hi_", 1, 3, "italic", ("hi", 0, 2)),  # the other markers count too
])
def test_inline_formats_toggle(line, start, end, kind, expected):
    assert toggle_inline([(line, start, end)], kind) == [expected]


def test_inline_formats_over_lines_wrap_each_and_go_once_all_have_them():
    wrapped = toggle_inline([("one", 1, 3), ("", 0, 0), ("two", 0, 3)], "italic")
    assert wrapped == [("o*ne*", 2, 4), ("", 0, 0), ("*two*", 1, 4)]

    partly = toggle_inline([("*one*", 1, 4), ("two", 0, 3)], "italic")
    assert partly == [("*one*", 1, 4), ("*two*", 1, 4)]  # the other one only

    unwrapped = toggle_inline([("o*ne*", 2, 4), ("", 0, 0), ("*two*", 1, 4)], "italic")
    assert [text for text, _, _ in unwrapped] == ["one", "", "two"]


@pytest.mark.parametrize("lines, kind, expected", [
    (["a", "b"], "heading2", ["## a", "## b"]),
    (["## a", "## b"], "heading2", ["a", "b"]),
    (["# a"], "heading2", ["## a"]),  # another level is replaced
    (["a", "> b"], "quote", ["> a", "> b"]),
    (["> a", ">> b"], "quote", ["a", "> b"]),  # one level at a time
    (["  a", "1. b"], "bullet", ["  - a", "- b"]),
    (["- a", "* b"], "bullet", ["a", "b"]),
    (["a", "", "b"], "quote", ["> a", "", "> b"]),  # empty lines between stay
])
def test_line_formats_toggle(lines, kind, expected):
    assert [text for text, _, _ in toggle_lines(lines, kind)] == expected


@pytest.fixture
def editor(qtbot):
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    return editor


def select(editor, start, end):
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)


def test_the_editor_s_selection_is_formatted_and_kept(editor):
    editor.setPlainText("say hello")
    select(editor, 4, 9)

    format(editor, "bold")

    assert editor.toPlainText() == "say **hello**"
    assert editor.textCursor().selectedText() == "hello"
    format(editor, "bold")
    assert editor.toPlainText() == "say hello"
    assert editor.textCursor().selectedText() == "hello"


def test_a_format_is_one_step_that_undo_takes_back(editor):
    editor.setPlainText("one\ntwo")
    select(editor, 0, 7)

    format(editor, "heading1")
    assert editor.toPlainText() == "# one\n# two"

    editor.undo()
    assert editor.toPlainText() == "one\ntwo"


def test_a_selection_ending_at_the_start_of_a_line_leaves_it_out(editor):
    editor.setPlainText("one\ntwo")
    select(editor, 0, 4)

    format(editor, "quote")

    assert editor.toPlainText() == "> one\ntwo"


def test_characters_beyond_utf16_keep_the_cursor_in_place(editor):
    editor.setPlainText("😀 word")
    select(editor, 3, 7)  # "word": the emoji takes two units

    format(editor, "italic")

    assert editor.toPlainText() == "😀 *word*"
    assert editor.textCursor().selectedText() == "word"


def test_the_formatting_keys_work_in_the_note_only(qtbot, store, answer_yes):
    from pensebete.note_window import NoteWindow
    from pensebete.storage import Note
    window = NoteWindow(Note("a", "Title", content="word"), store)
    qtbot.addWidget(window)
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()
    window.content_edit.setFocus()
    window.content_edit.selectAll()

    qtbot.keyClick(window.content_edit, Qt.Key_B, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == "**word**"
    qtbot.keyClick(window.content_edit, Qt.Key_B, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == "word"

    window.title_edit.setFocus()
    qtbot.keyClick(window.title_edit, Qt.Key_B, Qt.ControlModifier)
    assert window.content_edit.toPlainText() == "word"
