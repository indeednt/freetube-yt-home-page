#!/bin/sh
# Installs freetube-yt-home-page for the current user (no root needed):
#   - the script, to ~/.local/share/freetube-yt-home-page/
#   - the self-contained yt-dlp, to ~/.local/bin/ (only if you have none there)
#   - a copy of FreeTube's app-menu entry that starts FreeTube with the Home page
#
#   curl -fsSL https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/install.sh | sh
# or, from a clone of the repository:
#   sh install.sh
set -eu

REPO_RAW="https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
INSTALL_DIR="$HOME/.local/share/freetube-yt-home-page"
SCRIPT="$INSTALL_DIR/freetube_home.py"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }

download() {  # URL DESTINATION
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        die "curl or wget is needed to download $1"
    fi
}

[ "$(uname -s)" = Linux ] || die "only Linux is supported"
command -v python3 >/dev/null 2>&1 || die "python3 not found; install it with your package manager"
python3 -c 'import sys, sqlite3; sys.exit(sys.version_info < (3, 8))' 2>/dev/null \
    || die "Python 3.8 or newer (with sqlite3) is needed"

step "Checking FreeTube"
if command -v flatpak >/dev/null 2>&1 && flatpak info io.freetubeapp.FreeTube >/dev/null 2>&1; then
    say "found the Flatpak (io.freetubeapp.FreeTube)"
elif command -v freetube >/dev/null 2>&1; then
    say "found $(command -v freetube)"
else
    say "FreeTube was not found (neither the Flatpak nor a 'freetube' command)."
    say "Install it first (https://freetubeapp.io), for example:"
    say "  flatpak install flathub io.freetubeapp.FreeTube"
    say "For an AppImage, finish this install, then run:"
    say "  python3 \"$SCRIPT\" --install-launcher --freetube-path /path/to/FreeTube.AppImage"
fi

step "Installing the script to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# Run from a clone: use the script next to this file. Piped into sh: download it.
case "$0" in
    *install.sh) here=$(cd "$(dirname "$0")" && pwd) ;;
    *) here= ;;
esac
if [ -n "$here" ] && [ -f "$here/freetube_home.py" ]; then
    cp "$here/freetube_home.py" "$SCRIPT.new"
    say "copied from $here"
else
    download "$REPO_RAW/freetube_home.py" "$SCRIPT.new"
    say "downloaded from $REPO_RAW"
fi
python3 -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$SCRIPT.new" \
    || die "the downloaded script is damaged; please try again"
mv "$SCRIPT.new" "$SCRIPT"
chmod +x "$SCRIPT"

step "Checking yt-dlp"
if [ -x "$BIN_DIR/yt-dlp" ]; then
    say "using $BIN_DIR/yt-dlp"
else
    # The self-contained build: recent enough for YouTube, usable as a library
    # (needed for the topic chips), and the launcher can update it by itself.
    say "downloading the self-contained yt-dlp to $BIN_DIR/yt-dlp"
    mkdir -p "$BIN_DIR"
    download "$YTDLP_URL" "$BIN_DIR/yt-dlp.new"
    chmod +x "$BIN_DIR/yt-dlp.new"
    mv "$BIN_DIR/yt-dlp.new" "$BIN_DIR/yt-dlp"
fi

# Chrome-family browsers keep their cookie key in the desktop's keyring; outside
# KDE, yt-dlp reads it through the secretstorage module.
if ! python3 -c 'import secretstorage' >/dev/null 2>&1 && [ "${XDG_CURRENT_DESKTOP:-}" != KDE ]; then
    for d in "$HOME/.config/google-chrome" "$HOME/.config/chromium" "$HOME/.config/BraveSoftware" \
             "$HOME/.config/microsoft-edge" "$HOME/.config/vivaldi" "$HOME/.config/opera" \
             "$HOME/snap/chromium" "$HOME/.var/app/com.google.Chrome" "$HOME/.var/app/org.chromium.Chromium" \
             "$HOME/.var/app/com.brave.Browser" "$HOME/.var/app/com.microsoft.Edge"; do
        if [ -d "$d" ]; then
            say ""
            say "note: to use a Chrome-family browser's YouTube login, install python3-secretstorage:"
            say "  Debian/Ubuntu/Mint: sudo apt install python3-secretstorage"
            say "  Fedora:             sudo dnf install python3-secretstorage"
            say "  Arch:               sudo pacman -S python-secretstorage"
            say "(Firefox-family browsers don't need it.)"
            break
        fi
    done
fi

step "Adding the Home page to FreeTube's app-menu entry"
if ! python3 "$SCRIPT" --install-launcher; then
    say "No FreeTube app-menu entry to copy. Start FreeTube with the Home page by running:"
    say "  python3 \"$SCRIPT\" --launch"
fi

step "Checking your setup"
if python3 "$SCRIPT" --check; then
    say ""
    say "Done. Start FreeTube from your app menu; \"Home\" appears at the top of its sidebar."
    say "If FreeTube is open, quit it completely first (also from the tray, if you use it)."
else
    say ""
    say "Installed, but the item marked above needs fixing before the Home page can load."
    say "Run this again to re-check:  python3 \"$SCRIPT\" --check"
fi
say ""
say "Please read the Privacy section of the README:"
say "  https://github.com/indeednt/freetube-yt-home-page#privacy"
