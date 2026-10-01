#!/usr/bin/env bash
# Installs Pense-bête for the current user and registers it in the GNOME menu.
#
# Usage: ./install.sh [install-dir]   install (asks for the directory if not given)
#        ./install.sh --uninstall     remove the application, and on request its data
#        --purge                      with --uninstall: delete the notes and settings too
#        ./install.sh --dev           register this clone as "Pense-bête (dev)"
#        --yes                        ask nothing, take the default answers
#        --commit=<sha> --release=<tag>  what is installed, for a copy without git
#        --standalone                 the standalone version, without asking
#        --with-python                this computer's Python rather than the standalone version
#        --waitpid=<pid> --launch     wait for that process to end before installing,
#                                     then launch the application: for its own updates
#
# Also runs on its own, without a clone of the repository; it then installs the newest
# release, the highest vX.Y.Z tag, by default as the standalone version, which carries
# Python and PySide6:
#   curl -fsSL https://raw.githubusercontent.com/WatoLua/pense-bete/main/install.sh | bash
set -euo pipefail

ACTION=install
TARGET=""
ASSUME_YES=""
PURGE=""
DEV=""
COMMIT=""
RELEASE=""
STANDALONE=""
WITH_PYTHON=""
WAIT_PID=""
LAUNCH=""
REMOVE_SOURCE=""
for arg in "$@"; do
    case "$arg" in
        --uninstall) ACTION=uninstall ;;
        --purge) PURGE=1 ;;
        --dev) DEV=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        --commit=*) COMMIT="${arg#--commit=}" ;;
        --release=*) RELEASE="${arg#--release=}" ;;
        --standalone) STANDALONE=1 ;;
        --with-python) WITH_PYTHON=1 ;;
        --waitpid=*) WAIT_PID="${arg#--waitpid=}" ;;
        --launch) LAUNCH=1 ;;
        --removesource) REMOVE_SOURCE=1 ;;
        -h|--help) ACTION=help ;;
        *) TARGET="$arg" ;;
    esac
done

# The development version runs from a clone and has its own menu entry, command and
# notes (~/.local/share/pense-bete-dev), apart from the installed application.
APP_ID="pense-bete${DEV:+-dev}"
APP_NAME="Pense-bête${DEV:+ (dev)}"
REPO_URL="${PENSE_BETE_REPO:-https://github.com/WatoLua/pense-bete.git}"
# The standalone build's archive attached to each release, and its executable.
BUNDLE_ASSET="pense-bete-linux.tar.gz"
EXECUTABLE=pense-bete
is_bundle() {  # is_bundle <dir>: whether it holds a standalone build
    [[ -f "$1/$EXECUTABLE" && -d "$1/_internal" && ! -f "$1/pense_bete.py" ]]
}
# What to install: the sources, or a standalone build (BUNDLE), beside this script.
# Empty when the script is piped into bash: they are then downloaded.
SOURCE_DIR=""
BUNDLE=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SOURCE_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
    if is_bundle "$SOURCE_DIR"; then
        BUNDLE=1
    elif [[ ! -f "$SOURCE_DIR/pense_bete.py" ]]; then
        SOURCE_DIR=""
    fi
fi
WORK_DIR=""  # for downloads, deleted on exit
DEFAULT_DIR="$HOME/.local/opt/$APP_ID"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$APP_ID.desktop"
BIN_LINK="$HOME/.local/bin/$APP_ID"
# Where the application keeps its data, as pense_bete.py computes it.
DATA_DIR="${PENSE_BETE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
# The notes' directory chosen in the application, which its session records.
SESSION_FILE="$CONFIG_DIR/session.json"
if [[ -z "${PENSE_BETE_DIR:-}" && -f "$SESSION_FILE" ]] && command -v python3 >/dev/null; then
    chosen_dir="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("data_dir") or "")' "$SESSION_FILE" 2>/dev/null || true)"
    [[ -n "$chosen_dir" ]] && DATA_DIR="$chosen_dir"
