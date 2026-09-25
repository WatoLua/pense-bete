# Pense-bête

Sticky notes for Linux and Windows. A main window lists the notes; each note
opens in its own window, with a title, a color and free text.

The interface is in French or English, following the system language.

## Features

### Notes

- **New** creates a note, **Delete** moves the selected one to the deleted
  notes; double-click a note to open it.
- The search field above the list (Ctrl+F) keeps the notes whose title or text
  holds every word typed, whatever the case and accents: "reunion" finds
  "Réunion". Enter opens the first note found, Escape clears the search.
- A note's title and color (seven presets, or any color with **Other…**) are
  shown in the list.
- **Sort by**, in the **⋮** menu, orders the list by creation date, last
  modification (the latest first) or title.
- Each note has its own text size: Ctrl with the mouse wheel, Ctrl++ or Ctrl+-
  zoom it, Ctrl+0 goes back to the default. The size is kept for the next
  launch.
- In a note, Ctrl+L inserts a task (`- [ ] `), Ctrl+T a table, its first
  header selected; Ctrl+Shift+C copies the whole note, Ctrl+Delete clears it
  (Ctrl+Z brings it back). These are also in the right-click menu. Ctrl+Y
  redoes, as does Ctrl+Shift+Z. Ctrl+S saves at once, and Ctrl+W closes the
  window, the note or the list, as Alt+F4 does.
- Ctrl+F finds words in a note, Ctrl+H finds and replaces them, in a bar under
  its text: every match is marked, Enter and Shift+Enter (or F3 and Shift+F3)
  go to the next and previous one, **Aa** matches the case, **Replace all** is
  one step that Ctrl+Z takes back, and Escape closes the bar.
- Alt with the left button, from anywhere in a note, moves its window; Alt with
  the right button resizes it from the corner nearest to the click, the
  opposite corner staying put, so that moving the mouse away grows it and back
  shrinks it.
- The 📌 button keeps a note above the other windows; the pin stands upright
  while it is on.
- Notes are saved automatically 10 seconds after the last change, and
  immediately when their window is closed, when the session ends, or when the
  application is told to stop (as at shutdown).

### Markdown

Notes are plain text. With **Format the notes' Markdown** checked in the **⋮**
menu, their Markdown is shown formatted in place: headings, **bold**, *italic*,
~~struck~~ and `code`, quotes, lists and tables, their markers dimmed but kept.
The text stays exactly as typed, so unchecking the option loses nothing.

- `- [ ]` is a task, for to-do lists and checklists alike: a click on its box
  turns it to `[v]`, ok, in green, its text struck through and faded, then to `[x]`, ko, in
  red, then back to `[ ]`. Ctrl+Space does the same from anywhere on the
  task's line, and the letter can be typed as well.
- Enter at the end of a list item starts the next one — same bullet, next
  number, a new unchecked box; Enter on an empty item ends the list.
- A table (`| a | b |` lines) is shown in a fixed font. Its columns are aligned
  2 seconds after the typing pauses, and when the cursor leaves it; the cursor
  stays where it was in its cell, and Ctrl+Z takes back the typing and the
  alignment together, Ctrl+Y brings both back. In a table:
  - Tab and Shift+Tab go to the next and previous cell; Tab in the last cell
    adds a row;
  - Ctrl+Enter adds a row below, Ctrl+Shift+Enter a column to the right;
  - Ctrl+Backspace deletes the row, Ctrl+Shift+Backspace the column;
  - the right-click menu also adds rows and columns, and deletes them.
- Ctrl+L and Ctrl+T, or the right-click menu, insert a task or a table.
- Formatting keys put the markers around the selection, or a pair of them to
  type in without one; the same key again takes them away. Ctrl+B is bold,
  Ctrl+I italic, Ctrl+Shift+X struck through, Ctrl+E code. Ctrl+1, 2 and 3
  make the lines headings, Ctrl+Q a quote, Ctrl+Shift+L a bulleted list. They
  are also in the right-click menu, under **Formatting**, and work whether the
  option is checked or not: the markers are text like any other.

