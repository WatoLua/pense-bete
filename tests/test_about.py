from PySide6.QtWidgets import QApplication

from pensebete import about
from pensebete.about import SHORTCUTS, AboutDialog, ShortcutsDialog, key_names


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

    rows = sum(1 + len(shortcuts) for _, shortcuts in SHORTCUTS)
    assert dialog.tree.topLevelItemCount() == rows


def test_key_names_mix_key_sequences_and_words():
    assert key_names(["Ctrl+Y", "@sc_ctrl_wheel"]) == "Ctrl+Y / Ctrl+wheel"


def test_the_repository_page_comes_from_its_url(monkeypatch):
    monkeypatch.setattr(about, "REPO_URL", "https://github.com/someone/fork.git")
    assert about.web_url() == "https://github.com/someone/fork"
    monkeypatch.setattr(about, "REPO_URL", "/srv/git/pense-bete.git")
    assert about.web_url() == ""