fi
# Written by the application when it starts with the session.
AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP_ID.desktop"
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
    elif [[ -n "$install_dir" && ( -f "$install_dir/pense_bete.py" || -d "$install_dir/_internal" ) ]]; then
        if ask_yes "$(t "Delete $install_dir?" "Supprimer $install_dir ?")"; then
            rm -rf -- "$install_dir"
        fi
    fi
    rm -f -- "$DESKTOP_FILE" "$AUTOSTART_FILE"
    [[ -L "$BIN_LINK" ]] && rm -f -- "$BIN_LINK"
    command -v update-desktop-database >/dev/null && update-desktop-database "$(dirname "$DESKTOP_FILE")" || true
    if [[ -n "$purge" ]]; then
        delete_data
        info "$(t "$APP_NAME is uninstalled, with its notes and settings." "$APP_NAME est désinstallé, avec ses post-its et ses réglages.")"
    else
        info "$(t "$APP_NAME is uninstalled. Notes are kept in $DATA_DIR." "$APP_NAME est désinstallé. Les post-its sont conservés dans $DATA_DIR.")"
    fi
}

github_api() {  # the GitHub API address of REPO_URL, empty for a repository elsewhere
    local url="${REPO_URL%/}"
    url="${url%.git}"
    if [[ -n "${PENSE_BETE_API:-}" ]]; then
        printf '%s' "${PENSE_BETE_API%/}"
    elif [[ "$url" =~ ^https://github\.com/([^/]+)/([^/]+)$ ]]; then
        printf 'https://api.github.com/repos/%s/%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    fi
}

# Without git: the newest release through the GitHub API, its archive unpacked into $1.
# Prints its tag and commit.
download_release() {
    python3 - "$1" "$2" <<'PYTHON'
import io, json, re, shutil, sys, tempfile, urllib.request, zipfile
from pathlib import Path, PurePosixPath

target, api = Path(sys.argv[1]), sys.argv[2]

def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "pense-bete"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()

tags = [tag for tag in json.loads(get(api + "/tags?per_page=100"))
        if re.fullmatch(r"v\d+\.\d+\.\d+", tag["name"])]
if not tags:
    sys.exit("no release")
tag = max(tags, key=lambda tag: tuple(int(n) for n in tag["name"][1:].split(".")))
with zipfile.ZipFile(io.BytesIO(get(tag["zipball_url"]))) as archive:
    if any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts
           for n in archive.namelist()):
        sys.exit("unexpected archive")
    with tempfile.TemporaryDirectory() as temporary:
        archive.extractall(temporary)
        [top] = Path(temporary).iterdir()
        for item in top.iterdir():
            shutil.move(str(item), str(target / item.name))
print(tag["name"], tag["commit"]["sha"])
PYTHON
}

# The newest release's standalone build: GitHub sends this address on to the asset of
# the latest release, which is published with its builds. PENSE_BETE_API stands in for
# GitHub in the tests.
bundle_url() {
    local url="${REPO_URL%/}"
    url="${url%.git}"
    if [[ -n "${PENSE_BETE_API:-}" ]]; then
        printf '%s/releases/latest/download/%s' "${PENSE_BETE_API%/}" "$BUNDLE_ASSET"
    elif [[ "$url" =~ ^https://github\.com/[^/]+/[^/]+$ ]]; then
        printf '%s/releases/latest/download/%s' "$url" "$BUNDLE_ASSET"
    fi
}

# The standalone build, into $SOURCE_DIR: it carries its .version and .release.
download_bundle() {
    local url
    url="$(bundle_url)"
    [[ -n "$url" ]] || fail "$(t "The standalone version is only published on GitHub; use --with-python." "La version autonome n'est publiée que sur GitHub ; utilisez --with-python.")"
    info "$(t "Downloading the standalone version of Pense-bête from $REPO_URL" "Téléchargement de la version autonome de Pense-bête depuis $REPO_URL")"
    mkdir -p -- "$WORK_DIR/download"
    if command -v curl >/dev/null; then
        curl -fL --progress-bar -- "$url" | tar -xz -C "$WORK_DIR/download" \
            || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
    elif command -v wget >/dev/null; then
        wget -qO- -- "$url" | tar -xz -C "$WORK_DIR/download" \
            || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
    else
        fail "$(t "curl or wget is needed to download the application." "curl ou wget est nécessaire pour télécharger l'application.")"
    fi
    SOURCE_DIR="$WORK_DIR/download/$EXECUTABLE"
    is_bundle "$SOURCE_DIR" || fail "$(t "The download is not a standalone version of the application." "Le téléchargement n'est pas une version autonome de l'application.")"
    BUNDLE=1
    RELEASE="${RELEASE:-$(cat -- "$SOURCE_DIR/.release" 2>/dev/null || true)}"
    info "$(t "Pense-bête ${RELEASE:-} downloaded" "Pense-bête ${RELEASE:-} téléchargé")"
}

latest_release() {  # the newest vX.Y.Z tag of REPO_URL, empty when it has none
    git ls-remote --tags --refs -- "$REPO_URL" 'refs/tags/v*' 2>/dev/null \
        | sed -n 's#.*refs/tags/\(v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$#\1#p' \
        | sort -V | tail -n 1
}

# Only a warning: without it the application runs under Wayland, which does not restore
# window positions. A standalone build carries it when it was built where it was.
warn_without_xcb_cursor() {
    if [[ ! ( -n "$BUNDLE" && -e "$SOURCE_DIR/_internal/libxcb-cursor.so.0" ) ]] \
            && ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
        warn "$(t "libxcb-cursor0 is missing: windows will not reopen where they were. Install it with: sudo apt install libxcb-cursor0" "libxcb-cursor0 est absent : les fenêtres ne se rouvriront pas à leur place. Installez-le avec : sudo apt install libxcb-cursor0")"
    fi
}

check_dependencies() {
    # Only a warning: without git, notes are saved without history.
    command -v git >/dev/null || warn "$(t "git is not installed: notes will be saved without history. Install git to keep it." "git n'est pas installé : les post-its seront sauvegardés sans historique. Installez git pour le garder.")"

    if [[ -z "$SOURCE_DIR" ]]; then
        WORK_DIR="$(mktemp -d)"
        trap 'rm -rf -- "$WORK_DIR"' EXIT
        # The standalone version by default: it needs neither Python nor its libraries,
        # and downloads over HTTPS only.
        if [[ -z "$WITH_PYTHON" ]]; then
            if [[ -n "$STANDALONE" ]] || ! command -v python3 >/dev/null \
                    || ask_yes "$(t "Install the standalone version (recommended)? It carries Python and its libraries (about 75 MB); answer no to use this computer's Python instead." "Installer la version autonome (recommandé) ? Elle inclut Python et ses bibliothèques (environ 75 Mo) ; répondez non pour utiliser le Python de cet ordinateur.")"; then
                download_bundle
            fi
        fi
    fi
    if [[ -n "$BUNDLE" ]]; then
        warn_without_xcb_cursor
        return
    fi
    command -v python3 >/dev/null || fail "$(t "python3 not found, please install it first." "python3 est introuvable, installez-le d'abord.")"

    if [[ -z "$SOURCE_DIR" ]]; then
        SOURCE_DIR="$WORK_DIR/source"
        mkdir -- "$SOURCE_DIR"
        if command -v git >/dev/null; then
            local release
            release="$(latest_release)"
            if [[ -n "$release" ]]; then
                info "$(t "Downloading Pense-bête $release from $REPO_URL" "Téléchargement de Pense-bête $release depuis $REPO_URL")"
            else
                warn "$(t "$REPO_URL has no release yet: installing its latest commit." "$REPO_URL n'a encore aucune version publiée : installation de son dernier commit.")"
            fi
            git clone --quiet --depth 1 ${release:+--branch "$release"} -- "$REPO_URL" "$SOURCE_DIR" \
                || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
        else
            local api downloaded
            api="$(github_api)"
            [[ -n "$api" ]] || fail "$(t "Downloading from $REPO_URL needs git." "Le téléchargement depuis $REPO_URL nécessite git.")"
            info "$(t "Downloading the newest release of Pense-bête from $REPO_URL" "Téléchargement de la dernière version de Pense-bête depuis $REPO_URL")"
            downloaded="$(download_release "$SOURCE_DIR" "$api")" \
                || fail "$(t "Could not download the application." "Impossible de télécharger l'application.")"
            RELEASE="${downloaded% *}"
            COMMIT="${downloaded#* }"
            info "$(t "Pense-bête $RELEASE downloaded" "Pense-bête $RELEASE téléchargé")"
        fi
    fi

    warn_without_xcb_cursor

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
        if [[ -n "$(ls -A "$target")" && ! -f "$target/pense_bete.py" && ! -f "$target/$EXECUTABLE" ]]; then
            ask_yes "$(t "$target is not empty, install anyway?" "$target n'est pas vide, installer quand même ?")" || fail "$(t "Installation cancelled." "Installation annulée.")"
        fi
        info "$(t "Copying files to $target" "Copie des fichiers dans $target")"
        # What an earlier installation put there goes first, of either kind, so that
        # nothing of an earlier version is left behind, nor of the other kind.
        for item in "${FILES[@]}" "$PACKAGE" _internal .version .release; do
            rm -rf -- "${target:?}/$item"
        done
        if [[ -n "$BUNDLE" ]]; then
            cp -a -- "$SOURCE_DIR"/. "$target"/
        else
            for file in "${FILES[@]}"; do
                cp -- "$SOURCE_DIR/$file" "$target/"
            done
            mkdir -- "$target/$PACKAGE"
            cp -- "$SOURCE_DIR/$PACKAGE"/*.py "$target/$PACKAGE/"
        fi
    fi
    chmod +x "$target/$EXECUTABLE" "$target/install.sh"
    [[ -n "$BUNDLE" ]] || chmod +x "$target/pense_bete.py"
    # The installed commit, which the application compares with the repository to offer updates.
    # Given by --commit and --release for a copy git cannot tell about, as an archive; a
    # standalone build carries its own.
    if [[ -n "$BUNDLE" ]]; then
        [[ -z "$COMMIT" ]] || printf '%s\n' "$COMMIT" > "$target/.version"
        [[ -z "$RELEASE" ]] || printf '%s\n' "$RELEASE" > "$target/.release"
    elif [[ ! -e "$target/.git" ]]; then
        local commit="$COMMIT" release="$RELEASE"
        [[ -n "$commit" ]] || commit="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
        # And the release it is, when the commit is one, for the About window.
        [[ -n "$release" ]] || release="$(git -C "$SOURCE_DIR" describe --tags --exact-match \
            --match 'v[0-9]*' HEAD 2>/dev/null || true)"
        for record in ".version:$commit" ".release:$release"; do
            if [[ -n "${record#*:}" ]]; then
                printf '%s\n' "${record#*:}" > "$target/${record%%:*}"
            else
                rm -f -- "$target/${record%%:*}"
            fi
        done
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

    # For the application's own updates: the downloaded build goes, the new one starts.
    if [[ -n "$REMOVE_SOURCE" && "$SOURCE_DIR" != "$target" ]]; then
        rm -rf -- "$SOURCE_DIR"
        rmdir -- "$(dirname "$SOURCE_DIR")" 2>/dev/null || true
    fi
    if [[ -n "$LAUNCH" ]]; then
        setsid "$target/$EXECUTABLE" </dev/null >/dev/null 2>&1 &
    fi
}

# The application hands its update or uninstallation over and quits: its files are
# replaced once it is gone, two minutes at most. A process that has ended but that its
# parent has not collected yet, a zombie, is gone too.
wait_for_process() {
    local tries=0
    while [[ -n "$WAIT_PID" ]] && kill -0 "$WAIT_PID" 2>/dev/null \
            && [[ "$(ps -o stat= -p "$WAIT_PID" 2>/dev/null)" != Z* ]] && (( tries++ < 240 )); do
        sleep 0.5
    done
}

case "$ACTION" in
    uninstall) wait_for_process; uninstall ;;
    help) sed -n '2,14p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//' ;;
    install) wait_for_process; install "$TARGET" ;;
esac
