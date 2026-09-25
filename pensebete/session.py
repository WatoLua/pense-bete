"""The window state and options, kept across runs."""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray


class Session:
    """What is open across runs: windows and their geometry, recent notes, options.

    Keys: "background" (bool), "main_open" (bool), "open_notes", "recent" and "on_top"
    (note ids, most recent first for "recent"), "geometries" (window key -> base64),
    "font_sizes" (note id -> pixels, for the zoomed notes only), "sort" (the list's order),
    "retention_days" and "auto_update".
    """

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def geometry(self, key: str) -> QByteArray | None:
        value = self.data.get("geometries", {}).get(key)
        return QByteArray.fromBase64(value.encode()) if value else None

    def set_geometry(self, key: str, geometry: QByteArray) -> None:
        self.data.setdefault("geometries", {})[key] = bytes(geometry.toBase64()).decode()

    def forget(self, note_id: str) -> None:
        self.data.get("geometries", {}).pop(note_id, None)
        self.data.get("font_sizes", {}).pop(note_id, None)
        for key in ("open_notes", "recent", "on_top"):
            self.data[key] = [i for i in self.data.get(key, []) if i != note_id]

    def write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
            print(f"Could not save the session: {error}", file=sys.stderr)
