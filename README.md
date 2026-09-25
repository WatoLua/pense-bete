# Pense-bête

Sticky notes for the Linux desktop. A main window lists the notes; each note
opens in its own window, with a title, a color and free text.

- Notes are saved automatically 10 seconds after the last change, and
  immediately when their window is closed.
- Every save is committed to a local git repository, so the whole history of
  each note is kept: `git -C ~/.local/share/pense-bete log`.

The interface is in French or English, following the system language.

## Requirements

- Python 3.10+
- git
- PySide6 (`pip install PySide6-Essentials`) — the installer offers to install it

## Installation

Run this in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
```

The installer:

1. checks that `python3` and `git` are available, and offers to install PySide6
   with pip if it is missing;
2. downloads the application;
3. asks where to install it — press Enter to keep the default,
   `~/.local/opt/pense-bete`;
4. adds **Pense-bête** to the GNOME application menu, and a `pense-bete`
   command in `~/.local/bin`.

Then launch it from the application menu: search for "Pense-bête". If it does
not show up right away, log out and back in.

To choose the directory without being asked, pass it after `bash -s --`:

```sh
curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash -s -- ~/apps/pense-bete
```

From a clone of the repository, `./install.sh` does the same.

### Updating

Run the installation command again; the notes are not touched.

### Uninstalling

```sh
~/.local/opt/pense-bete/install.sh --uninstall
```

The application, its menu entry and its command are removed. The notes are kept.

## Data

Notes are JSON files in `~/.local/share/pense-bete/` (a git repository). Set
`PENSE_BETE_DIR` to store them elsewhere.
