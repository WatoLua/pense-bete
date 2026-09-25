"""The dialog listing the deleted notes."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QDateTime, QLocale, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr
from .storage import Note
from .style import text_color_for

if TYPE_CHECKING:
    from .main_window import MainWindow


class TrashDialog(QDialog):
    """The deleted notes, to restore or erase, and how long they are kept."""

    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("trash_title"))
        self.resize(460, 360)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _item: self.restore_selected())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())

        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(main.retention_days())
        # Only recorded: erasing waits for the next check, so that typing a number
        # never erases notes on the way through a smaller one.
        self.days.valueChanged.connect(self._set_retention)
        retention = QHBoxLayout()
        retention.addWidget(QLabel(tr("retention_before")))
        retention.addWidget(self.days)
        retention.addWidget(QLabel(tr("retention_after")))
        retention.addStretch()

        self.restore_button = QPushButton(tr("restore"))
        self.restore_button.clicked.connect(self.restore_selected)
        self.erase_button = QPushButton(tr("erase"))
        self.erase_button.clicked.connect(self.erase_selected)
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.erase_button)
        buttons.addStretch()
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(retention)
        layout.addLayout(buttons)
        self.refresh()

    def _set_retention(self, days: int) -> None:
        self.main.session.set("retention_days", days)
        self.main.session.write()
        self.refresh()

    def refresh(self) -> None:
        selected = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        notes = sorted(self.main.deleted_notes(), key=lambda note: note.deleted, reverse=True)
        for note in notes:
            date = QLocale().toString(QDateTime.fromString(note.deleted, Qt.ISODate).date(),
                                      QLocale.FormatType.ShortFormat)
            days = max(self.days.value() - note.days_in_trash(), 0)
            item = QListWidgetItem(tr("trash_item", title=note.display_title, date=date, days=days))
            item.setData(Qt.UserRole, note.id)
            item.setBackground(QColor(note.color))
            item.setForeground(QColor(text_color_for(note.color)))
            item.setToolTip(note.content[:500])
            self.list.addItem(item)
            if note.id == selected:
                self.list.setCurrentItem(item)
        if not notes:
            item = QListWidgetItem(tr("trash_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
        elif self.list.currentItem() is None:
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _selected(self) -> Note | None:
        item = self.list.currentItem()
        note_id = item.data(Qt.UserRole) if item else None
        return next((n for n in self.main.deleted_notes() if n.id == note_id), None)

    def _update_buttons(self) -> None:
        enabled = self._selected() is not None
        self.restore_button.setEnabled(enabled)
        self.erase_button.setEnabled(enabled)

    def restore_selected(self) -> None:
        note = self._selected()
        if note is not None:
            self.main.restore_note(note)
            self.refresh()

    def erase_selected(self) -> None:
        note = self._selected()
        if note is None:
            return
        if QMessageBox.question(self, tr("erase"), tr("confirm_erase", title=note.display_title)
                                ) != QMessageBox.Yes:
            return
        self.main.erase_note(note)
        self.refresh()
