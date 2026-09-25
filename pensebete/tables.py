"""Markdown tables as lines of text: aligning their columns, adding and removing rows and
columns, and finding a cell from a column of a line and back.

A table is a run of lines such as "| a | b |", its second line a separator such as
"| --- | :-: |". Everything works on the lines alone, so that the editor only has to
replace them.
"""

import re

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*(:?-+:?\s*)?\|?\s*$")
PIPE = re.compile(r"(?<!\\)\|")
MIN_WIDTH = 3  # what a separator cell needs: "---"


def is_table_line(text: str) -> bool:
    return bool(TABLE_ROW.match(text) or (TABLE_SEPARATOR.match(text) and "|" in text))


def is_separator(text: str) -> bool:
    return TABLE_SEPARATOR.match(text) is not None


def raw_cells(line: str) -> list[str]:
    """The cells of a line, with the spaces around their text."""
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return PIPE.split(body)


def align_table(lines: list[str], keep: tuple[int, int, int] | None = None) -> list[str]:
    """The rows of a table with their cells padded to the width of each column.

    keep is (row, column, offset) of the cursor in the cell being typed in: that cell
    keeps the spaces after its text up to the cursor, since a space just typed comes
    before the next word.
    """
    rows = []
    for index, line in enumerate(lines):
        row = []
        for column, cell in enumerate(raw_cells(line)):
            text = cell.strip()
            if keep is not None and keep[:2] == (index, column):
                typed = cell.lstrip()[:keep[2]]
                text = typed if len(typed) > len(text) else text
            row.append(text)
        rows.append(row)
    separators = [is_separator(line) for line in lines]
    columns = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (columns - len(row)))
    widths = [max([MIN_WIDTH] + [len(row[column]) for row, separator in zip(rows, separators)
                                 if not separator]) for column in range(columns)]
    indent = re.match(r"\s*", lines[0]).group()
    aligned = []
    for row, separator in zip(rows, separators):
        if separator:
            cells = [_separator_cell(cell, width) for cell, width in zip(row, widths)]
        else:
            cells = [cell.ljust(width) for cell, width in zip(row, widths)]
        aligned.append(f"{indent}| {' | '.join(cells)} |")
    return aligned


def _separator_cell(cell: str, width: int) -> str:
    left, right = cell.startswith(":"), cell.endswith(":")
    return f"{':' if left else '-'}{'-' * (width - 2)}{':' if right else '-'}"


def cell_at(line: str, column: int) -> tuple[int, int]:
    """(cell, offset in its text) at a column of a line; the offset is -1 before the
    first cell, and counts from the cell's text, past the spaces before it."""
    pipes = [match.start() for match in PIPE.finditer(line)]
    if not pipes or column <= pipes[0]:
        return 0, -1
    cell = sum(1 for pipe in pipes if pipe < column) - 1
    start = pipes[cell] + 1
    padding = len(line[start:]) - len(line[start:].lstrip(" "))
    return cell, max(column - start - padding, 0)


def cell_column(line: str, cell: int, offset: int) -> int:
    """The column of a line at an offset in a cell's text; the reverse of cell_at."""
    pipes = [match.start() for match in PIPE.finditer(line)]
    if not pipes:
        return 0
    if offset < 0:
        return pipes[0]
    cell = min(cell, len(pipes) - 2) if len(pipes) > 1 else 0
    start = pipes[cell] + 1
    end = pipes[cell + 1] if cell + 1 < len(pipes) else len(line)
    segment = line[start:end]
    if not segment.strip():  # an empty cell: after the space that follows the pipe
        return start + min(1, len(segment))
    padding = len(segment) - len(segment.lstrip(" "))
    # Within the cell, spaces kept after the text included; past it, the end of the text.
    if offset <= len(segment) - padding - 1:
        return start + padding + offset
    return start + len(segment.rstrip(" "))


def column_count(lines: list[str]) -> int:
    return max(len(raw_cells(line)) for line in lines)


def _rows(lines: list[str]) -> list[list[str]]:
    columns = column_count(lines)
    rows = [[cell.strip() for cell in raw_cells(line)] for line in lines]
    for row in rows:
        row.extend([""] * (columns - len(row)))
    return rows


def _lines(rows: list[list[str]], separators: list[bool], indent: str) -> list[str]:
    return align_table([indent + "| " + " | ".join("---" if separator and not cell else cell
                                                   for cell in row) + " |"
                        for row, separator in zip(rows, separators)])


def insert_row(lines: list[str], row: int) -> tuple[list[str], int]:
    """A new empty row below the given one, below the separator when that is the header.
    Returns the lines and the index of the new row."""
    separators = [is_separator(line) for line in lines]
    while row + 1 < len(lines) and separators[row + 1]:
        row += 1
    rows = _rows(lines)
    rows.insert(row + 1, [""] * len(rows[0]))
    separators.insert(row + 1, False)
    return _lines(rows, separators, _indent(lines)), row + 1


def insert_column(lines: list[str], column: int) -> list[str]:
    """A new empty column right of the given one."""
    separators = [is_separator(line) for line in lines]
    rows = _rows(lines)
    for row in rows:
        row.insert(column + 1, "")
    return _lines(rows, separators, _indent(lines))


def can_delete_row(lines: list[str], row: int) -> bool:
    """The header and the separator hold the table together; other rows can go."""
    return row > 0 and not is_separator(lines[row])


def delete_row(lines: list[str], row: int) -> list[str]:
    return align_table(lines[:row] + lines[row + 1:])


def can_delete_column(lines: list[str]) -> bool:
    return column_count(lines) > 1


def delete_column(lines: list[str], column: int) -> list[str]:
    separators = [is_separator(line) for line in lines]
    rows = _rows(lines)
    for row in rows:
        del row[column]
    return _lines(rows, separators, _indent(lines))


def _indent(lines: list[str]) -> str:
    return re.match(r"\s*", lines[0]).group()
