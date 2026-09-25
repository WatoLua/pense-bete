#!/usr/bin/env bash
# Installs Pense-bête for the current user and registers it in the GNOME menu.
#
# Usage: ./install.sh [install-dir]   install (asks for the directory if not given)
#        ./install.sh --uninstall     remove the application, and on request its data
#        --purge                      with --uninstall: delete the notes and settings too
#        ./install.sh --dev           register this clone as "Pense-bête (dev)"
#        --yes                        ask nothing, take the default answers
#
# Also runs on its own, without a clone of the repository; it then installs the newest
# release, the highest vX.Y.Z tag:
#   curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
set -euo pipefail

ACTION=install
TARGET=""
ASSUME_YES=""
PURGE=""
DEV=""
for arg in "$@"; do
    case "$arg" in
        --uninstall) ACTION=uninstall ;;
        --purge) PURGE=1 ;;
        --dev) DEV=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) ACTION=help ;;
        *) TARGET="$arg" ;;
    esac
done

# The development version runs from a clone and has its own menu entry, command and
# notes (~/.local/share/pense-bete-dev), apart from the installed application.
APP_ID="pense-bete${DEV:+-dev}"
APP_NAME="Pense-bête${DEV:+ (dev)}"
REPO_URL="${PENSE_BETE_REPO:-https://github.com/WatoLua/pense-bete.git}"
# Empty when the script is piped into bash: the sources are then cloned from REPO_URL.
SOURCE_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SOURCE_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
    [[ -f "$SOURCE_DIR/pense_bete.py" ]] || SOURCE_DIR=""
fi
DEFAULT_DIR="$HOME/.local/opt/$APP_ID"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP_ID.desktop"
BIN_LINK="$HOME/.local/bin/$APP_ID"
# Where the application keeps its data, as pense_bete.py computes it.
DATA_DIR="${PENSE_BETE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
FILES=(pense_bete.py pense-bete icon.svg requirements.txt install.sh LICENSE)
PACKAGE=pensebete

# Messages are in French when the system locale is French, in English otherwise.
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
    fr*) FRENCH=1 ;;
    *) FRENCH="" ;;