### History

Every save is committed to the note's own local git repository, so the whole
history of each note is kept, apart from the others.

**Keep each note's history (git)**, in the **⋮** menu, turns this off: notes are
then saved without commits, and the **History** button goes away. Without git,
the option is off and greyed out. Repositories already there are kept, and saves
are committed again once the option is back on. **About…** says whether the
history is on.

**History** in a note splits its window: the version picked on the left,
read-only and in its own color, the current note on the right. Versions are
picked from a dated list, newest first, or browsed with the arrows
(Alt+← / Alt+→). What changed since that version is highlighted, word by word:
in red in the version, what the note has lost; in green in the note, what it
has gained. The highlights follow the typing and never change the text. From
there:

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

### About and shortcuts

**About…**, in the **⋮** menu, shows the installed version and when it was
installed (in development: the branch, the commit and whether the clone has
uncommitted changes), a button to check for updates, the application and notes
directories with a button to open each, and the technical information a bug
report needs — system, display server, Python, PySide6 and Qt versions — with a
button to copy it. **Keyboard shortcuts…** (F1, from the list or a note) lists
every shortcut, and changes them: **Change…**, or a double click, records new
keys, a second key if wanted; **Turn off** leaves an action without keys;
**Default** and **Reset all** put the defaults back. Mouse gestures — Ctrl with
the wheel, Alt and a drag, a click on a task's box — are turned on or off with
their checkbox. A key another action already has, where both would work, is
refused. Changes are shown in bold and kept for the next launches, on this
machine.

### Backup

**Export the notes…**, in the **⋮** menu, writes every note, deleted ones
included, with its whole history into a `.zip` archive. **Import notes…** adds
the notes of such an archive, on this machine or another: a note already there
and unchanged is skipped, one that differs is added beside the existing one, so
an import never overwrites anything.

### Windows and background

- The open windows — the list and the notes — come back at the next launch,
  with their size and position.
- With **Keep running in the background when closed**, in the **⋮** menu,
  closing the list leaves the notes open and the application running. Its icon
  in the top bar opens a menu to reopen the list or one of the last three notes
  opened, or to quit. **Quit** is also in the **⋮** menu.
- Only one instance runs: launching the application again brings its list back.
- **Start with the system**, in the **⋮** menu, launches the application when
  you log in: an entry in `~/.config/autostart` on Linux, a value of the
  registry's `Run` key on Windows. Unchecking it removes the entry, as
  uninstalling does.

## Requirements

