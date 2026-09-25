"""The About window, with the version and where things are, and the list of shortcuts."""

import os
import platform
import sys
from typing import TYPE_CHECKING

import PySide6
from PySide6.QtCore import QLocale, Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .config import APP_DIR, APP_NAME, DATA_DIR, DEV_MODE, ICON_PATH, REPO_URL
from .i18n import tr
from .shortcuts import ACTIONS, BY_ID, normalized, settings
from .updates import can_update, git_version, installed_version

if TYPE_CHECKING:
    from .main_window import MainWindow

def key_name(key: str) -> str:
    """A key sequence as the system names it, with the names of Enter and Backspace as
    printed on keyboards rather than Qt's ("Retour", "Effacement" in French)."""
    text = QKeySequence(key).toString(QKeySequence.NativeText)
    for qt_key, name in (("Return", "key_enter"), ("Backspace", "key_backspace")):
        text = text.replace(QKeySequence(qt_key).toString(QKeySequence.NativeText), tr(name))
    return text


def key_names(keys: list[str]) -> str:
    return " / ".join(key_name(key) for key in keys)


class KeyDialog(QDialog):
    """Asks for an action's keys: one, and another if wanted."""

    def __init__(self, action_id: str, parent=None):
        super().__init__(parent)
        self.action_id = action_id
        action = BY_ID[action_id]
        self.setWindowTitle(tr("sc_edit_title", action=tr(action.description)))
        keys = settings.keys(action_id)
        self.edits = []
        form = QFormLayout()
        for index, label in enumerate(("sc_key", "sc_other_key")):
            edit = QKeySequenceEdit(QKeySequence(keys[index]) if index < len(keys) else QKeySequence())
            if hasattr(edit, "setMaximumSequenceLength"):  # one key per field, Qt 6.5+
                edit.setMaximumSequenceLength(1)
            if hasattr(edit, "setClearButtonEnabled"):
                edit.setClearButtonEnabled(True)
            form.addRow(tr(label), edit)
            self.edits.append(edit)
        hint = QLabel(tr("sc_edit_hint"))
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def keys(self) -> list[str]:
        keys = []
        for edit in self.edits:
            key = normalized(edit.keySequence())
            if key and key not in keys:
                keys.append(key)
        return keys

    def accept(self) -> None:
        """Only keys no other action has where this one works."""
        for key in self.keys():
            other = settings.conflict(self.action_id, key)
            if other is not None:
                QMessageBox.warning(self, tr("shortcuts_title"), tr(
                    "sc_conflict", shortcut=key_name(key), action=tr(BY_ID[other].description)))
                return
        settings.set_keys(self.action_id, self.keys())
        super().accept()


class ShortcutsDialog(QDialog):
    """Every shortcut and gesture, which the user can change, turn off or reset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("shortcuts_title"))
        self.resize(640, 700)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("sc_action"), tr("sc_keys")])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(lambda item, _column: self.edit(item))
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())

        self.edit_button = QPushButton(tr("sc_edit"))
        self.edit_button.clicked.connect(lambda: self.edit(self.tree.currentItem()))
        self.disable_button = QPushButton(tr("sc_disable"))
        self.disable_button.clicked.connect(self.disable)
        self.default_button = QPushButton(tr("sc_default"))
        self.default_button.clicked.connect(self.reset)
        reset_all_button = QPushButton(tr("sc_reset_all"))
        reset_all_button.clicked.connect(self.reset_all)
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        for button in (self.edit_button, self.disable_button, self.default_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(reset_all_button)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        current = self.selected()
        self.tree.blockSignals(True)
        self.tree.clear()
        section = None
        for action in ACTIONS:
            if action.section != section:
                section = action.section
                header = QTreeWidgetItem(self.tree, [tr(section)])
                font = header.font(0)
                font.setBold(True)
                header.setFont(0, font)
                header.setFirstColumnSpanned(True)
                header.setFlags(Qt.ItemIsEnabled)
            item = QTreeWidgetItem(self.tree, [tr(action.description)])
            item.setData(0, Qt.UserRole, action.id)
            if action.gesture:
                item.setText(1, tr(action.gesture))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(1, Qt.Checked if settings.enabled(action.id) else Qt.Unchecked)
            else:
                keys = settings.keys(action.id)
                item.setText(1, key_names(keys) if keys else tr("sc_disabled"))
            if not settings.is_default(action.id):  # what the user changed stands out
                for column in (0, 1):
                    font = item.font(column)
                    font.setBold(True)
                    item.setFont(column, font)
            if action.id == current:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self.tree.resizeColumnToContents(0)
        self._update_buttons()

    def selected(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _update_buttons(self) -> None:
        action_id = self.selected()
        keys = action_id is not None and not BY_ID[action_id].gesture
        self.edit_button.setEnabled(keys)
        self.disable_button.setEnabled(keys and settings.enabled(action_id))
        self.default_button.setEnabled(action_id is not None and not settings.is_default(action_id))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        action_id = item.data(0, Qt.UserRole)
        if action_id and BY_ID[action_id].gesture and column == 1:
            settings.set_enabled(action_id, item.checkState(1) == Qt.Checked)
            self.refresh()

    def edit(self, item: QTreeWidgetItem | None) -> None:
        action_id = item.data(0, Qt.UserRole) if item is not None else None
        if action_id is None:
            return
        if BY_ID[action_id].gesture:
            settings.set_enabled(action_id, not settings.enabled(action_id))
        elif KeyDialog(action_id, self).exec() != QDialog.Accepted:
            return
        self.refresh()

    def disable(self) -> None:
        if self.selected() is not None:
            settings.set_keys(self.selected(), [])
            self.refresh()

    def reset(self) -> None:
        if self.selected() is not None:
            settings.reset(self.selected())
            self.refresh()

    def reset_all(self) -> None:
        if QMessageBox.question(self, tr("shortcuts_title"), tr("sc_confirm_reset_all")
                                ) == QMessageBox.Yes:
            settings.reset()
            self.refresh()


def display_server() -> str:
    """How the windows are drawn: X11 through XWayland in a Wayland session, or not."""
    name = QGuiApplication.platformName()
    if name == "xcb":
        return "XWayland" if os.environ.get("WAYLAND_DISPLAY") else "X11"
    return {"wayland": "Wayland", "windows": "Windows"}.get(name, name)


def version_text() -> str:
    version = installed_version()
    if DEV_MODE:
        text = tr("about_dev_version", branch=version.branch or "?", commit=version.commit or "?")
        return text + (f" — {tr('about_modified')}" if version.modified else "")
    name = version.release or tr("about_unknown_release")
    text = tr("about_version", release=name, commit=version.commit or "?")
    if version.installed is not None:
        date = QLocale().toString(version.installed.date(), QLocale.FormatType.LongFormat)
        text += "\n" + tr("about_installed_on", date=date)
    return text


def history_text(main: "MainWindow") -> str:
    version = git_version()
    if not version:
        return tr("about_history_no_git")
    return tr("about_history_on", version=version) if main.store.versioning \
        else tr("about_history_off")


def version_summary() -> str:
    version = installed_version()
    if DEV_MODE:
        return (f"development, branch {version.branch or '?'}, commit {version.commit or '?'}"
                + (", modified" if version.modified else ""))
    return f"{version.release or 'unknown release'} ({version.commit or '?'})"


def technical_text() -> str:
    """What a bug report needs, in English whatever the interface's language."""
    try:
        system = platform.freedesktop_os_release().get("PRETTY_NAME", platform.platform())
    except OSError:
        system = platform.platform()
    return "\n".join([
        f"{APP_NAME}: {version_summary()}",
        f"System: {system}",
        f"Display: {display_server()} ({QGuiApplication.platformName()})",
        f"Python: {sys.version.split()[0]}",
        f"git: {git_version() or 'not installed'}",
        f"PySide6: {PySide6.__version__}, Qt: {qVersion()}",
        f"Installed in: {APP_DIR}",
        f"Notes in: {DATA_DIR}",
    ])


