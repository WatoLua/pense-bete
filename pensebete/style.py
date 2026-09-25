"""Colors and icons drawn by the application."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on the given background."""
    color = QColor(background)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def pin_icon() -> QIcon:
    """A pin lying tilted when off, upright as if pushed in when on."""
    icon = QIcon()
    # The emoji is drawn tilted: turned back by 40 degrees, its needle points down.
    for state, angle in ((QIcon.Off, 0), (QIcon.On, -40)):
        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.translate(20, 20)
        painter.rotate(angle)
        font = painter.font()
        font.setPixelSize(26)
        painter.setFont(font)
        painter.drawText(QRect(-20, -20, 40, 40), Qt.AlignCenter, "📌")
        painter.end()
        icon.addPixmap(pixmap, QIcon.Normal, state)
    return icon


def color_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)
