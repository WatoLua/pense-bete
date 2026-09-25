from pensebete.diff import differences, utf16_ranges


def parts(text, ranges):
    return [text[start:start + length] for start, length in ranges]


def test_identical_texts_have_no_differences():
    assert differences("a\nb\n", "a\nb\n") == ([], [])


def test_a_changed_word_marks_that_word_only():
    old, new = "buy milk\nand bread\n", "buy oat milk\nand bread\n"
    removed, added = differences(old, new)

    assert parts(old, removed) == []
    assert [part.strip() for part in parts(new, added)] == ["oat"]


def test_added_and_removed_lines():
    old, new = "one\ntwo\nthree\n", "one\nthree\nfour\n"
    removed, added = differences(old, new)

    assert parts(old, removed) == ["two\n"]
    assert parts(new, added) == ["four\n"]


def test_a_replaced_word_is_marked_whole():
    old, new = "- confiture\n", "- café\n"
    removed, added = differences(old, new)

    assert (parts(old, removed), parts(new, added)) == (["confiture"], ["café"])


def test_from_or_to_an_empty_text():
    assert differences("", "new\n") == ([], [(0, 4)])
    assert differences("old", "") == ([(0, 3)], [])


def test_ranges_in_utf16_count_emoji_twice():
    text = "📌 pin"
    assert utf16_ranges(text, [(2, 3)]) == [(3, 3)]
    assert utf16_ranges("plain", [(1, 2)]) == [(1, 2)]
