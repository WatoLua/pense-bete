#!/usr/bin/env python3
"""Build icon.ico and icon-dev.ico, for Windows shortcuts, from the SVG icons.

Windows picks the size it needs from the file, so each holds the icon drawn at every
size it uses, as PNG images, which the ICO format accepts since Windows Vista.
Run it again after changing an SVG icon: python3 tools/make_icons.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ROOT = Path(__file__).resolve().parent.parent


def png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def ico(svg: Path) -> bytes:
    renderer = QSvgRenderer(str(svg))
    images = [(size, png(renderer, size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b"", b""
    for size, image in images:
        # A width or height of 0 means 256.
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(image), offset + len(data))
        data += image
    return header + entries + data


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841, needed to paint
    for name in ("icon", "icon-dev"):
        (ROOT / f"{name}.ico").write_bytes(ico(ROOT / f"{name}.svg"))
        print(f"{name}.ico")


if __name__ == "__main__":
    main()
