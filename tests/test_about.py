from PySide6.QtWidgets import QApplication

from pensebete import about
from pensebete.about import AboutDialog, ShortcutsDialog, key_names
from pensebete.shortcuts import ACTIONS


def test_the_about_window_shows_the_version_and_copies_the_information(main_window, qtbot):
    dialog = AboutDialog(main_window)
    qtbot.addWidget(dialog)

    # Run from this clone, it is the development version.
    assert "branch" in dialog.version.text() or "branche" in dialog.version.text()
    dialog.copy_information()
    copied = QApplication.clipboard().text()
    assert "Python:" in copied and "PySide6:" in copied and "Display:" in copied
    assert "github.com/WatoLua/pense-bete" in dialog.links.text()
    assert not dialog.update_button.isEnabled()  # a clone updates with git


def test_every_shortcut_is_listed(qtbot):
    dialog = ShortcutsDialog()
    qtbot.addWidget(dialog)

    sections = len({action.section for action in ACTIONS})
    assert dialog.tree.topLevelItemCount() == len(ACTIONS) + sections


def test_key_names_are_the_system_names_with_keyboard_words():
    assert key_names(["Ctrl+Y", "Ctrl+Return"]) == "Ctrl+Y / Ctrl+Enter"


def test_the_repository_page_comes_from_its_url(monkeypatch):
    monkeypatch.setattr(about, "REPO_URL", "https://github.com/someone/fork.git")
    assert about.web_url() == "https://github.com/someone/fork"
    monkeypatch.setattr(about, "REPO_URL", "/srv/git/pense-bete.git")
    assert about.web_url() == ""
