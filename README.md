# Pense-bête

Sticky notes for the Linux desktop. A main window lists the notes; each note
opens in its own window, with a title, a color and free text.

The interface is in French or English, following the system language.

## Features

### Notes

- **New** creates a note, **Delete** moves the selected one to the deleted
  notes; double-click a note to open it.
- A note's title and color (seven presets, or any color with **Other…**) are
  shown in the list.
- The 📌 button keeps a note above the other windows; the pin stands upright
  while it is on.
- Notes are saved automatically 10 seconds after the last change, and
  immediately when their window is closed, when the session ends, or when the
  application is told to stop (as at shutdown).

### History

Every save is committed to the note's own local git repository, so the whole
history of each note is kept, apart from the others.

**History** in a note splits its window: the version picked on the left,
read-only and in its own color, the current note on the right. Versions are
picked from a dated list, newest first, or browsed with the arrows
(Alt+← / Alt+→). From there:

- **Restore** replaces the current note with that version; the replaced text
  stays in the history;
- **New note** copies that version into another note;
- **✕** closes the history.

### Deleted notes

**Deleted notes…** in the **⋮** menu lists the deleted notes, with the days
left before they are erased. A note can be restored, with its whole history, or
erased at once. The delay before erasing is set there, 30 days by default;
expired notes are erased at launch and when that list opens. Erasing a note
removes its repository, and so its history.

### Windows and background

- The open windows — the list and the notes — come back at the next launch,
  with their size and position.
- With **Keep running in the background when closed**, in the **⋮** menu,
  closing the list leaves the notes open and the application running. Its icon
  in the top bar opens a menu to reopen the list or one of the last three notes
  opened, or to quit. **Quit** is also in the **⋮** menu.
- Only one instance runs: launching the application again brings its list back.

## Requirements

- Python 3.10+
- git
- PySide6 (`pip install PySide6-Essentials`) — the installer offers to install it
- `libxcb-cursor0` (`sudo apt install libxcb-cursor0`), so that windows reopen
  where they were. Without it the application runs under Wayland, which leaves
  window placement to GNOME: sizes are restored, positions are not.
- For the top bar icon, GNOME needs the AppIndicator extension, enabled by
  default on Ubuntu (`ubuntu-appindicators`).

## Installation

Run this in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
```

The installer:

1. checks that `python3` and `git` are available, warns if `libxcb-cursor0` is
   missing, and offers to install PySide6 with pip if it is missing;
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

With **Update automatically at launch** checked in the same menu, Pense-bête
looks for a new version each time it starts, in the background, and installs
it; the new version runs from the next launch, which it offers to do at once.
A failed check, when offline for instance, is silent.

Installations older than the **⋮** menu are updated by running the installation
command again. Notes saved before each note got its own repository are in a
format this version does not read.

An application run from a git clone is updated with `git pull` instead.

### Uninstalling

In the **⋮** menu, choose **Uninstall**, or run:

```sh
~/.local/opt/pense-bete/install.sh --uninstall
```

The application, its menu entry and its command are removed. It then asks
whether to delete the notes and settings as well — the default keeps them; in
the application, that is the checkbox of the confirmation. `--purge` deletes
them without asking. Only note directories are deleted, so a `PENSE_BETE_DIR`
pointing at a folder with other files loses nothing else.

## Data

- **Notes:** each note is a directory in `~/.local/share/pense-bete/`, holding
  the note as `note.json` and its git repository:
  `git -C ~/.local/share/pense-bete/<id> log` shows its history. Set
  `PENSE_BETE_DIR` to store the notes elsewhere.
- **Window state:** the open windows, their geometry, the recent notes and the
  options are in `~/.config/pense-bete/session.json`, apart from the notes so
  that moving a window never creates a commit.

## Development

Run from a git clone, the application is **Pense-bête (dev)**, kept apart from
the installed one: its notes are in `~/.local/share/pense-bete-dev/`, its window
state in `~/.config/pense-bete-dev/`, its icon carries a DEV badge, and it has
its own entry in the application menu once registered with:

```sh
./install.sh --dev
```

The entry runs the code of the clone directly, so changes are picked up at the
next launch; `./pense-bete` from the clone does the same, and **Restart** in the
**⋮** menu, only there in development, relaunches it with the current code. `pense-bete-dev` is
also available as a command. To remove the entry: `./install.sh --uninstall --dev`
(the clone itself is kept).

`PENSE_BETE_REPO` points updates and the standalone installer at another
repository, such as a fork. `QT_QPA_PLATFORM=wayland` runs the application
under Wayland instead of XWayland.
