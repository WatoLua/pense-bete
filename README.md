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

In the main window, open the **⋮** menu and choose **Update**: Pense-bête checks
GitHub for a new version, installs it and offers to restart. Running the
installation command again does the same. The notes are not touched.

An application run from a git clone is updated with `git pull` instead.

### Uninstalling

In the **⋮** menu, choose **Uninstall**, or run:

```sh
~/.local/opt/pense-bete/install.sh --uninstall
```

The application, its menu entry and its command are removed. The notes are kept.

## Data

Notes are JSON files in `~/.local/share/pense-bete/` (a git repository). Set
`PENSE_BETE_DIR` to store them elsewhere.

## Development

Run from a git clone, the application is **Pense-bête (dev)**, kept apart from
the installed one: its notes are in `~/.local/share/pense-bete-dev/`, its icon
carries a DEV badge, and it has its own entry in the application menu once
registered with:

```sh
./install.sh --dev
```

The entry runs the code of the clone directly, so changes are picked up at the
next launch; `./pense-bete` from the clone does the same. `pense-bete-dev` is
also available as a command. To remove the entry: `./install.sh --uninstall --dev`
(the clone itself is kept).
