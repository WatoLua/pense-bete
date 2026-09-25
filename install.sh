#!/usr/bin/env bash
# Installs Pense-bête for the current user and registers it in the GNOME menu.
#
# Usage: ./install.sh [install-dir]   install (asks for the directory if not given)
#        ./install.sh --uninstall     remove the application (notes are kept)
#        ./install.sh --dev           register this clone as "Pense-bête (dev)"
#        --yes                        ask nothing, take the default answers
#
# Also runs on its own, without a clone of the repository:
#   curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
set -euo pipefail

ACTION=install
TARGET=""
ASSUME_YES=""
DEV=""
for arg in "$@"; do
    case "$arg" in
        --uninstall) ACTION=uninstall ;;
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
FILES=(pense_bete.py pense-bete icon.svg requirements.txt install.sh)

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

uninstall() {
    local exec_line install_dir=""
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
    info "$(t "$APP_NAME is uninstalled. Notes are kept in ~/.local/share/$APP_ID." "$APP_NAME est désinstallé. Les post-its sont conservés dans ~/.local/share/$APP_ID.")"
}

check_dependencies() {
    command -v python3 >/dev/null || fail "$(t "python3 not found, please install it first." "python3 est introuvable, installez-le d'abord.")"
    command -v git >/dev/null || fail "$(t "git not found, please install it first (it versions the notes)." "git est introuvable, installez-le d'abord (il versionne les post-its).")"

    if [[ -z "$SOURCE_DIR" ]]; then
        SOURCE_DIR="$(mktemp -d)"
        trap 'rm -rf -- "$SOURCE_DIR"' EXIT
        info "$(t "Downloading Pense-bête from $REPO_URL" "Téléchargement de Pense-bête depuis $REPO_URL")"
        git clone --quiet --depth 1 -- "$REPO_URL" "$SOURCE_DIR" \
            || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
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
    fi
    chmod +x "$target/pense-bete" "$target/pense_bete.py" "$target/install.sh"
    # The installed commit, which the application compares with the repository to offer updates.
    if [[ ! -e "$target/.git" ]]; then
        git -C "$SOURCE_DIR" rev-parse HEAD > "$target/.version" 2>/dev/null || rm -f -- "$target/.version"
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
    help) sed -n '2,7p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//' ;;
    install) install "$TARGET" ;;
esac
