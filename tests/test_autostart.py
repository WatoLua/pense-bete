import sys

import pytest

from pensebete import autostart


@pytest.fixture(autouse=True)
def no_entry():
    autostart.disable()
    yield
    autostart.disable()


def test_the_entry_is_added_then_removed():
    assert not autostart.enabled()

    autostart.enable()
    assert autostart.enabled()

    autostart.disable()
    assert not autostart.enabled()
    autostart.disable()  # nothing left to remove: nothing fails


@pytest.mark.skipif(sys.platform == "win32", reason="a desktop entry is for Linux")
def test_the_desktop_entry_starts_this_copy():
    autostart.enable()

    entry = autostart.DESKTOP_FILE.read_text()
    assert "X-GNOME-Autostart-enabled=true" in entry
    exec_line = next(line for line in entry.splitlines() if line.startswith("Exec="))
    assert exec_line == "Exec=" + " ".join(f'"{part}"' for part in autostart.command())


def test_paths_are_quoted_for_the_desktop_entry(monkeypatch):
    monkeypatch.setattr(autostart, "WINDOWS", False)
    assert autostart._quoted(["/a b/c", 'd"$']) == '"/a b/c" "d\\"\\$"'


@pytest.mark.skipif(sys.platform != "win32", reason="the registry is Windows'")
def test_the_run_value_starts_this_copy():
    import winreg
    autostart.enable()

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY) as key:
        value, _ = winreg.QueryValueEx(key, autostart.APP_ID)
    assert value == " ".join(f'"{part}"' for part in autostart.command())
    assert autostart.RUN_KEY != r"Software\Microsoft\Windows\CurrentVersion\Run"


def test_the_menu_option_follows_the_entry(main_window):
    assert not main_window.autostart_action.isChecked()

    main_window.autostart_action.setChecked(True)
    assert autostart.enabled()

    main_window.autostart_action.setChecked(False)
    assert not autostart.enabled()


def test_a_failure_is_told_and_the_option_shows_what_is(main_window, monkeypatch,
                                                        answer_yes):
    def refuse():
        raise PermissionError("denied")
    monkeypatch.setattr(autostart, "enable", refuse)

    main_window.autostart_action.setChecked(True)

    assert not main_window.autostart_action.isChecked()
    assert answer_yes and "denied" in answer_yes[-1][2]
