"""Where the application lives and keeps its data, and the constants it runs with."""

import os
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
# The directory holding the launcher, the package and the installers.
APP_DIR = Path(__file__).resolve().parent.parent
# Run from a git clone, the application is the development version: it keeps its own
# notes, menu entry and window class, apart from the installed application.
DEV_MODE = (APP_DIR / ".git").exists()
APP_ID = "pense-bete-dev" if DEV_MODE else "pense-bete"
APP_NAME = "Pense-bête (dev)" if DEV_MODE else "Pense-bête"
# The notes, and the window state kept apart from them so that moving a window never
# creates a commit: in the XDG directories on Linux, in %APPDATA% on Windows. The
# installers compute the same paths, to delete them on request.
if WINDOWS:
    _APP_DATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    DATA_DIR = Path(os.environ.get("PENSE_BETE_DIR") or _APP_DATA / "notes")
    SESSION_FILE = _APP_DATA / "session.json"
else:
    DATA_DIR = Path(
        os.environ.get("PENSE_BETE_DIR")
        or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    )
    SESSION_FILE = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID / "session.json"
    )
# Passed to every command run: on Windows, a command started from a windowless
# application would otherwise flash a console window. Output is UTF-8 whatever the
# system's code page, as git writes it.
SUBPROCESS_OPTIONS = {"encoding": "utf-8", "errors": "replace"}
if WINDOWS:
    SUBPROCESS_OPTIONS["creationflags"] = subprocess.CREATE_NO_WINDOW
RECENT_NOTES = 3
DEFAULT_RETENTION_DAYS = 30
ICON_PATH = APP_DIR / ("icon-dev.svg" if DEV_MODE else "icon.svg")
# Written by the installer: the installed commit of the repository, and its release tag
# when it is one.
VERSION_FILE = APP_DIR / ".version"
RELEASE_FILE = APP_DIR / ".release"
REPO_URL = os.environ.get("PENSE_BETE_REPO", "https://github.com/WatoLua/pense-bete.git")
AUTOSAVE_DELAY_MS = 10_000
DEFAULT_COLOR = "#fff59d"
# The size of a note's text, in pixels, which each note can zoom.
DEFAULT_FONT_SIZE = 13
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 40
PALETTE = {
    "yellow": "#fff59d",
    "orange": "#ffcc80",
    "pink": "#f8bbd0",
    "purple": "#d1c4e9",
    "blue": "#b3e5fc",
    "green": "#c5e1a5",
    "grey": "#e0e0e0",
}
