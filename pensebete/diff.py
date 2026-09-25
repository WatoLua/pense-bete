"""What changed between two versions of a note's text."""

import re
from difflib import SequenceMatcher

# Beyond this many characters, a changed block is marked as a whole: comparing it
# word by word would take too long for the interface.
DETAILED_BLOCK_LIMIT = 5000

Range = tuple[int, int]  # (start, length), in characters


def differences(old: str, new: str) -> tuple[list[Range], list[Range]]:
    """The parts of old that new lacks, and the parts of new that old lacks.

    Lines are compared first, so that unchanged lines never match by chance; the
    words of changed lines are then compared, so that a word changed in a line marks
    that word rather than the whole line, and never only the letters that differ.
    """
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    old_starts, new_starts = _line_starts(old_lines), _line_starts(new_lines)
    removed: list[Range] = []
    added: list[Range] = []
    lines = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in lines.get_opcodes():
        old_start, old_end = old_starts[i1], old_starts[i2]
        new_start, new_end = new_starts[j1], new_starts[j2]
        if tag == "equal":
            continue
        if tag != "replace" or max(old_end - old_start, new_end - new_start) > DETAILED_BLOCK_LIMIT:
            _add(removed, old_start, old_end)
            _add(added, new_start, new_end)
            continue
        old_words = _words(old[old_start:old_end])
        new_words = _words(new[new_start:new_end])
        old_offsets, new_offsets = _line_starts(old_words), _line_starts(new_words)
        words = SequenceMatcher(None, old_words, new_words, autojunk=False)
        for tag, a1, a2, b1, b2 in words.get_opcodes():
            if tag != "equal":
                _add(removed, old_start + old_offsets[a1], old_start + old_offsets[a2])
                _add(added, new_start + new_offsets[b1], new_start + new_offsets[b2])
    return removed, added


def _words(text: str) -> list[str]:
    """The text cut into words, runs of spaces and single other characters, which
    together make up the whole text."""
    return re.findall(r"\w+|\s+|[^\w\s]", text)


def _line_starts(lines: list[str]) -> list[int]:
    """The offset of each line, then the length of the whole text."""
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return starts


def _add(ranges: list[Range], start: int, end: int) -> None:
    if end > start:
        ranges.append((start, end - start))


def utf16_ranges(text: str, ranges: list[Range]) -> list[Range]:
    """The same ranges counted in UTF-16 units, as Qt's text positions are: a character
    outside the Basic Multilingual Plane, such as most emoji, counts twice there."""
    if all(ord(char) < 0x10000 for char in text):
        return ranges
    positions = [0]
    for char in text:
        positions.append(positions[-1] + (2 if ord(char) >= 0x10000 else 1))
    return [(positions[start], positions[start + length] - positions[start])
            for start, length in ranges]
