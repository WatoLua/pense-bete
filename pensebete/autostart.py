"""Starting the application when the user logs in, as a choice of the options menu.

The entry itself is the setting: a desktop entry in the XDG autostart directory on
Linux, a value of the registry's Run key on Windows. Removing it is all it takes to
stop, and the installers remove it on uninstalling.
"""

import os
import sys
from pathlib import Path

from .config import APP_DIR, APP_ID, APP_NAME, DEV_MODE, FROZEN, ICON_PATH, WINDOWS

if WINDOWS:
    import winreg

# The Run key of the current user; tests point it elsewhere.
RUN_KEY = os.environ.get("PENSE_BETE_RUN_KEY",
                         r"Software\Microsoft\Windows\CurrentVersion\Run")
DESKTOP_FILE = (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
                / "autostart" / f"{APP_ID}.desktop")


def command() -> list[str]:
    """What starts this very copy of the application."""
    if FROZEN:
        return [sys.executable]
    launcher = APP_DIR / "pense-bete"  # the script install.sh writes
    if not WINDOWS and not DEV_MODE and launcher.exists():
        return [str(launcher)]
    python = Path(sys.executable)
    if WINDOWS and python.with_name("pythonw.exe").exists():
        python = python.with_name("pythonw.exe")  # no console window
    return [str(python), str(APP_DIR / "pense_bete.py")]


def _quoted(arguments: list[str]) -> str:
    """A command line with every argument in double quotes. Windows paths hold no quote;
    the desktop entry specification escapes these characters inside quotes."""
    if WINDOWS:
        return " ".join(f'"{argument}"' for argument in arguments)
    return " ".join('"' + "".join("\\" + c if c in '"`$\\' else c for c in argument) + '"'
                    for argument in arguments)


def enabled() -> bool:
    if WINDOWS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_ID)
            return True
        except OSError:
            return False
    return DESKTOP_FILE.exists()


def enable() -> None:
    """Start the application at login, from where it runs now."""
    if WINDOWS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _quoted(command()))
        return
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_quoted(command())}\n"
        f"Icon={ICON_PATH}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")


def disable() -> None:
    if WINDOWS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_ID)
        except FileNotFoundError:
            pass
        return
    DESKTOP_FILE.unlink(missing_ok=True)
