import pytest

from pensebete import tables

TABLE = ["| Day | Who |", "| --- | --- |", "| Mon | Ann |"]


def test_align_keeps_the_trailing_space_of_the_cell_being_typed_in():
    lines = ["| a | b |", "|-|-|", "| Ann  | x |"]

    assert tables.align_table(lines, keep=(2, 0, 4))[2] == "| Ann  | x   |"
    assert tables.align_table(lines, keep=(2, 0, 3))[2] == "| Ann | x   |"
    assert tables.align_table(lines)[2] == "| Ann | x   |"


@pytest.mark.parametrize("column, expected", [
    (0, (0, -1)),   # on the first pipe
    (1, (0, 0)),    # in the padding before "Day"
    (4, (0, 2)),    # between "Da" and "y"
    (8, (1, 0)),    # right after the second pipe
    (10, (1, 2)),
    (11, (1, 3)),   # after "Who"
])
def test_cell_at(column, expected):
    assert tables.cell_at("| Day | Who |", column) == expected


def test_cell_column_is_the_reverse_of_cell_at_and_stays_in_the_cell():
    line = "| Day   | Who |"
    assert tables.cell_column(line, 0, 2) == 4
    assert tables.cell_column(line, 1, 0) == 10
    assert tables.cell_column(line, 0, 99) == 5  # the end of "Day", not the padding
    assert tables.cell_column(line, 5, 0) == 10  # past the last cell: the last one
    assert tables.cell_column("| a |     |", 1, 5) == 6  # an empty cell


def test_insert_a_row_below_a_row_or_the_header():
    lines, row = tables.insert_row(TABLE, 2)
    assert (lines[3], row) == ("|     |     |", 3)

    lines, row = tables.insert_row(TABLE, 0)
    assert (lines[2], row) == ("|     |     |", 2)
    assert lines[1] == "| --- | --- |"


def test_insert_a_column():
    assert tables.insert_column(TABLE, 0) == [
        "| Day |     | Who |",
        "| --- | --- | --- |",
        "| Mon |     | Ann |",
    ]


def test_delete_a_row_or_a_column():
    assert tables.delete_row(TABLE, 2) == TABLE[:2]
    assert tables.delete_column(TABLE, 0) == ["| Who |", "| --- |", "| Ann |"]
    assert not tables.can_delete_row(TABLE, 0) and not tables.can_delete_row(TABLE, 1)
    assert tables.can_delete_row(TABLE, 2)
    assert not tables.can_delete_column(["| a |", "| - |"])


def test_escaped_pipes_stay_in_their_cell():
    assert tables.align_table(["| a \\| b | c |", "|-|-|"]) == [
        "| a \\| b | c   |", "| ------ | --- |"]