- Python 3.10+ — on Windows, from [python.org](https://www.python.org/downloads/),
  or none with the standalone version
- git, for the history of the notes — on Windows,
  [Git for Windows](https://git-scm.com/download/win). Without it, everything else
  works: notes are saved without history, and the installer and updates download
  the releases from GitHub.
- PySide6 (`pip install PySide6-Essentials`) — the installer offers to install it

On Linux:

- `libxcb-cursor0` (`sudo apt install libxcb-cursor0`), so that windows reopen
  where they were. Without it the application runs under Wayland, which leaves
  window placement to GNOME: sizes are restored, positions are not.
- For the top bar icon, GNOME needs the AppIndicator extension, enabled by
  default on Ubuntu (`ubuntu-appindicators`).

## Installation

### Linux

Run this in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
```

The installer:

1. checks that `python3` and `git` are available, warns if `libxcb-cursor0` is
   missing, and offers to install PySide6 with pip if it is missing;
2. downloads the newest release of the application;
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

### Windows

Run this in PowerShell:

```powershell
irm https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.ps1 | iex
```

The installer checks that Python and git are available, offers to install
PySide6 with pip if it is missing, downloads the newest release, asks where to
install it — press Enter to keep the default, `%LOCALAPPDATA%\Programs\pense-bete`
— and adds **Pense-bête** to the Start menu. Its windows are grouped under that
entry in the taskbar, where it can be pinned.

Without Python, it offers the **standalone version** instead: `Pense-bete.exe`,
about 40 MB, with Python and PySide6 inside, nothing else to install. It is built
for every release and attached to it on GitHub, a few minutes after the release
is tagged. `-Standalone` asks for it even where Python is installed. The
standalone version updates and uninstalls from its **⋮** menu as the other does:
since Windows cannot replace a running program, it closes, its installer puts
the new files in place and starts it again. The installer's report is in
`%TEMP%\pense-bete-install.log`.

From a clone of the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Target <directory>]
```

### Updating

In the main window, open the **⋮** menu and choose **Update**: Pense-bête checks
GitHub for a new release, installs it and offers to restart. Without git, it
finds the release through the GitHub API and downloads its archive; a repository
set with `PENSE_BETE_REPO` outside GitHub needs git. Running the
installation command again does the same. The notes are not touched.

A release is a `vX.Y.Z` tag of the repository: commits pushed without a new tag
reach nobody.

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

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\pense-bete\install.ps1" -Uninstall
```

The application, its menu entry, its command and its start with the system
are removed. It then asks
whether to delete the notes and settings as well — the default keeps them; in
the application, that is the checkbox of the confirmation. `--purge` (`-Purge`
on Windows) deletes them without asking. Only note directories are deleted, so a `PENSE_BETE_DIR`
pointing at a folder with other files loses nothing else.

## Data

- **Notes:** each note is a directory in `~/.local/share/pense-bete/`
  (`%APPDATA%\pense-bete\notes\` on Windows), holding the note as `note.json`
  and its git repository: `git -C ~/.local/share/pense-bete/<id> log` shows its
  history. Set `PENSE_BETE_DIR` to store the notes elsewhere.
- **Window state:** the open windows, their geometry, the recent notes and the
  options are in `~/.config/pense-bete/session.json`
  (`%APPDATA%\pense-bete\session.json` on Windows), apart from the notes so that
  moving a window never creates a commit.

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
(the clone itself is kept). On Windows, `.\install.ps1 -Dev` and
`.\install.ps1 -Uninstall -Dev` do the same with a Start menu entry; its data is in
`%APPDATA%\pense-bete-dev\`.

`icon.ico` and `icon-dev.ico`, for the Windows shortcuts, are built from the SVG
icons: run `python3 tools/make_icons.py` after changing one.

### Releasing

Installations and updates follow the highest `vX.Y.Z` tag, compared number by
number (`v1.10.0` is newer than `v1.9.0`); other tags are ignored. To publish the
commit on `main` as a new version, with the notes that the update shows before
installing it:

```sh
git tag -a v1.2.0 -m "Search in the notes, sorted list"
git push origin v1.2.0
```

A tag made without `-a` works as well, only without notes.

Until the repository has a release, the installer takes the latest commit of the
default branch, and the application finds no update.

### Windows build

`tools/build_windows.ps1` builds the standalone version with PyInstaller into
`dist\Pense-bete`, checks it with `Pense-bete.exe --self-test <report>`, which
starts what a launch starts in throwaway directories, and packs it as
`dist\pense-bete-windows.zip`. The **Release** workflow runs it for every
`vX.Y.Z` tag and attaches the archive to the tag's GitHub release; started by
hand from the Actions tab, it only builds and checks.

### Tests

```sh
pip install --user -r requirements-dev.txt
pytest
```

The tests run offscreen, in a throwaway home directory: they never touch the
notes, settings, menu entries or start at login of the machine. GitHub runs them on every push,
on Linux and on Windows, where `install.ps1` is tested; each system skips the
other's installer tests.

`PENSE_BETE_REPO` points updates and the standalone installer at another
repository, such as a fork. `QT_QPA_PLATFORM=wayland` runs the application
under Wayland instead of XWayland.

## License

MIT, see [LICENSE](LICENSE).
