# Pense-bête

Sticky notes for the Linux desktop. A main window lists the notes; each note
opens in its own window, with a title, a color and free text.

- Notes are saved automatically 10 seconds after the last change, and
  immediately when their window is closed.
- Every save is committed to a local git repository, so the whole history of
  each note is kept: `git -C ~/.local/share/pense-bete log`.

The interface is in French.

## Requirements

- Python 3.10+
- git
- PySide6 (`pip install PySide6-Essentials`) — the installer offers to install it

## Installation

```sh
git clone <repository-url>
cd pense-bete
./install.sh
```

The script asks for the installation directory (default `~/.local/opt/pense-bete`),
copies the application there, adds **Pense-bête** to the GNOME application menu
and a `pense-bete` command in `~/.local/bin`. The directory can also be given
directly: `./install.sh ~/apps/pense-bete`.

To uninstall: `~/.local/opt/pense-bete/install.sh --uninstall`. Notes are kept.

## Data

Notes are JSON files in `~/.local/share/pense-bete/` (a git repository). Set
`PENSE_BETE_DIR` to store them elsewhere.
