#!/bin/sh
# Removes freetube-yt-home-page. FreeTube itself, its settings and its data are
# not touched; neither is yt-dlp in ~/.local/bin (other programs may use it).
#
#   curl -fsSL https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/uninstall.sh | sh
# or, from a clone of the repository:
#   sh uninstall.sh
set -eu

INSTALL_DIR="$HOME/.local/share/freetube-yt-home-page"
APPS="$HOME/.local/share/applications"
CACHE="$HOME/.cache/freetube_home"

# The app-menu entry: our copy of FreeTube's, recognisable by this marker line.
for f in "$APPS"/*.desktop; do
    if [ -f "$f" ] && grep -q '^X-FreeTube-Home-Launcher=true' "$f"; then
        rm -f "$f"
        echo "removed $f: the app menu starts plain FreeTube again"
    fi
done
if command -v update-desktop-database >/dev/null 2>&1 && [ -d "$APPS" ]; then
    update-desktop-database "$APPS" >/dev/null 2>&1 || true
fi

for d in "$INSTALL_DIR" "$CACHE"; do
    if [ -e "$d" ]; then
        rm -rf "$d"
        echo "removed $d"
    fi
done

echo
echo "Done. If FreeTube is open, restart it to remove the Home page from the sidebar."
echo "yt-dlp was left in ~/.local/bin; remove it with 'rm ~/.local/bin/yt-dlp' if nothing else needs it."
