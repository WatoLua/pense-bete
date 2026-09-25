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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .config import APP_DIR, APP_NAME, DATA_DIR, DEV_MODE, ICON_PATH, REPO_URL
from .i18n import tr
from .updates import can_update, git_version, installed_version

if TYPE_CHECKING:
    from .main_window import MainWindow

# (section, [(keys, description)]): keys are key sequences, shown as the system names
# them, or "@" and a translation key for what a key sequence cannot say.
SHORTCUTS = [
    ("sc_section_list", [
        (["Ctrl+F"], "sc_search"),
        (["Return"], "sc_open_first"),
        (["Esc"], "sc_clear_search"),
        (["Ctrl+W"], "sc_close_list"),
        (["F1"], "sc_shortcuts"),
    ]),
    ("sc_section_note", [
        (["Ctrl+S"], "sc_save"),
        (["Ctrl+W"], "sc_close_note"),
        (["Ctrl+Z"], "sc_undo"),
        (["Ctrl+Y", "Ctrl+Shift+Z"], "sc_redo"),
        (["Ctrl+Shift+C"], "sc_copy_all"),
        (["Ctrl+Del"], "sc_clear_all"),
        (["@sc_ctrl_wheel", "Ctrl++", "Ctrl+-"], "sc_zoom"),
        (["Ctrl+0"], "sc_zoom_reset"),
        (["@sc_alt_left_drag"], "sc_move"),
        (["@sc_alt_right_drag"], "sc_resize"),
        (["Alt+Left", "Alt+Right"], "sc_history"),
    ]),
    ("sc_section_markdown", [
        (["Ctrl+L"], "sc_insert_task"),
        (["Ctrl+T"], "sc_insert_table"),
        (["@sc_click_box", "Ctrl+Space"], "sc_toggle_task"),
        (["Return"], "sc_continue_list"),
    ]),
    ("sc_section_table", [
        (["Tab", "Shift+Tab"], "sc_next_cell"),
        (["Ctrl+Return"], "sc_add_row"),
        (["Ctrl+Shift+Return"], "sc_add_column"),
        (["Ctrl+Backspace"], "sc_delete_row"),
        (["Ctrl+Shift+Backspace"], "sc_delete_column"),
    ]),
]


def key_names(keys: list[str]) -> str:
    return " / ".join(tr(key[1:]) if key.startswith("@") else key_name(key) for key in keys)


def key_name(key: str) -> str:
    """A key sequence as the system names it, with the names of Enter and Backspace as
    printed on keyboards rather than Qt's ("Retour", "Effacement" in French)."""
    text = QKeySequence(key).toString(QKeySequence.NativeText)
    for qt_key, name in (("Return", "key_enter"), ("Backspace", "key_backspace")):
        text = text.replace(QKeySequence(qt_key).toString(QKeySequence.NativeText), tr(name))
    return text


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("shortcuts_title"))
        self.resize(580, 660)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("sc_keys"), tr("sc_action")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        for section, shortcuts in SHORTCUTS:
            header = QTreeWidgetItem(self.tree, [tr(section)])
            font = header.font(0)
            font.setBold(True)
            header.setFont(0, font)
            header.setFirstColumnSpanned(True)
            for keys, description in shortcuts:
                QTreeWidgetItem(self.tree, [key_names(keys), tr(description)])
        self.tree.resizeColumnToContents(0)
        close_button = QPushButton(tr("close"))
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addLayout(buttons)


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
