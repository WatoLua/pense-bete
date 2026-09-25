"""Colors and icons drawn by the application."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap


def text_color_for(background: str) -> str:
    """Black or white, whichever reads better on the given background."""
    color = QColor(background)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def note_palette(background: str) -> QPalette:
    """The colors of a note's window, drawn from its paper: every widget in it, buttons
    and labels included, reads on the paper whatever the system's theme, dark or light."""
    paper = QColor(background)
    ink = QColor(text_color_for(background))
    # Buttons a shade off the paper, so that they show as buttons on it.
    button = paper.darker(108) if ink.lightness() < 128 else paper.lighter(125)
    palette = QPalette(button, paper)
    palette.setColor(QPalette.Base, paper)
    faded = QColor(ink)
    faded.setAlpha(110)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Active, role, ink)
        palette.setColor(QPalette.Inactive, role, ink)
        palette.setColor(QPalette.Disabled, role, faded)
    palette.setColor(QPalette.PlaceholderText, faded)
    return palette


def pixel_font(font: QFont, size: int, bold: bool = False) -> QFont:
    """A copy of the font at a size in pixels, as the notes' text sizes are counted."""
    font = QFont(font)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


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
