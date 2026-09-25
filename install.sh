#!/usr/bin/env bash
# Installs Pense-bête for the current user and registers it in the GNOME menu.
#
# Usage: ./install.sh [install-dir]   install (asks for the directory if not given)
#        ./install.sh --uninstall     remove the application (notes are kept)
set -euo pipefail

APP_ID="pense-bete"
SOURCE_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
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

ask_yes() {  # ask_yes "question" -> true on yes, default yes
    local answer
    read -r -p "$1 $(t "[Y/n]" "[O/n]") " answer
    [[ -z "$answer" || "$answer" =~ ^[yYoO] ]]
}

uninstall() {
    local exec_line install_dir=""
    # The desktop entry records where the application was installed.
    if [[ -f "$DESKTOP_FILE" ]]; then
        exec_line="$(grep -m1 '^Exec=' "$DESKTOP_FILE" || true)"
        install_dir="$(dirname "${exec_line#Exec=}")"
    fi
    if [[ -n "$install_dir" && -f "$install_dir/pense_bete.py" ]]; then
        if ask_yes "$(t "Delete $install_dir?" "Supprimer $install_dir ?")"; then
            rm -rf -- "$install_dir"
        fi
    fi
    rm -f -- "$DESKTOP_FILE"
    [[ -L "$BIN_LINK" ]] && rm -f -- "$BIN_LINK"
    command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP_FILE")" || true
    info "$(t "Pense-bête is uninstalled. Notes are kept in ~/.local/share/pense-bete." "Pense-bête est désinstallé. Les post-its sont conservés dans ~/.local/share/pense-bete.")"
}

check_dependencies() {
    command -v python3 >/dev/null || fail "$(t "python3 not found, please install it first." "python3 est introuvable, installez-le d'abord.")"
    command -v git >/dev/null || fail "$(t "git not found, please install it first (it versions the notes)." "git est introuvable, installez-le d'abord (il versionne les post-its).")"

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
    check_dependencies
    if [[ -z "$target" ]]; then
        read -r -p "$(t "Installation directory [$DEFAULT_DIR]: " "Dossier d'installation [$DEFAULT_DIR] : ")" target
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

    info "$(t "Adding the entry to the applications menu" "Ajout de l'entrée dans le menu des applications")"
    mkdir -p -- "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Pense-bête
Comment=Sticky notes versioned with git
Comment[fr]=Post-its versionnés avec git
Exec=$target/pense-bete
Icon=$target/icon.svg
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

    info "$(t "Pense-bête is installed in $target" "Pense-bête est installé dans $target")"
    echo "$(t "    Launch it from the applications menu (search for \"Pense-bête\")" "    Lancez-le depuis le menu des applications (cherchez « Pense-bête »)")"
    echo "$(t "    or with the command: $APP_ID" "    ou avec la commande : $APP_ID")"
    echo "$(t "    To uninstall: $target/install.sh --uninstall" "    Désinstallation : $target/install.sh --uninstall")"
}

case "${1:-}" in
    --uninstall) uninstall ;;
    -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) install "${1:-}" ;;
esac