esac
t() { if [[ -n "$FRENCH" ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }  # t "English" "Français"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m/!\\\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m%s\033[0m %s\n' "$(t "Error:" "Erreur :")" "$*" >&2; exit 1; }

# Answers come from the terminal, since stdin is the script itself when piped into bash.
# Without a terminal, the answer is empty and the default applies.
# --yes (ASSUME_YES) skips the questions, for the application's own update and uninstall.
ask() {  # ask "prompt" -> the answer
    local answer=""
    if [[ -z "$ASSUME_YES" ]] && { exec 3</dev/tty; } 2>/dev/null; then
        read -r -p "$1" answer <&3 || true
        exec 3<&-
    fi
    printf '%s' "$answer"
}

ask_yes() {  # ask_yes "question" -> true on yes, default yes
    local answer
    answer="$(ask "$1 $(t "[Y/n]" "[O/n]") ")"
    [[ -z "$answer" || "$answer" =~ ^[yYoO] ]]
}

ask_no() {  # ask_no "question" -> true on yes, default no
    local answer
    answer="$(ask "$1 $(t "[y/N]" "[o/N]") ")"
    [[ "$answer" =~ ^[yYoO] ]]
}

delete_data() {
    local note_dir
    # Only what the application wrote: note directories, then the data directory if that
    # leaves it empty, so that a PENSE_BETE_DIR pointing elsewhere loses nothing else.
    for note_dir in "$DATA_DIR"/*/; do
        [[ -f "$note_dir/note.json" ]] && rm -rf -- "$note_dir"
    done
    rmdir -- "$DATA_DIR" 2>/dev/null || true
    rm -f -- "$CONFIG_DIR/session.json" "$CONFIG_DIR/session.tmp"
    rmdir -- "$CONFIG_DIR" 2>/dev/null || true
}

uninstall() {
    local exec_line install_dir="" purge="$PURGE"
    # Asked first, so the answer does not depend on what the removal prints. Default no:
    # the notes cannot be recovered once deleted.
    if [[ -z "$purge" && -d "$DATA_DIR" ]] && ask_no "$(t "Also delete the notes and settings ($DATA_DIR)? They cannot be recovered." "Supprimer aussi les post-its et les réglages ($DATA_DIR) ? Ils ne pourront pas être récupérés.")"; then
        purge=1
    fi
    # The desktop entry records where the application was installed.
    if [[ -f "$DESKTOP_FILE" ]]; then
        exec_line="$(grep -m1 '^Exec=' "$DESKTOP_FILE" || true)"
        install_dir="$(dirname "${exec_line#Exec=}")"
    fi
    # A git working copy is a clone the application was installed in place from: it is
    # the user's own checkout, so only the menu entry and the command are removed.
    if [[ -n "$install_dir" && -e "$install_dir/.git" ]]; then
        warn "$(t "$install_dir is a git repository, it is kept." "$install_dir est un dépôt git, il est conservé.")"
    elif [[ -n "$install_dir" && -f "$install_dir/pense_bete.py" ]]; then
        if ask_yes "$(t "Delete $install_dir?" "Supprimer $install_dir ?")"; then
            rm -rf -- "$install_dir"
        fi
    fi
    rm -f -- "$DESKTOP_FILE"
    [[ -L "$BIN_LINK" ]] && rm -f -- "$BIN_LINK"
    command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP_FILE")" || true
    if [[ -n "$purge" ]]; then
        delete_data
        info "$(t "$APP_NAME is uninstalled, with its notes and settings." "$APP_NAME est désinstallé, avec ses post-its et ses réglages.")"
    else
        info "$(t "$APP_NAME is uninstalled. Notes are kept in $DATA_DIR." "$APP_NAME est désinstallé. Les post-its sont conservés dans $DATA_DIR.")"
    fi
}

latest_release() {  # the newest vX.Y.Z tag of REPO_URL, empty when it has none
    git ls-remote --tags --refs -- "$REPO_URL" 'refs/tags/v*' 2>/dev/null \
        | sed -n 's#.*refs/tags/\(v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$#\1#p' \
        | sort -V | tail -n 1
}

check_dependencies() {
    command -v python3 >/dev/null || fail "$(t "python3 not found, please install it first." "python3 est introuvable, installez-le d'abord.")"
    command -v git >/dev/null || fail "$(t "git not found, please install it first (it versions the notes)." "git est introuvable, installez-le d'abord (il versionne les post-its).")"

    if [[ -z "$SOURCE_DIR" ]]; then
        SOURCE_DIR="$(mktemp -d)"
        trap 'rm -rf -- "$SOURCE_DIR"' EXIT
        local release
        release="$(latest_release)"
        if [[ -n "$release" ]]; then
            info "$(t "Downloading Pense-bête $release from $REPO_URL" "Téléchargement de Pense-bête $release depuis $REPO_URL")"
        else
            warn "$(t "$REPO_URL has no release yet: installing its latest commit." "$REPO_URL n'a encore aucune version publiée : installation de son dernier commit.")"
        fi
        git clone --quiet --depth 1 ${release:+--branch "$release"} -- "$REPO_URL" "$SOURCE_DIR" \
            || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
    fi

    # Only a warning: without it the application runs under Wayland, which does not
    # restore window positions.
    if ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
        warn "$(t "libxcb-cursor0 is missing: windows will not reopen where they were. Install it with: sudo apt install libxcb-cursor0" "libxcb-cursor0 est absent : les fenêtres ne se rouvriront pas à leur place. Installez-le avec : sudo apt install libxcb-cursor0")"
    fi

    if python3 -c "import PySide6" 2>/dev/null; then
        return
    fi
    warn "$(t "The PySide6 library is not installed." "La bibliothèque PySide6 n'est pas installée.")"
    if ask_yes "$(t "Install it now with pip?" "L'installer maintenant avec pip ?")"; then
        if python3 -m pip install --user -r "$SOURCE_DIR/requirements.txt"; then
            return
        fi
        warn "$(t "Installation with pip failed." "L'installation avec pip a échoué.")"
    fi
    fail "$(t "Install PySide6-Essentials (pip install PySide6-Essentials), then run this script again." "Installez PySide6-Essentials (pip install PySide6-Essentials) puis relancez ce script.")"
}

install() {
    local target="${1:-}"
    if [[ -n "$DEV" ]]; then
        [[ -n "$SOURCE_DIR" && -e "$SOURCE_DIR/.git" ]] \
            || fail "$(t "--dev runs from a git clone of the repository." "--dev s'utilise depuis un clone git du dépôt.")"
        target="$SOURCE_DIR"
    fi
    check_dependencies
    if [[ -z "$target" ]]; then
        target="$(ask "$(t "Installation directory [$DEFAULT_DIR]: " "Dossier d'installation [$DEFAULT_DIR] : ")")"
        target="${target:-$DEFAULT_DIR}"
    fi
    target="${target/#\~/$HOME}"
    mkdir -p -- "$target"
    target="$(cd "$target" && pwd)"

    if [[ "$target" != "$SOURCE_DIR" ]]; then
        if [[ -n "$(ls -A "$target")" && ! -f "$target/pense_bete.py" ]]; then
            ask_yes "$(t "$target is not empty, install anyway?" "$target n'est pas vide, installer quand même ?")" || fail "$(t "Installation cancelled." "Installation annulée.")"
        fi
        info "$(t "Copying files to $target" "Copie des fichiers dans $target")"
        for file in "${FILES[@]}"; do
            cp -- "$SOURCE_DIR/$file" "$target/"
        done
        # Replaced as a whole, so that no module of an earlier version is left behind.
        rm -rf -- "${target:?}/$PACKAGE"
        mkdir -- "$target/$PACKAGE"
        cp -- "$SOURCE_DIR/$PACKAGE"/*.py "$target/$PACKAGE/"
    fi
    chmod +x "$target/pense-bete" "$target/pense_bete.py" "$target/install.sh"
    # The installed commit, which the application compares with the repository to offer updates.
    if [[ ! -e "$target/.git" ]]; then
        git -C "$SOURCE_DIR" rev-parse HEAD > "$target/.version" 2>/dev/null || rm -f -- "$target/.version"
        # And the release it is, when the commit is one, for the About window.
        git -C "$SOURCE_DIR" describe --tags --exact-match --match 'v[0-9]*' HEAD \
            > "$target/.release" 2>/dev/null || rm -f -- "$target/.release"
    fi

    info "$(t "Adding the entry to the applications menu" "Ajout de l'entrée dans le menu des applications")"
    mkdir -p -- "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Sticky notes versioned with git
Comment[fr]=Post-its versionnés avec git
Exec=$target/pense-bete
Icon=$target/icon${DEV:+-dev}.svg
Terminal=false
Categories=Utility;
StartupWMClass=$APP_ID
EOF
    command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP_FILE")" || true

    # A command-line launcher too, when ~/.local/bin is free to use for it.
    if [[ ! -e "$BIN_LINK" || -L "$BIN_LINK" ]]; then
        mkdir -p -- "$(dirname "$BIN_LINK")"
        ln -sfn -- "$target/pense-bete" "$BIN_LINK"
    fi

    info "$(t "$APP_NAME is installed in $target" "$APP_NAME est installé dans $target")"
    echo "$(t "    Launch it from the applications menu (search for \"$APP_NAME\")" "    Lancez-le depuis le menu des applications (cherchez « $APP_NAME »)")"
    echo "$(t "    or with the command: $APP_ID" "    ou avec la commande : $APP_ID")"
    echo "$(t "    To uninstall: $target/install.sh --uninstall${DEV:+ --dev}" "    Désinstallation : $target/install.sh --uninstall${DEV:+ --dev}")"
}

case "$ACTION" in
    uninstall) uninstall ;;
    help) sed -n '2,8p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//' ;;
    install) install "$TARGET" ;;
esac