def web_url() -> str:
    """The repository's page, for a repository on the web; "" otherwise."""
    if not REPO_URL.startswith(("https://", "http://")):
        return ""
    return REPO_URL.removesuffix("/").removesuffix(".git")


class AboutDialog(QDialog):
    def __init__(self, main: "MainWindow"):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(tr("about_title"))

        icon = QLabel()
        icon.setPixmap(QIcon(str(ICON_PATH)).pixmap(64, 64))
        name = QLabel(APP_NAME)
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        font.setBold(True)
        name.setFont(font)
        self.version = QLabel(version_text() + "\n" + history_text(main))
        self.version.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.update_button = QPushButton(tr("about_check_updates"))
        self.update_button.clicked.connect(main.update_app)
        if not can_update():
            self.update_button.setEnabled(False)
            self.update_button.setToolTip(tr("update_from_clone", path=APP_DIR))
        heading = QVBoxLayout()
        heading.addWidget(name)
        heading.addWidget(self.version)
        heading.addWidget(self.update_button, 0, Qt.AlignLeft)
        top = QHBoxLayout()
        top.addWidget(icon, 0, Qt.AlignTop)
        top.addLayout(heading, 1)

        places = QGroupBox(tr("about_places"))
        grid = QGridLayout(places)
        for row, (label, path) in enumerate(((tr("about_app_dir"), APP_DIR),
                                             (tr("about_data_dir"), DATA_DIR))):
            path_label = QLabel(str(path))
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            open_button = QPushButton(tr("about_open"))
            open_button.clicked.connect(
                lambda _=False, path=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(path_label, row, 1)
            grid.addWidget(open_button, row, 2)
        grid.setColumnStretch(1, 1)

        technical = QGroupBox(tr("about_technical"))
        self.technical = QLabel(technical_text())
        self.technical.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_button = QPushButton(tr("about_copy"))
        copy_button.clicked.connect(self.copy_information)
        technical_layout = QVBoxLayout(technical)
        technical_layout.addWidget(self.technical)
        technical_layout.addWidget(copy_button, 0, Qt.AlignLeft)

        links = []
        if web_url():
            links.append(f'<a href="{web_url()}">GitHub</a>')
        license_file = APP_DIR / "LICENSE"
        license_url = (QUrl.fromLocalFile(str(license_file)).toString() if license_file.exists()
                       else f"{web_url()}/blob/main/LICENSE" if web_url() else "")
        if license_url:
            links.append(f'<a href="{license_url}">{tr("about_license")}</a>')
        self.links = QLabel(" · ".join(links))
        self.links.setOpenExternalLinks(True)

        shortcuts_button = QPushButton(tr("shortcuts_menu"))
        shortcuts_button.clicked.connect(main.show_shortcuts)
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(self.close)
        close_button.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.links)
        buttons.addStretch()
        buttons.addWidget(shortcuts_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(places)
        layout.addWidget(technical)
        layout.addLayout(buttons)
        self.resize(max(self.sizeHint().width(), 520), self.sizeHint().height())

    def copy_information(self) -> None:
        QApplication.clipboard().setText(technical_text())
