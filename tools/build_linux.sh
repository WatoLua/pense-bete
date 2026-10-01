#!/usr/bin/env bash
# Builds the standalone Linux version of Pense-bête.
#
# pense-bete with Python and PySide6 in it, in dist/pense-bete, checked with its
# self-test, and its archive dist/pense-bete-linux.tar.gz, which install.sh installs by
# default. GitHub Actions runs it for every release, on an older Ubuntu, so that the build
# runs on the systems released since; from a clone:
#   tools/build_linux.sh [<release> <commit>]
# The release and commit, when given, are recorded in the build, which the installer
# copies along: it has no other way of knowing them. It needs PyInstaller and the
# application's requirements:
#   python3 -m pip install pyinstaller -r requirements.txt
set -euo pipefail
root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
dist="$root/dist"
app="$dist/pense-bete"

# QtSvg is imported by name: nothing in the code does, but Qt's SVG image plugin, which
# draws the icons, needs it.
python3 -m PyInstaller --noconfirm --clean --name pense-bete \
    --hidden-import PySide6.QtSvg --exclude-module tkinter \
    --distpath "$dist" --workpath "$root/build" --specpath "$root/build" \
    "$root/pense_bete.py"
# Beside the executable, where the application and the installer look for them.
cp -- "$root/icon.svg" "$root/LICENSE" "$root/install.sh" "$app/"
chmod +x "$app/install.sh"
if [[ -n "${1:-}" ]]; then printf '%s\n' "$1" > "$app/.release"; fi
if [[ -n "${2:-}" ]]; then printf '%s\n' "$2" > "$app/.version"; fi

# A module or Qt plugin left out shows here, before the build is published.
report="$dist/self-test.txt"
status=0
QT_QPA_PLATFORM=offscreen "$app/pense-bete" --self-test "$report" || status=$?
cat -- "$report" 2>/dev/null || true
if (( status )); then
    echo "The self-test failed (exit code $status)." >&2
    exit 1
fi

# The archive holds the pense-bete directory, as GitHub's source archives hold theirs.
tar -C "$dist" -czf "$dist/pense-bete-linux.tar.gz" pense-bete
echo "Built $dist/pense-bete-linux.tar.gz ($(du -m "$dist/pense-bete-linux.tar.gz" | cut -f1) MB)"
