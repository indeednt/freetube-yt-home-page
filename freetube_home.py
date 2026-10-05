#!/usr/bin/env python3
"""Put your personal YouTube home-page suggestions into FreeTube.

FreeTube never logs in to YouTube, so it has no personalised home feed.
This script fetches the feed as you, using the YouTube login cookies of
your browser, and either prints it or saves it as a FreeTube playlist
(default name: "YouTube Home"). Supported: Firefox, Zen, LibreWolf, Floorp,
Waterfox, Chrome, Chromium, Brave, Edge, Vivaldi and Opera — on Linux
(native, Snap or Flatpak installs) and Windows (where Chrome-family browsers
keep their cookies unreadable to other programs, so in practice only the
Firefox family works). By default the most recently used browser that is
logged in to YouTube is picked.

    python3 freetube_home.py --browser zen             # print the feed
    python3 freetube_home.py --browser zen --playlist  # save to FreeTube
    python3 freetube_home.py --launch                  # FreeTube with a Home page
    python3 freetube_home.py --install-launcher        # ...from the app menu too
    python3 freetube_home.py --check                   # what would be used

Needs a recent yt-dlp (install.sh / install.ps1 set one up). Close FreeTube before using --playlist:
FreeTube keeps its database in memory and would overwrite the change.

Cookie handling: only youtube.com cookies are used, copied into a private
temporary folder that is deleted afterwards. YouTube's short-lived "ST-*"
cookies are left out — they pile up in the browser (hundreds of KB) and make
YouTube reject the request with "HTTP Error 413". Chromium-family browsers
encrypt their cookies with a key kept in the desktop's keyring; yt-dlp reads
it from there (on GNOME-like desktops through python3-secretstorage).
"""

import argparse
import base64
import glob
import itertools
import json
import os
import pathlib
import select
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

WINDOWS = os.name == "nt"
LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
APPDATA = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
# Windows: everything of ours lives in one folder (script, yt-dlp, cache).
APP_HOME = os.path.join(LOCALAPPDATA, "freetube-yt-home-page")
# Console programs (yt-dlp, tasklist...) started from the windowless launcher
# would each flash a console window on Windows.
NO_WINDOW = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if WINDOWS else {}

if WINDOWS:
    FREETUBE_DIRS = [os.path.join(APPDATA, "FreeTube")]
    FIREFOX_BROWSERS = {
        "firefox": [
            os.path.join(APPDATA, r"Mozilla\Firefox\Profiles\*\cookies.sqlite"),
            # the Microsoft Store version
            os.path.join(LOCALAPPDATA, r"Packages\Mozilla.Firefox_*\LocalCache\Roaming\Mozilla"
                                       r"\Firefox\Profiles\*\cookies.sqlite"),
        ],
        "zen": [os.path.join(APPDATA, r"zen\Profiles\*\cookies.sqlite")],
        "librewolf": [os.path.join(APPDATA, r"librewolf\Profiles\*\cookies.sqlite")],
        "floorp": [os.path.join(APPDATA, r"Floorp\Profiles\*\cookies.sqlite")],
        "waterfox": [os.path.join(APPDATA, r"Waterfox\Profiles\*\cookies.sqlite")],
    }
    CHROMIUM_BROWSERS = {
        "chrome": ("chrome", [os.path.join(LOCALAPPDATA, r"Google\Chrome\User Data")]),
        "chromium": ("chromium", [os.path.join(LOCALAPPDATA, r"Chromium\User Data")]),
        "brave": ("brave", [os.path.join(LOCALAPPDATA, r"BraveSoftware\Brave-Browser\User Data")]),
        "edge": ("edge", [os.path.join(LOCALAPPDATA, r"Microsoft\Edge\User Data")]),
        "vivaldi": ("vivaldi", [os.path.join(LOCALAPPDATA, r"Vivaldi\User Data")]),
        "opera": ("opera", [os.path.join(APPDATA, r"Opera Software\Opera Stable")]),
    }
else:
    FREETUBE_DIRS = [
        "~/.var/app/io.freetubeapp.FreeTube/config/FreeTube",  # Flatpak
        "~/.config/FreeTube",  # deb / AppImage / AUR
    ]
    # Firefox-family browsers: where their profiles' cookies.sqlite live
    # (native install, Snap, Flatpak).
    FIREFOX_BROWSERS = {
        "firefox": [
            "~/.mozilla/firefox/*/cookies.sqlite",
            "~/snap/firefox/common/.mozilla/firefox/*/cookies.sqlite",
            "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
        ],
        "zen": [
            "~/.zen/*/cookies.sqlite",
            "~/.var/app/app.zen_browser.zen/.zen/*/cookies.sqlite",
        ],
        "librewolf": [
            "~/.librewolf/*/cookies.sqlite",
            "~/.var/app/io.gitlab.librewolf-community/.librewolf/*/cookies.sqlite",
        ],
        "floorp": [
            "~/.floorp/*/cookies.sqlite",
            "~/.var/app/one.ablaze.floorp/.floorp/*/cookies.sqlite",
        ],
        "waterfox": [
            "~/.waterfox/*/cookies.sqlite",
            "~/.var/app/net.waterfox.waterfox/.waterfox/*/cookies.sqlite",
        ],
    }
    # Chromium-family browsers: yt-dlp's name for each (it decrypts their cookies
    # with the key in the desktop's keyring), and their user-data dirs.
    CHROMIUM_BROWSERS = {
        "chrome": ("chrome", [
            "~/.config/google-chrome",
            "~/.var/app/com.google.Chrome/config/google-chrome",
        ]),
        "chromium": ("chromium", [
            "~/.config/chromium",
            "~/snap/chromium/common/chromium",
            "~/.var/app/org.chromium.Chromium/config/chromium",
            "~/.var/app/io.github.ungoogled_software.ungoogled_chromium/config/chromium",
        ]),
        "brave": ("brave", [
            "~/.config/BraveSoftware/Brave-Browser",
            "~/snap/brave/current/.config/BraveSoftware/Brave-Browser",
            "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
        ]),
        "edge": ("edge", [
            "~/.config/microsoft-edge",
            "~/.var/app/com.microsoft.Edge/config/microsoft-edge",
        ]),
        "vivaldi": ("vivaldi", [
            "~/.config/vivaldi",
            "~/snap/vivaldi/current/.config/vivaldi",
            "~/.var/app/com.vivaldi.Vivaldi/config/vivaldi",
        ]),
        "opera": ("opera", [
            "~/.config/opera",
            "~/snap/opera/current/.config/opera",
            "~/.var/app/com.opera.Opera/config/opera",
        ]),
    }
# The cookie database sits in a profile dir (Default, Profile 1...), or directly
# in the user-data dir for browsers without profiles (Opera).
CHROMIUM_COOKIE_FILES = ["*/Network/Cookies", "*/Cookies", "Network/Cookies", "Cookies"]
BROWSERS = [*FIREFOX_BROWSERS, *CHROMIUM_BROWSERS]
# A YouTube login. The third-party variants (__Secure-3P*) aren't enough: a
# browser signed in only to Google gets them from embedded videos.
LOGIN_COOKIES = ("SAPISID", "__Secure-1PAPISID")
STALE_PROFILE_DAYS = 7


class FeedError(Exception):
    """Fetching the feed failed, with a message meant for the user."""


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


# --- Cookies -----------------------------------------------------------------

def cookie_dbs(browser):
    """[(browser, cookie database)] for one browser, or every known one."""
    found = []
    for name in (BROWSERS if browser == "auto" else [browser]):
        if name in FIREFOX_BROWSERS:
            patterns = FIREFOX_BROWSERS[name]
        else:
            patterns = [os.path.join(d, f) for d in CHROMIUM_BROWSERS[name][1] for f in CHROMIUM_COOKIE_FILES]
        found += [(name, p) for g in patterns for p in glob.glob(os.path.expanduser(g))]
    return found


def has_youtube_login(name, path):
    """Whether a cookie database holds a YouTube login (cookie names aren't encrypted)."""
    table, host = ("moz_cookies", "host") if name in FIREFOX_BROWSERS else ("cookies", "host_key")
    try:  # immutable: read the live file without locking it or touching its journal
        con = sqlite3.connect(pathlib.Path(path).as_uri() + "?immutable=1", uri=True)
        try:
            return con.execute(
                f"SELECT 1 FROM {table} WHERE {host} LIKE '%youtube.com' AND name IN (?, ?) LIMIT 1",
                LOGIN_COOKIES).fetchone() is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False


def find_cookie_db(browser, profile):
    """(browser, cookie database) to read the YouTube login from."""
    if profile:
        profile = os.path.expanduser(profile)
        if os.path.exists(os.path.join(profile, "cookies.sqlite")):
            return ("firefox" if browser in ("auto", *CHROMIUM_BROWSERS) else browser,
                    os.path.join(profile, "cookies.sqlite"))
        for f in ("Network/Cookies", "Cookies"):
            if os.path.exists(os.path.join(profile, f)):
                return ("chrome" if browser in ("auto", *FIREFOX_BROWSERS) else browser,
                        os.path.join(profile, f))
        raise FeedError(f"no browser cookies in {profile}")
    found = cookie_dbs(browser)
    if not found:
        raise FeedError(f"no {'supported browser' if browser == 'auto' else browser} profile found;"
                        " pass --browser or --profile DIR")
    # The most recently written profile is the one you actually use; with
    # several browsers, the most recent one that is logged in to YouTube.
    found.sort(key=lambda f: os.path.getmtime(f[1]), reverse=True)
    if browser == "auto":
        found = [f for f in found if has_youtube_login(*f)] or found
    name, path = found[0]
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days > STALE_PROFILE_DAYS:
        # An old profile means an expired login: YouTube then answers with a
        # consent page and an empty, logged-out feed instead of an error.
        print(f"warning: this {name} profile was last used "
              f"{time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(path)))}"
              f" ({path}); its YouTube login has probably expired. Use --browser for the"
              " browser you actually use.", file=sys.stderr)
    return name, path


# Cookies worth reporting in --debug (names, places and dates only — never values).
KEY_COOKIES = ("SOCS", "CONSENT", "PREF", "LOGIN_INFO", "SID", "SAPISID",
               "__Secure-3PSID", "__Secure-3PAPISID", "__Secure-1PSIDTS", "__Secure-3PSIDTS")


def firefox_youtube_cookies(cookie_db, workdir):
    """[(host, path, secure, expiry, name, value, context)] from a Firefox-family profile."""
    # Firefox locks the live database, so read a copy. The -wal file holds its
    # most recent writes — without it, rotated login cookies come out stale.
    db_copy = os.path.join(workdir, "cookies.sqlite")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(cookie_db + suffix):
            shutil.copy(cookie_db + suffix, db_copy + suffix)
    con = sqlite3.connect(db_copy)
    try:
        columns = {r[1] for r in con.execute("PRAGMA table_info(moz_cookies)")}
        context = "originAttributes" if "originAttributes" in columns else "''"
        rows = con.execute(
            f"SELECT host, path, isSecure, expiry, name, value, {context} FROM moz_cookies"
            " WHERE host LIKE ? AND name NOT LIKE ?",
            ("%youtube.com", "ST-%"),
        ).fetchall()
    finally:
        con.close()
    # newer Firefox stores milliseconds
    return [(h, p, s, e // 1000 if e > 10**11 else e, n, v, c) for h, p, s, e, n, v, c in rows]


class _CookieLogger:
    """Quiet logger for yt-dlp's cookie reader that remembers what went wrong."""

    def __init__(self):
        self.problems = []

    def debug(self, message, only_once=False):
        pass

    def info(self, message, only_once=False):
        pass

    def warning(self, message, only_once=False):
        self.problems.append(message)

    def error(self, message, only_once=False):
        self.problems.append(message)


def chromium_youtube_cookies(browser, cookie_db):
    """The same rows from a Chromium-family profile. Its cookie values are
    encrypted with a key kept in the desktop's keyring (GNOME Keyring, KWallet...);
    yt-dlp knows how to get it and decrypt them."""
    yt_dlp = import_yt_dlp()
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except ImportError:
        yt_dlp = None
    if yt_dlp is None:
        raise FeedError(f"reading {browser}'s cookies needs yt-dlp's self-contained version"
                        f" ({'install.ps1' if WINDOWS else 'install.sh'} sets it up)")
    profile_dir = os.path.dirname(cookie_db)
    if os.path.basename(profile_dir) == "Network":
        profile_dir = os.path.dirname(profile_dir)
    logger = _CookieLogger()
    try:
        jar = extract_cookies_from_browser(CHROMIUM_BROWSERS[browser][0], profile_dir, logger)
    except Exception as e:
        raise FeedError(f"could not read {browser}'s cookies: {e}")
    rows = [(c.domain, c.path, c.secure, c.expires or 0, c.name, c.value, "")
            for c in jar if c.domain.endswith("youtube.com") and not c.name.startswith("ST-")
            and c.value is not None]
    if logger.problems and not any(r[4] in LOGIN_COOKIES for r in rows) and has_youtube_login(browser, cookie_db):
        if WINDOWS:
            hint = (" On Windows, Chrome-family browsers protect their cookies from other programs"
                    " (app-bound encryption) and lock them while running; use a Firefox-family"
                    " browser for the YouTube login instead.")
        else:
            hint = (" Its key is in your desktop's keyring; on GNOME-like desktops yt-dlp needs"
                    " the python3-secretstorage package for that.")
        raise FeedError(f"could not decrypt {browser}'s cookies: {logger.problems[-1]}.{hint}")
    return rows


def write_youtube_cookie_file(found, workdir, debug=False):
    """Copy a browser's youtube.com cookies (minus ST-*) to a Netscape cookie file."""
    browser, cookie_db = found
    if browser in FIREFOX_BROWSERS:
        all_rows = firefox_youtube_cookies(cookie_db, workdir)
    else:
        all_rows = chromium_youtube_cookies(browser, cookie_db)
    # Normal tabs only: Firefox's container tabs and partitioned (embedded)
    # cookies carry originAttributes, and mixing them in sends two conflicting logins.
    rows = [r[:6] for r in all_rows if not r[6]]

    if debug:
        print(f"[debug] browser cookies: {browser} {cookie_db}", file=sys.stderr)
        contexts = sorted({r[6] for r in all_rows})
        print(f"[debug] {len(rows)} youtube cookies in normal tabs; contexts present: "
              f"{', '.join(repr(c) for c in contexts)}", file=sys.stderr)
        for host, _, _, expiry, name, _, ctx in sorted(all_rows, key=lambda r: (r[4], r[6])):
            if name in KEY_COOKIES:
                when = time.strftime("%Y-%m-%d", time.localtime(expiry)) if expiry else "session"
                print(f"[debug]   {name:<18} {host:<16} context={ctx or 'normal'!s:<10} expires {when}",
                      file=sys.stderr)

    if not any(r[4] in LOGIN_COOKIES for r in rows):
        if any(r[4] in LOGIN_COOKIES for r in all_rows):
            raise FeedError("your YouTube login is only in a container tab; log in to"
                 " youtube.com in a normal tab")
        raise FeedError(f"no YouTube login found in {browser} ({cookie_db}) — sign in on"
                        " youtube.com in that browser first (being signed in to Google isn't"
                        " enough), or pick another with --browser")

    path = os.path.join(workdir, "youtube_cookies.txt")
    with open(path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for host, cpath, secure, expiry, name, value in rows:
            f.write("\t".join([
                host,
                "TRUE" if host.startswith(".") else "FALSE",
                cpath,
                "TRUE" if secure else "FALSE",
                str(int(expiry)),
                name,
                value,
            ]) + "\n")
    return path


# --- Fetching ----------------------------------------------------------------

def summarize_pages(pages_dir):
    """Describe what YouTube actually sent back, without printing the pages."""
    markers = {
        "ytInitialData": "ytInitialData",
        "consent page": "consent.youtube.com",
        "Google sign-in": "accounts.google.com/ServiceLogin",
        "logged in": '"LOGGED_IN":true',
        "logged out": '"LOGGED_IN":false',
        "empty-feed message": "feedNudgeRenderer",
        "videoId mentions": '"videoId"',
        "richItemRenderer": "richItemRenderer",
        "lockupViewModel": "lockupViewModel",
    }
    for name in sorted(os.listdir(pages_dir)):
        with open(os.path.join(pages_dir, name), encoding="utf-8", errors="replace") as f:
            body = f.read()
        title = body.split("<title>", 1)[1].split("</title>", 1)[0][:80] if "<title>" in body else "-"
        found = ", ".join(f"{k}={body.count(v)}" for k, v in markers.items() if v in body)
        print(f"[debug] page {name[:60]}: {len(body)} bytes, title={title!r}; {found or 'no markers'}",
              file=sys.stderr)


if WINDOWS:  # the self-contained build that install.ps1 puts next to the script
    YT_DLP_CANDIDATES = [os.path.join(APP_HOME, "yt-dlp")]
else:
    YT_DLP_CANDIDATES = ["~/.local/bin/yt-dlp", "~/bin/yt-dlp", "/usr/local/bin/yt-dlp", "/usr/bin/yt-dlp"]
_yt_dlp_path = []


def console_python():
    """python.exe rather than the windowless pythonw.exe the launcher runs under."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe") and os.path.exists(exe[:-5] + ".exe"):
        return exe[:-5] + ".exe"
    return exe


def ytdlp_command(path):
    """How to run a yt-dlp: Windows can't start the self-contained (zip) build
    directly, so it is handed to Python."""
    if WINDOWS and zipfile.is_zipfile(path):
        return [console_python(), path]
    return [path]


def find_yt_dlp():
    """The newest yt-dlp installed. Not simply the one on PATH: started from the
    app menu, PATH often lacks ~/.local/bin, and a distro's copy is usually
    too old for YouTube's current pages."""
    if not _yt_dlp_path:
        found = {}
        for c in [shutil.which("yt-dlp"), *map(os.path.expanduser, YT_DLP_CANDIDATES)]:
            if c and os.path.isfile(c) and (WINDOWS or os.access(c, os.X_OK)):
                found.setdefault(os.path.realpath(c), c)

        def version(path):
            try:
                out = subprocess.run(ytdlp_command(path) + ["--version"], capture_output=True,
                                     text=True, timeout=30, **NO_WINDOW)
                return out.stdout.strip()  # e.g. 2026.08.19: compares correctly as text
            except (OSError, subprocess.SubprocessError):
                return ""

        _yt_dlp_path.append(max(found.values(), key=version) if found else None)
    return _yt_dlp_path[0]


def fetch_entries(cookie_file, count, url=":ytrec", debug=False):
    """Return the feed's videos as yt-dlp flat-playlist entries."""
    ytdlp = find_yt_dlp()
    if not ytdlp:
        raise FeedError("yt-dlp not found on PATH")
    options = ["--flat-playlist", "-J", "--playlist-end", str(count)]
    if cookie_file:
        options += ["--cookies", cookie_file]
    pages_dir = None
    if debug:
        pages_dir = tempfile.mkdtemp(prefix="freetube_home-pages-")
        options += ["--verbose", "--write-pages"]
    cmd = ytdlp_command(ytdlp) + options + [url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=pages_dir,
                                timeout=180, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise FeedError("yt-dlp took longer than 3 minutes; try again")
    if debug:
        # yt-dlp's verbose log; it names the cookie file but never prints its contents
        sys.stderr.write(result.stderr)
        summarize_pages(pages_dir)
        shutil.rmtree(pages_dir)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        last = [l for l in result.stderr.splitlines() if l.strip()][-1:] or ["no output"]
        raise FeedError(f"yt-dlp failed: {last[0]}")
    data = json.loads(result.stdout)
    if debug:
        raw = data.get("entries") or []
        print(f"[debug] yt-dlp returned {len(raw)} raw entries", file=sys.stderr)
        for e in raw[:5]:
            print(f"[debug]   {e.get('ie_key')} id={e.get('id')} url={e.get('url')}", file=sys.stderr)
    entries, seen = [], set()
    for e in data.get("entries") or []:
        vid = e.get("id")
        if not vid or vid in seen or len(vid) != 11:  # skip non-videos and repeats
            continue
        seen.add(vid)
        entries.append(e)
    return entries


# --- FreeTube playlist ---------------------------------------------------------

def freetube_running():
    if WINDOWS:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FreeTube.exe", "/NH"],
                             capture_output=True, text=True, **NO_WINDOW).stdout
        return "freetube.exe" in out.lower()
    return subprocess.run(["pgrep", "-x", "freetube"], capture_output=True).returncode == 0


def find_playlists_db(freetube_dir):
    dirs = [freetube_dir] if freetube_dir else FREETUBE_DIRS
    for d in dirs:
        path = os.path.join(os.path.expanduser(d), "playlists.db")
        if os.path.exists(path):
            return path
    fail("FreeTube's playlists.db not found; pass --freetube-dir DIR")


def to_freetube_video(entry, now_ms):
    video = {
        "videoId": entry["id"],
        "title": entry.get("title") or "",
        "author": entry.get("channel") or entry.get("uploader") or "",
        "authorId": entry.get("channel_id") or "",
        "lengthSeconds": int(entry.get("duration") or 0),
        "timeAdded": now_ms,
        "playlistItemId": str(uuid.uuid4()),
        "type": "video",
    }
    if entry.get("timestamp"):
        video["published"] = int(entry["timestamp"]) * 1000
    return video


def save_playlist(db_path, name, entries):
    """Create or replace the named playlist in FreeTube's NeDB playlists.db.

    NeDB is an append-only file of JSON lines where a later line with the same
    _id replaces an earlier one and {"$$deleted": true} removes it. Rather than
    append, the file is rewritten compacted — what NeDB itself does on load —
    after a backup copy to playlists.db.bak.
    """
    meta_lines, docs = [], {}
    with open(db_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            if "$$indexCreated" in doc or "$$indexRemoved" in doc:
                meta_lines.append(line)
            elif doc.get("$$deleted"):
                docs.pop(doc["_id"], None)
            else:
                docs[doc["_id"]] = doc

    now_ms = int(time.time() * 1000)
    existing = next((d for d in docs.values() if d.get("playlistName") == name), None)
    playlist = {
        "playlistName": name,
        "protected": False,
        "description": "Your YouTube home page, fetched by freetube_home.py",
        "videos": [to_freetube_video(e, now_ms) for e in entries],
        "_id": existing["_id"] if existing else f"ft-playlist--{uuid.uuid4()}",
        "createdAt": existing["createdAt"] if existing else now_ms,
        "lastUpdatedAt": now_ms,
    }
    docs[playlist["_id"]] = playlist

    shutil.copy2(db_path, db_path + ".bak")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(db_path), prefix=".playlists.db.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for line in meta_lines:
            f.write(line + "\n")
        for doc in docs.values():
            f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.chmod(tmp, os.stat(db_path).st_mode & 0o777)
    os.replace(tmp, db_path)
    return "updated" if existing else "created"


def load_feed(browser, profile, count):
    """Fetch the home feed and reduce it to what the Home page shows."""
    with tempfile.TemporaryDirectory(prefix="freetube_home-") as workdir:
        cookie_file = write_youtube_cookie_file(find_cookie_db(browser, profile), workdir)
        entries = fetch_entries(cookie_file, count)
    if not entries:
        raise FeedError("YouTube returned no videos. Check youtube.com in your browser: if it"
                        " says your watch history is off, YouTube shows no suggestions at all.")
    return [video_from_entry(e) for e in entries]


def video_from_entry(e):
    return {
        "id": e["id"],
        "title": e.get("title") or "",
        "channel": e.get("channel") or e.get("uploader") or "",
        "channelId": e.get("channel_id") or "",
        "duration": int(e.get("duration") or 0),
        "views": e.get("view_count"),
    }


def import_yt_dlp():
    """yt-dlp as a library: the newest one (its zipapp is importable), else an installed one."""
    exe = find_yt_dlp()
    if exe and zipfile.is_zipfile(exe) and exe not in sys.path:
        sys.path.insert(0, exe)
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        return None


class _YtdlpLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        log(f"yt-dlp: {msg}")

    def error(self, msg):
        log(f"yt-dlp: {msg}")


def make_ydl(yt_dlp, browser, profile):
    with tempfile.TemporaryDirectory(prefix="freetube_home-") as workdir:
        cookie_file = write_youtube_cookie_file(find_cookie_db(browser, profile), workdir)
        ydl = yt_dlp.YoutubeDL({
            "quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "cookiefile": cookie_file, "logger": _YtdlpLogger(),
        })
        ydl.cookiejar  # read the cookies now: the file is deleted when this block ends
        ydl.params["cookiefile"] = None  # ...and never write them back
    add_view_counts(yt_dlp, ydl)
    return ydl


def add_view_counts(yt_dlp, ydl):
    """Fill in the view counts yt-dlp misses on home-page video cards.

    YouTube now puts them in the channel's row ("Channel · 70K · 7d ago"),
    marked by a play-arrow icon, where yt-dlp doesn't look. If yt-dlp's
    internals change, the cards are simply shown without views.
    """
    try:
        ie = ydl.get_info_extractor("YoutubeTab")
        original = ie._extract_lockup_view_model
        parse_count = yt_dlp.utils.parse_count
    except Exception:
        return

    def extract(view_model):
        entry = original(view_model)
        if entry and entry.get("view_count") is None:
            rows = (view_model.get("metadata", {}).get("lockupMetadataViewModel", {}).get("metadata", {})
                    .get("contentMetadataViewModel", {}).get("metadataRows") or [])
            for part in (p for row in rows for p in row.get("metadataParts") or []):
                if "PLAY_ARROW" in (part.get("leadingIcon") or {}).get("name", ""):
                    entry["view_count"] = parse_count((part.get("text") or {}).get("content"))
                    break
        return entry

    ie._extract_lockup_view_model = extract


class FeedStream:
    """One load of a feed, continued page by page like YouTube's own scrolling."""

    def __init__(self, entries):
        self.entries = iter(entries)
        self.exhausted = False

    @classmethod
    def recommended(cls, yt_dlp, browser, profile):
        """The home feed through yt-dlp's public API: no topic chips, but the
        least likely to break when yt-dlp changes."""
        ydl = make_ydl(yt_dlp, browser, profile)
        try:
            result = ydl.extract_info(":ytrec", download=False, process=False)
            for _ in range(3):  # :ytrec -> feed/recommended -> the feed itself
                if result.get("_type") not in ("url", "url_transparent"):
                    break
                result = ydl.extract_info(result["url"], ie_key=result.get("ie_key"),
                                          download=False, process=False)
        except Exception as e:
            raise FeedError(f"yt-dlp failed: {e}")
        return cls(result.get("entries") or [])

    def take(self, n, seen):
        """Up to n more videos whose ids aren't in seen (which is updated)."""
        videos = []
        try:
            for e in self.entries:
                vid = e.get("id")
                if vid and len(vid) == 11 and vid not in seen:
                    seen.add(vid)
                    videos.append(video_from_entry(e))
                    if len(videos) >= n:
                        return videos
        except Exception as e:
            raise FeedError(f"loading more failed: {e}")
        self.exhausted = True
        return videos


class HomeSession:
    """One load of youtube.com's home page: its "All" feed and its topic chips
    (Music, Podcasts, Gaming...), which YouTube picks per user.

    yt-dlp has no option for the chips, so this uses its YouTube extractor's
    internal methods; if they change, the launcher falls back to FeedStream.recommended.
    """

    def __init__(self, yt_dlp, browser, profile):
        ydl = make_ydl(yt_dlp, browser, profile)
        try:
            ie = self.ie = ydl.get_info_extractor("YoutubeTab")
            ie.initialize()
            data, self.ytcfg = ie._extract_data("https://www.youtube.com/feed/recommended", "home")
            self.tab = ie._extract_selected_tab(ie._extract_tab_renderers(data))
            self.session_id = ie._extract_delegated_session_id(self.ytcfg, data)
            self.visitor_data = ie._extract_visitor_data(data, self.ytcfg)
        except Exception as e:
            raise FeedError(f"yt-dlp failed: {e}")
        self.created = time.time()
        self.home_used = False
        # [(label, continuation token)]; the selected first one ("All") has no token.
        self.chips = []
        bar = (self.tab.get("content", {}).get("richGridRenderer", {})
               .get("header", {}).get("feedFilterChipBarRenderer", {}))
        for item in bar.get("contents") or []:
            chip = item.get("chipCloudChipRenderer") or {}
            text = chip.get("text") or {}
            label = text.get("simpleText") or "".join(r.get("text", "") for r in text.get("runs") or [])
            token = (chip.get("navigationEndpoint") or {}).get("continuationCommand", {}).get("token")
            if label and (token or chip.get("isSelected")):
                self.chips.append((label, None if chip.get("isSelected") else token))

    def chip_list(self):
        """The chips as the page shows them; the key "" is the "All" feed."""
        if len(self.chips) < 2:
            return []
        return [{"key": "" if token is None else label, "label": label} for label, token in self.chips]

    def _entries(self, tab):
        return self.ie._entries(tab, "home", self.ytcfg, self.session_id, self.visitor_data)

    def stream(self, key):
        if not key:
            self.home_used = True
            return FeedStream(self._entries(self.tab))
        token = next((t for label, t in self.chips if label == key and t), None)
        if not token:
            raise FeedError(f"“{key}” isn't among YouTube's topics for you right now;"
                            " refresh “All” to get the current ones")
        try:
            response = self.ie._extract_response(
                item_id=f"home: {key}", query={"continuation": token}, ep="browse", ytcfg=self.ytcfg,
                headers=self.ie.generate_api_headers(ytcfg=self.ytcfg, delegated_session_id=self.session_id,
                                                     visitor_data=self.visitor_data))
        except Exception as e:
            raise FeedError(f"loading “{key}” failed: {e}")
        # Picking a chip replaces the page body ("slot") with the topic's feed.
        items = next((c.get("continuationItems") for action in response.get("onResponseReceivedActions") or []
                      for c in [action.get("reloadContinuationItemsCommand") or {}]
                      if c.get("slot") == "RELOAD_CONTINUATION_SLOT_BODY"), None) or []
        return FeedStream(self._entries({"content": {"richGridRenderer": {"contents": items}}}))


# --- Home page inside FreeTube ---------------------------------------------------
#
# --launch starts FreeTube with Chromium's standard remote-debugging switch and
# adds the Home page through the DevTools protocol. Nothing inside FreeTube is
# modified, and FreeTube's internals are touched as little as possible, so an
# update degrades the page rather than breaking FreeTube:
#   - The page is drawn by us, in a shadow root: FreeTube's CSS can't restyle it.
#   - It is reached through Vue Router's public API (addRoute/push/afterEach), so
#     Back/Forward work. The save buttons dispatch the same Vuex actions as
#     FreeTube's own video cards, and are simply left out if those are missing. If the router can't be found, the page still opens as
#     an overlay, and videos open through FreeTube's own youtube.com link handling.
#   - The sidebar entry is a copy of an existing one; if the sidebar can't be
#     found, a floating "Home" button appears instead.
#   - Colours are read from FreeTube's theme at runtime, with fallbacks.
#   - The topic chips (All, Music, Podcasts...) are YouTube's own for your account;
#     if they can't be read, the page shows the plain feed without them.
# If DevTools never comes up, FreeTube simply runs without the Home page.

FLATPAK_ID = "io.freetubeapp.FreeTube"
BRIDGE = "__ftHomeBridge"
CACHE_DIR = os.path.join(APP_HOME, "cache") if WINDOWS else os.path.expanduser("~/.cache/freetube_home")
FEED_CACHE = os.path.join(CACHE_DIR, "feed.json")
LAUNCH_LOG = os.path.join(CACHE_DIR, "launcher.log")
STALE_FEED_SECONDS = 30 * 60
SESSION_MAX_AGE = 10 * 60  # how long the chips of one home page load are reused
PAGE_SIZE = 30  # videos per load, like one screenful of scrolling on youtube.com
MAX_CACHED = 600
# Bump when the cached feed gains fields (chips, views...): an older cache is then
# reloaded right away instead of being shown for up to STALE_FEED_SECONDS.
CACHE_VERSION = 2

HOME_PAGE_JS = r"""
(() => {
  if (window.__ftHome || window.top !== window) return;  // main window only, not FreeTube's helper frames
  const BRIDGE = %BRIDGE%;
  const ROUTE = '/youtube-home';
  const ROUTE_NAME = 'ftYoutubeHome';
  const STALE_MS = %STALE_MS%;
  const SIDE = ['.sideNav', '[class*="sideNav"]', 'nav'];
  const TOP = ['.topNav', '[class*="topNav"]', 'header'];
  const VIEW = ['.routerView', '[class*="routerView"]', 'main'];
  const THEME_VARS = ['--bg-color', '--card-bg-color', '--secondary-card-bg-color', '--primary-text-color',
    '--secondary-text-color', '--tertiary-text-color', '--accent-color', '--text-with-accent-color',
    '--side-nav-hover-color', '--side-nav-active-color', '--side-nav-hover-text-color', '--favorite-icon-color'];
  const HOUSE = '<path fill="currentColor" d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/>';
  const ICONS = {
    plus: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z',
    bookmark: 'M17 3H7c-1.1 0-2 .9-2 2v16l7-3 7 3V5c0-1.1-.9-2-2-2z',
    check: 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z',
  };

  const state = { videos: null, fetchedAt: 0, loading: false, error: '', shown: false,
    loadingMore: false, moreError: '', chip: '', chips: [] };
  let router = null, store = null, i18n = null, entry = null, floating = null, renderedFor;

  const send = (msg) => { try { window[BRIDGE](JSON.stringify(msg)); } catch (e) { /* launcher gone */ } };
  const first = (sels) => { for (const s of sels) { const el = document.querySelector(s); if (el) return el; } return null; };

  // --- the page: our own DOM in a shadow root -------------------------------
  const host = document.createElement('div');
  host.setAttribute('data-ft-home-page', '');
  host.style.cssText = 'position:fixed;z-index:3;display:none;overflow-y:auto;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>
    .page { min-height: 100%; box-sizing: border-box; padding: 16px 24px 40px;
      background: var(--bg-color, var(--fth-bg, #181818)); color: var(--primary-text-color, var(--fth-fg, #eee));
      font-family: var(--fth-font, sans-serif); }
    .bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    h1 { font-size: 1.4em; margin: 0; font-weight: 600; }
    .meta { flex: 1; color: var(--secondary-text-color, #aaa); font-size: .85em; }
    button { background: var(--accent-color, #f44336); color: var(--text-with-accent-color, #fff); border: 0;
      border-radius: 4px; padding: 8px 16px; font: inherit; cursor: pointer; }
    button:disabled { opacity: .6; cursor: default; }
    .chips { position: sticky; top: 0; z-index: 2; display: flex; gap: 12px; overflow-x: auto;
      margin: -8px -24px 8px; padding: 8px 24px; scrollbar-width: none;
      background: var(--bg-color, var(--fth-bg, #181818)); }
    .chips:empty { display: none; }
    .chips::-webkit-scrollbar { display: none; }
    .chips button { flex: none; padding: 6px 12px; border-radius: 8px; font-size: .9em; font-weight: 500;
      background: var(--card-bg-color, rgba(127, 127, 127, .2)); color: var(--primary-text-color, #eee);
      transition: background .15s ease-out; }
    .chips button:hover { background: var(--side-nav-hover-color, rgba(127, 127, 127, .35)); }
    .chips button.on { background: var(--primary-text-color, #eee); color: var(--bg-color, #181818); cursor: default; }
    .msg { color: var(--secondary-text-color, #aaa); margin: 0 0 16px; }
    .msg:empty { display: none; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
    .card { cursor: pointer; border-radius: 8px; padding: 6px; outline: none; }
    .card:hover, .card:focus-visible { background: var(--side-nav-hover-color, rgba(127, 127, 127, .15)); }
    .thumb { position: relative; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden;
      background: var(--card-bg-color, #222); }
    .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .dur { position: absolute; right: 6px; bottom: 6px; background: rgba(0, 0, 0, .8); color: #fff;
      font-size: .75em; padding: 1px 5px; border-radius: 4px; }
    .title { margin: 8px 0 4px; font-weight: 600; font-size: .95em; line-height: 1.3; display: -webkit-box;
      -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .sub { color: var(--secondary-text-color, #aaa); font-size: .85em; }
    .channel:hover { color: var(--primary-text-color, #eee); text-decoration: underline; }
    .icons { position: absolute; top: 4px; right: 4px; display: flex; gap: 4px; }
    .icons button { width: 30px; height: 30px; padding: 6px; border-radius: 50%; display: grid; place-items: center;
      background: var(--card-bg-color, #222); color: var(--primary-text-color, #eee); opacity: 0;
      transition: opacity .2s linear, background .15s ease-out; }
    .icons button svg { width: 18px; height: 18px; }
    .icons button:hover, .icons button:focus-visible { background: var(--side-nav-hover-color, #444);
      color: var(--side-nav-hover-text-color, var(--primary-text-color, #eee)); }
    .card:hover .icons button, .card:focus-within .icons button, .icons button.bookmarked { opacity: .85; }
    .icons button.bookmarked { color: var(--favorite-icon-color, #f7c600); }
    .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); padding: 10px 18px;
      border-radius: 6px; background: var(--card-bg-color, #222); color: var(--primary-text-color, #eee);
      box-shadow: 0 2px 8px rgba(0, 0, 0, .4); opacity: 0; transition: opacity .2s; pointer-events: none; }
    .toast.on { opacity: 1; }
    .more { text-align: center; padding: 28px 0 8px; color: var(--secondary-text-color, #aaa); }
    .more.error { cursor: pointer; text-decoration: underline; }
  </style>
  <div class="page">
    <div class="bar"><h1>Home</h1><span class="meta"></span><button type="button">Refresh</button></div>
    <div class="chips" role="tablist"></div>
    <p class="msg"></p>
    <div class="grid"></div>
    <div class="more"></div>
  </div>
  <div class="toast"></div>`;
  const $ = (s) => root.querySelector(s);
  $('.bar button').addEventListener('click', () => send({ type: 'refresh', chip: state.chip }));
  $('.chips').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (b && b.dataset.key !== state.chip) selectChip(b.dataset.key);
  });
  $('.chips').addEventListener('wheel', (e) => {  // a mouse wheel scrolls the chips sideways
    const el = e.currentTarget;
    if (!e.deltaY || e.deltaX || el.scrollWidth <= el.clientWidth) return;
    e.preventDefault();
    el.scrollLeft += e.deltaY;
  }, { passive: false });
  $('.more').addEventListener('click', () => {
    if (state.moreError) { state.moreError = ''; maybeLoadMore(); }
  });
  host.addEventListener('scroll', () => maybeLoadMore(), { passive: true });

  // Infinite scroll: ask for the next page when the bottom comes near.
  function maybeLoadMore() {
    if (!state.shown || !state.videos || !state.videos.length) return;
    if (state.loading || state.loadingMore || state.moreError) return;
    if (host.scrollTop + host.clientHeight < host.scrollHeight - 1200) return;
    state.loadingMore = true;
    render();
    send({ type: 'more', chip: state.chip });
  }

  // Topic chips (All, Music, Podcasts...): each one is its own feed, served by the launcher.
  function selectChip(key) {
    Object.assign(state, { chip: key, videos: null, fetchedAt: 0, loading: true, error: '',
      loadingMore: false, moreError: '' });
    render();
    send({ type: 'chip', chip: key });
  }

  let renderedChips;
  function renderChips() {
    const id = JSON.stringify([state.chips, state.chip]);
    if (id === renderedChips) return;
    renderedChips = id;
    $('.chips').replaceChildren(...state.chips.map((c) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = c.label; b.dataset.key = c.key;
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(c.key === state.chip));
      b.classList.toggle('on', c.key === state.chip);
      return b;
    }));
  }

  const fmtDuration = (s) => {
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  };
  const fmtViews = (n) => new Intl.NumberFormat('en', { notation: 'compact' }).format(n) + ' views';
  const fmtAgo = (ms) => {
    const min = Math.round((Date.now() - ms) / 60000);
    return min < 1 ? 'just now' : min < 60 ? `${min} min ago` : `${Math.round(min / 60)} h ago`;
  };

  function card(v) {
    const el = document.createElement('div');
    el.className = 'card'; el.tabIndex = 0; el.title = v.title;
    const thumb = el.appendChild(document.createElement('div'));
    thumb.className = 'thumb';
    const img = thumb.appendChild(document.createElement('img'));
    img.loading = 'lazy'; img.alt = ''; img.src = `https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`;
    if (v.duration) {
      const d = thumb.appendChild(document.createElement('span'));
      d.className = 'dur'; d.textContent = fmtDuration(v.duration);
    }
    addSaveButtons(thumb, v);
    const t = el.appendChild(document.createElement('div'));
    t.className = 'title'; t.textContent = v.title;
    if (v.channel) {
      const c = el.appendChild(document.createElement('div'));
      c.className = 'sub channel'; c.textContent = v.channel;
      if (v.channelId) c.addEventListener('click', (e) => { e.stopPropagation(); openChannel(v.channelId); });
    }
    if (v.views) {
      const w = el.appendChild(document.createElement('div'));
      w.className = 'sub'; w.textContent = fmtViews(v.views);
    }
    el.addEventListener('click', () => openVideo(v.id));
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') openVideo(v.id); });
    return el;
  }

  // --- save buttons: FreeTube's own playlist actions -------------------------
  const t = (key, fallback, params) => {
    try { const out = i18n && i18n(key, params || {}); if (out && out !== key) return out; } catch (e) { /* no i18n */ }
    return fallback;
  };
  const hasAction = (name) => !!store && typeof store.dispatch === 'function'
    && (!store._actions || !!store._actions[name]);
  const quickPlaylist = () => { try { return store.getters.getQuickBookmarkPlaylist || null; } catch (e) { return null; } };
  const videoData = (v) => ({ videoId: v.id, title: v.title, author: v.channel || null, authorId: v.channelId || null,
    lengthSeconds: v.duration || 0, viewCount: v.views || 0 });

  function iconButton(name, title, onClick) {
    const b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = `<svg viewBox="0 0 24 24"><path fill="currentColor" d="${ICONS[name]}"/></svg>`;
    b.title = title; b.setAttribute('aria-label', title);
    b.addEventListener('click', (e) => { e.stopPropagation(); onClick(b); });
    b.addEventListener('keydown', (e) => e.stopPropagation());
    return b;
  }

  function addSaveButtons(thumb, v) {
    let hidden = false;
    try { hidden = !!(store && store.getters.getHidePlaylists); } catch (e) { /* keep them */ }
    if (hidden) return;
    const icons = document.createElement('div');
    icons.className = 'icons';
    if (hasAction('showAddToPlaylistPromptForManyVideos')) {
      icons.append(iconButton('plus', t('User Playlists.Add to Playlist', 'Add to Playlist'),
        () => store.dispatch('showAddToPlaylistPromptForManyVideos', { videos: [videoData(v)] })));
    }
    if (hasAction('addVideo') && hasAction('removeVideo') && quickPlaylist()) {
      const b = iconButton('bookmark', '', () => toggleBookmark(v, b));
      b.dataset.videoId = v.id;
      icons.append(b);
      updateBookmark(b);
    }
    if (icons.children.length) thumb.append(icons);
  }

  function updateBookmark(b) {
    const playlist = quickPlaylist();
    if (!playlist) { b.remove(); return; }
    const saved = playlist.videos.some((x) => x.videoId === b.dataset.videoId);
    const params = { playlistName: playlist.playlistName };
    b.classList.toggle('bookmarked', saved);
    b.querySelector('path').setAttribute('d', saved ? ICONS.check : ICONS.bookmark);
    b.title = saved ? t('User Playlists.Remove from Favorites', `Remove from ${playlist.playlistName}`, params)
      : t('User Playlists.Add to Favorites', `Add to ${playlist.playlistName}`, params);
    b.setAttribute('aria-label', b.title);
  }
  const updateBookmarks = () => root.querySelectorAll('.icons button[data-video-id]').forEach(updateBookmark);

  async function toggleBookmark(v, b) {
    const playlist = quickPlaylist();
    if (!playlist) return;
    try {
      if (playlist.videos.some((x) => x.videoId === v.id)) {
        await store.dispatch('removeVideo', { _id: playlist._id, videoId: v.id });
        toast(t('Video.Video has been removed from your saved list', 'Video has been removed from your saved list'));
      } else {
        await store.dispatch('addVideo', { _id: playlist._id, videoData: videoData(v) });
        toast(t('Video.Video has been saved', 'Video has been saved'));
      }
    } catch (e) { console.warn('[freetube_home]', e); }
    updateBookmarks();
  }

  let toastTimer;
  function toast(text) {
    const el = $('.toast');
    el.textContent = text; el.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('on'), 2500);
  }

  function render(appended) {
    renderChips();
    const btn = $('.bar button');
    btn.disabled = state.loading;
    btn.textContent = state.loading ? 'Updating…' : 'Refresh';
    $('.meta').textContent = state.fetchedAt ? `Updated ${fmtAgo(state.fetchedAt)}` : '';
    $('.msg').textContent = state.error
      || (!state.videos ? (state.chip ? 'Loading…' : 'Loading your YouTube home page…')
        : state.videos.length ? '' : 'No videos.');
    const more = $('.more');
    more.textContent = state.loadingMore ? 'Loading more…'
      : state.moreError ? `${state.moreError} — click to try again` : '';
    more.classList.toggle('error', !!state.moreError);
    if (appended) {
      $('.grid').append(...appended.map(card));
    } else if (renderedFor !== state.videos) {
      $('.grid').replaceChildren(...(state.videos || []).map(card));
      host.scrollTop = 0;
    }
    renderedFor = state.videos;
    requestAnimationFrame(() => maybeLoadMore());  // a short page needs more right away
  }

  // --- fitting into FreeTube: position, theme, navigation ---------------------
  function layout() {
    const side = first(SIDE), top = first(TOP), view = first(VIEW);
    let left = 0, right = innerWidth, topPx = 0, bottom = innerHeight;
    if (top) {
      const r = top.getBoundingClientRect();
      if (r.height > 0 && r.height < innerHeight / 3) topPx = Math.max(0, r.bottom);
    }
    if (side) {
      const r = side.getBoundingClientRect();
      if (r.width > 0 && r.top > innerHeight / 2) bottom = r.top;  // narrow window: nav bar at the bottom
      else if (r.width > 0 && r.width < innerWidth / 2) left = r.right;
    }
    if (view) {
      const r = view.getBoundingClientRect();
      if (r.width > 100) { left = r.left; right = r.right; }
    }
    Object.assign(host.style, { left: `${left}px`, top: `${topPx}px`,
      width: `${Math.max(0, right - left)}px`, height: `${Math.max(0, bottom - topPx)}px` });
  }

  function applyTheme() {
    const src = first(VIEW) || document.getElementById('app') || document.body;
    const cs = getComputedStyle(src);
    for (const name of THEME_VARS) {
      const value = cs.getPropertyValue(name).trim();
      if (value) host.style.setProperty(name, value);
    }
    let bg = cs.backgroundColor;
    if (!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') bg = getComputedStyle(document.body).backgroundColor;
    host.style.setProperty('--fth-bg', bg);
    host.style.setProperty('--fth-fg', cs.color);
    host.style.setProperty('--fth-font', cs.fontFamily);
  }

  function setShown(shown) {
    state.shown = shown;
    host.style.display = shown ? 'block' : 'none';
    if (entry) entry.style.backgroundColor = shown ? 'var(--side-nav-active-color, rgba(127, 127, 127, .25))' : '';
    if (!shown) return;
    applyTheme(); layout(); render(); updateBookmarks();
    if (!state.loading && (!state.videos || Date.now() - state.fetchedAt > STALE_MS)) {
      send({ type: 'refresh', chip: state.chip });
    }
  }

  function go(path, url) {
    if (router) { router.push(path).catch(() => {}); return; }
    setShown(false);
    send({ type: 'open', url });  // FreeTube opens youtube.com links itself
  }
  const openVideo = (id) => go(`/watch/${id}`, `https://www.youtube.com/watch?v=${id}`);
  const openChannel = (id) => go(`/channel/${id}`, `https://www.youtube.com/channel/${id}`);
  const openHome = () => { if (router) router.push(ROUTE).catch(() => {}); else setShown(true); };

  function wireRouter() {
    for (const el of [document.getElementById('app'), ...document.querySelectorAll('body > *')]) {
      const g = el && el.__vue_app__ && el.__vue_app__.config.globalProperties;
      const r = g && g.$router;
      if (r && typeof r.push === 'function' && typeof r.addRoute === 'function') {
        router = r;
        if (g.$store && typeof g.$store.dispatch === 'function' && g.$store.getters) store = g.$store;
        if (typeof g.$t === 'function') i18n = g.$t.bind(g);
        break;
      }
    }
    if (!router) return;
    if (store && typeof store.watch === 'function') {
      try {  // keep the bookmark buttons right when FreeTube's playlists change
        store.watch(() => { const p = quickPlaylist(); return p ? `${p._id}:${p.videos.length}` : ''; }, updateBookmarks);
      } catch (e) { /* the buttons just update on the next visit */ }
    }
    renderedFor = undefined;  // redraw cards with the save buttons now available
    render();
    try {
      if (!router.hasRoute(ROUTE_NAME)) {
        router.addRoute({ path: ROUTE, name: ROUTE_NAME, meta: { title: 'Home' },
          component: { name: 'FtYoutubeHome', render: () => null } });
      }
      router.afterEach((to) => setShown(to.path === ROUTE));
      const current = router.currentRoute.value.path;
      if (current !== ROUTE && location.hash.startsWith('#' + ROUTE)) router.replace(ROUTE).catch(() => {});
      setShown(current === ROUTE);
    } catch (e) {
      console.warn('[freetube_home] router not usable, using overlay mode', e);
      router = null;
    }
  }

  function ensureEntry() {
    if (entry && entry.isConnected) return;
    const side = first(SIDE);
    const template = side && [...side.querySelectorAll('a, [role="link"], [role="button"]')]
      .find((el) => el.querySelector('svg') && el.textContent.trim());
    if (!template) { ensureFloating(); return; }
    if (floating) { floating.remove(); floating = null; }
    entry = template.cloneNode(true);
    entry.setAttribute('data-ft-home-entry', '');
    for (const a of ['href', 'id', 'aria-current']) entry.removeAttribute(a);
    entry.setAttribute('role', 'link');
    entry.tabIndex = 0;
    entry.title = 'YouTube Home';
    entry.style.cursor = 'pointer';
    const walker = document.createTreeWalker(entry, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walker.nextNode()) if (walker.currentNode.nodeValue.trim()) texts.push(walker.currentNode);
    texts.forEach((n, i) => { n.nodeValue = i === 0 ? 'Home' : ''; });
    entry.querySelectorAll('svg').forEach((svg, i) => {
      if (i) { svg.remove(); return; }
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.innerHTML = HOUSE;
    });
    const activate = (e) => { e.preventDefault(); e.stopPropagation(); openHome(); };
    entry.addEventListener('click', activate, true);
    entry.addEventListener('keydown', (e) => { if (e.key === 'Enter') activate(e); });
    template.parentNode.insertBefore(entry, template);
    if (state.shown) setShown(true);
  }

  function ensureFloating() {
    if (floating && floating.isConnected) return;
    floating = document.createElement('div');
    floating.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:5;';
    const r = floating.attachShadow({ mode: 'open' });
    r.innerHTML = `<style>button { display: flex; gap: 6px; align-items: center; border: 0; border-radius: 20px;
      padding: 8px 14px; cursor: pointer; font: inherit; background: var(--accent-color, #f44336);
      color: var(--text-with-accent-color, #fff); box-shadow: 0 2px 6px rgba(0, 0, 0, .3); }</style>
      <button type="button"><svg width="16" height="16" viewBox="0 0 24 24">${HOUSE}</svg>Home</button>`;
    r.querySelector('button').addEventListener('click', openHome);
    document.body.appendChild(floating);
  }

  // Overlay mode only: leave the page when FreeTube's own navigation is used.
  document.addEventListener('click', (e) => {
    if (!state.shown) return;
    setTimeout(layout, 350);  // the sidebar may be animating open/closed
    if (router || host.contains(e.target) || (entry && entry.contains(e.target))) return;
    if (floating && floating.contains(e.target)) return;
    if (e.target.closest && e.target.closest(SIDE.concat(TOP).join(','))) setShown(false);
  }, true);

  function receive(msg) {
    let appended = null;
    if (Array.isArray(msg.chips)) state.chips = msg.chips;
    if (typeof msg.chip === 'string' && msg.chip !== state.chip) {  // about a chip no longer shown
      render();
      return;
    }
    if (msg.type === 'feed') {
      state.videos = msg.videos; state.fetchedAt = msg.fetchedAt; state.error = ''; state.loading = !!msg.loading;
      state.loadingMore = false; state.moreError = '';
    } else if (msg.type === 'append') {
      appended = msg.videos;
      state.videos = (state.videos || []).concat(appended);
      state.loadingMore = false;
      if (!appended.length) state.moreError = 'No more videos right now';
    } else if (msg.type === 'loading') {
      if (msg.more) state.loadingMore = !!msg.loading; else state.loading = !!msg.loading;
    } else if (msg.type === 'error') {
      if (msg.more) { state.moreError = msg.message; state.loadingMore = false; }
      else { state.error = msg.message; state.loading = false; }
    }
    render(appended);
  }
  window.__ftHome = { receive };

  function start() {
    document.body.appendChild(host);
    const tick = () => {
      try {
        if (!router) wireRouter();
        ensureEntry();
        if (state.shown) layout();
      } catch (e) { console.warn('[freetube_home]', e); }
    };
    tick();
    setInterval(tick, 1000);
    setInterval(() => { if (state.shown) { applyTheme(); render(); } }, 30000);
    addEventListener('resize', () => { if (state.shown) layout(); });
    send({ type: 'ready' });
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""


class DevTools:
    """Minimal Chrome DevTools Protocol client over a hand-written WebSocket.

    Standard library only, so no Python package update can break it. Supports
    exactly what --launch needs: sending commands and receiving events.
    """

    def __init__(self, ws_url):
        u = urllib.parse.urlsplit(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("DevTools closed the connection during the handshake")
            response += chunk
        status, self.buf = response.split(b"\r\n\r\n", 1)
        if b" 101 " not in status.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"DevTools refused the WebSocket: {status[:80]!r}")
        self.sock.settimeout(None)
        self.send_lock = threading.Lock()
        self.ids = itertools.count(1)

    def _send_frame(self, opcode, data):
        n = len(data)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)  # clients must mask every frame
        masked = (int.from_bytes(data, "big")
                  ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
        with self.send_lock:
            self.sock.sendall(bytes(header) + mask + masked)

    def call(self, method, params=None):
        """Send a command without waiting for its result."""
        message = {"id": next(self.ids), "method": method, "params": params or {}}
        self._send_frame(0x1, json.dumps(message).encode())

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools connection closed")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def receive(self, timeout):
        """Return the next message, or None if nothing arrived within timeout."""
        if not self.buf and not select.select([self.sock], [], [], timeout)[0]:
            return None
        message = b""
        while True:
            b1, b2 = self._read(2)
            opcode, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x8:
                raise ConnectionError("DevTools connection closed")
            if opcode == 0x9:
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            message += data
            if b1 & 0x80:
                return json.loads(message)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def log(message):
    print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)


# Where FreeTube's Windows installer puts it: per user, or for all users. Scoop too.
FREETUBE_EXES = [
    os.path.join(LOCALAPPDATA, r"Programs\FreeTube\FreeTube.exe"),
    os.path.join(os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files",
                 r"FreeTube\FreeTube.exe"),
    os.path.expanduser(r"~\scoop\apps\freetube\current\FreeTube.exe"),
]


def find_freetube(path=None):
    """The command that starts FreeTube, or None."""
    if path:
        return [os.path.abspath(os.path.expanduser(path))] if os.path.isfile(os.path.expanduser(path)) else None
    if WINDOWS:
        found = [c for c in [*FREETUBE_EXES, shutil.which("FreeTube")] if c and os.path.isfile(c)]
        return found[:1] or None
    if shutil.which("flatpak") and subprocess.run(
            ["flatpak", "info", FLATPAK_ID], capture_output=True).returncode == 0:
        return ["flatpak", "run", FLATPAK_ID]
    if shutil.which("freetube"):
        return [shutil.which("freetube")]
    return None


def freetube_command(path=None):
    command = find_freetube(path)
    if not command:
        if path:
            fail(f"FreeTube not found at {path}")
        fail("FreeTube not found (" + ("not installed in the usual places; pass --freetube-path"
             if WINDOWS else "neither the Flatpak nor a 'freetube' command") + ")")
    return command


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_devtools_page(port, proc, timeout=60):
    """WebSocket URL of FreeTube's main window, once DevTools is up."""
    started = time.time()
    while time.time() - started < timeout and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                targets = json.load(r)
        except (OSError, ValueError):
            targets = []
        pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        main = [t for t in pages if "index.html" in t.get("url", "")]
        if main:
            return main[0]["webSocketDebuggerUrl"]
        if pages and time.time() - started > 20:  # FreeTube changed how it loads; take what's there
            return pages[0]["webSocketDebuggerUrl"]
        time.sleep(0.5)
    return None


class HomeLauncher:
    """Serves the page its feeds. Each topic chip has its own feed, keyed by the
    chip's label; the key "" is the "All" feed, the only one cached on disk —
    like youtube.com, the page always opens on "All"."""

    def __init__(self, args, command, proc):
        self.args, self.command, self.proc = args, command, proc
        self.session = None
        self.home = None  # the HomeSession that the chips come from
        self.chips = []
        self.chip = ""  # the feed the page shows
        self.feeds = {}  # key -> {"videos", "fetchedAt"}
        self.streams = {}  # key -> FeedStream, to continue that feed
        self.fetching = set()  # keys being loaded
        self.fetch_lock = threading.Lock()  # guards self.fetching
        self.net_lock = threading.Lock()  # one load from YouTube at a time
        try:
            with open(FEED_CACHE, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("version") != CACHE_VERSION:
                raise ValueError("cache from an older version")
            self.feeds[""] = {"videos": cached["videos"], "fetchedAt": cached["fetchedAt"]}
            self.chips = cached.get("chips") or []
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def push(self, msg):
        session = self.session
        if not session:
            return
        expression = f"window.__ftHome && window.__ftHome.receive({json.dumps(msg)})"
        try:
            session.call("Runtime.evaluate", {"expression": expression})
        except OSError as e:
            log(f"could not reach FreeTube: {e}")

    def push_feed(self):
        key = self.chip
        feed = self.feeds.get(key) or {}
        self.push({"type": "feed", "chip": key, "chips": self.chips, "videos": feed.get("videos"),
                   "fetchedAt": feed.get("fetchedAt", 0), "loading": key in self.fetching})

    def feed_is_stale(self, key):
        feed = self.feeds.get(key)
        return not feed or time.time() - feed["fetchedAt"] / 1000 > STALE_FEED_SECONDS

    def select(self, key):
        self.chip = key
        self.push_feed()
        if self.feed_is_stale(key):
            self._start_fetch(key, more=False, fresh=False)

    def refresh(self, key):
        self._start_fetch(key, more=False, fresh=True)

    def load_more(self, key):
        self._start_fetch(key, more=bool(self.feeds.get(key)), fresh=False)

    def _start_fetch(self, key, more, fresh):
        with self.fetch_lock:
            if key in self.fetching:
                return
            self.fetching.add(key)
        if key == self.chip:
            self.push({"type": "loading", "chip": key, "loading": True, "more": more})
        threading.Thread(target=self._fetch, args=(key, more, fresh), daemon=True).start()

    def _new_stream(self, yt_dlp, key, fresh):
        """A stream for the feed, from the current home page load where possible."""
        home = self.home
        reuse = (home and not fresh and time.time() - home.created < SESSION_MAX_AGE
                 and not (key == "" and home.home_used))  # "All" can be read once per load
        if reuse:
            try:
                return home.stream(key)
            except FeedError:
                pass  # the chip's token may have expired: load the page again
        try:
            self.home = HomeSession(yt_dlp, self.args.browser, self.args.profile)
        except FeedError as e:
            if key:
                raise
            log(f"home page with chips unavailable, using the plain feed: {e}")
            self.home, self.chips = None, []
            return FeedStream.recommended(yt_dlp, self.args.browser, self.args.profile)
        if key == "":
            # YouTube picks a different set of chips on every load; the page's
            # chip bar only changes along with the "All" feed, never under you.
            self.chips = self.home.chip_list()
        return self.home.stream(key)

    def _next_page(self, key, seen, fresh):
        yt_dlp = import_yt_dlp()
        if yt_dlp is None:  # no library: a whole new load, minus what's already shown
            if key:
                raise FeedError("topics need yt-dlp's self-contained version"
                                f" ({'install.ps1' if WINDOWS else 'install.sh'} sets it up)")
            videos = load_feed(self.args.browser, self.args.profile, PAGE_SIZE * 2)
            return [v for v in videos if v["id"] not in seen][:PAGE_SIZE]
        for attempt in range(2):  # a used-up feed is followed by a fresh load, like YouTube does
            stream = self.streams.get(key)
            if stream is None or stream.exhausted:
                stream = self.streams[key] = self._new_stream(yt_dlp, key, fresh or attempt > 0)
            videos = stream.take(PAGE_SIZE, seen)
            if videos:
                return videos
        return []

    def _fetch(self, key, more, fresh):
        error = None
        try:
            with self.net_lock:
                if more:
                    feed = self.feeds[key]
                    videos = self._next_page(key, {v["id"] for v in feed["videos"]}, fresh=False)
                    feed["videos"] = feed["videos"] + videos
                else:
                    self.streams.pop(key, None)
                    videos = self._next_page(key, set(), fresh)
                    if not videos:
                        raise FeedError(
                            f"YouTube returned no videos for “{key}”." if key else
                            "YouTube returned no videos. Check youtube.com in your browser: if it says"
                            " your watch history is off, YouTube shows no suggestions at all.")
                    self.feeds[key] = {"videos": videos, "fetchedAt": int(time.time() * 1000)}
            if key == "":
                feed = self.feeds[""]
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(FEED_CACHE, "w", encoding="utf-8") as f:
                    json.dump({**feed, "videos": feed["videos"][:MAX_CACHED], "chips": self.chips,
                               "version": CACHE_VERSION},
                              f, ensure_ascii=False)
            log(f"{'loaded more' if more else 'fetched'}{f' ({key})' if key else ''}: {len(videos)} videos")
        except FeedError as e:
            error = str(e)
        except Exception as e:  # keep the launcher alive whatever happens
            error = f"unexpected error: {e!r}"
        finally:
            with self.fetch_lock:
                self.fetching.discard(key)
        if error:
            log(f"fetch failed: {error}")
        if key != self.chip:
            return  # the page has moved on to another chip; this one is kept for later
        if error:
            self.push({"type": "error", "chip": key, "chips": self.chips, "message": error, "more": more})
        elif more:
            self.push({"type": "append", "chip": key, "videos": videos})
        else:
            self.push_feed()

    def on_message(self, msg):
        params = msg.get("params") or {}
        if msg.get("method") == "Runtime.bindingCalled" and params.get("name") == BRIDGE:
            try:
                request = json.loads(params.get("payload") or "{}")
            except ValueError:
                return
            kind = request.get("type")
            key = request.get("chip") if isinstance(request.get("chip"), str) else ""
            if kind == "ready":
                # A freshly loaded page starts on "All". Nothing is fetched yet:
                # YouTube is only contacted as you once the Home page is opened.
                self.chip = ""
                self.push_feed()
            elif kind == "chip":
                self.select(key)
            elif kind == "refresh":
                self.chip = key
                self.refresh(key)
            elif kind == "more":
                self.load_more(key)
            elif kind == "open":
                url = request.get("url")
                if isinstance(url, str) and url.startswith("https://www.youtube.com/"):
                    subprocess.Popen(self.command + [url], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        elif "error" in msg:
            log(f"DevTools error: {msg['error']}")

    def run_session(self, ws_url):
        session = DevTools(ws_url)
        script = (HOME_PAGE_JS.replace("%BRIDGE%", json.dumps(BRIDGE))
                  .replace("%STALE_MS%", str(STALE_FEED_SECONDS * 1000)))
        session.call("Runtime.enable")
        session.call("Page.enable")
        session.call("Runtime.addBinding", {"name": BRIDGE})
        session.call("Page.addScriptToEvaluateOnNewDocument", {"source": script})  # reloads
        session.call("Runtime.evaluate", {"expression": script})  # the page already open
        self.session = session
        log("Home page added to FreeTube")
        try:
            while self.proc.poll() is None:
                msg = session.receive(1.0)
                if msg:
                    self.on_message(msg)
        finally:
            self.session = None
            session.close()


UPDATE_STAMP = os.path.join(CACHE_DIR, "yt-dlp-update-check")


def update_yt_dlp_daily():
    """Let a self-contained yt-dlp update itself, at most once a day.

    YouTube changes its pages often and old yt-dlp versions then return fewer
    details or nothing at all. Runs before yt-dlp is imported, so the running
    launcher never has the file replaced underneath it.
    """
    path = find_yt_dlp()
    if not path or not zipfile.is_zipfile(path) or not os.access(path, os.W_OK):
        return  # a distro package is updated by the package manager instead
    try:
        if time.time() - os.path.getmtime(UPDATE_STAMP) < 86400:
            return
    except OSError:
        pass
    open(UPDATE_STAMP, "w").close()
    try:
        out = subprocess.run(ytdlp_command(path) + ["-U"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120, **NO_WINDOW)
        lines = (out.stdout + out.stderr).strip().splitlines()
        log(f"yt-dlp update check: {lines[-1] if lines else 'no output'}")
    except (OSError, subprocess.SubprocessError) as e:
        log(f"yt-dlp update check failed: {e}")


def launch(args):
    os.makedirs(CACHE_DIR, exist_ok=True)
    if sys.stderr is None or not sys.stderr.isatty():  # started from the app menu: keep a log
        sys.stderr = open(LAUNCH_LOG, "w", buffering=1, encoding="utf-8")
    if not WINDOWS:
        refresh_desktop_entry(args)
    command = freetube_command(args.freetube_path)
    if freetube_running():
        # A FreeTube that is already open can't gain a DevTools port; just hand
        # over (this focuses it, and opens any freetube:// link passed in).
        log("FreeTube is already running; handing over")
        subprocess.Popen(command + args.urls)
        return
    port = free_port()
    proc = subprocess.Popen(command + [f"--remote-debugging-port={port}", *args.urls],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"started FreeTube (DevTools on 127.0.0.1:{port})")
    update_yt_dlp_daily()  # while FreeTube is still starting up
    log(f"using {find_yt_dlp()}")
    launcher = HomeLauncher(args, command, proc)
    while proc.poll() is None:
        ws_url = find_devtools_page(port, proc)
        if not ws_url:
            log("FreeTube did not open DevTools; it runs normally, without the Home page")
            return
        try:
            launcher.run_session(ws_url)
        except (OSError, ConnectionError, ValueError) as e:
            log(f"DevTools session ended: {e}")
            time.sleep(1)
    log("FreeTube closed")


# --- App-menu entry ------------------------------------------------------------
#
# Linux: a copy of FreeTube's own .desktop file in ~/.local/share/applications
# takes precedence over the installed one, so the normal menu icon (and
# freetube:// links) go through --launch. Flatpak updates never touch this copy;
# --launch regenerates it whenever the installed original is newer.
#
# Windows: a "FreeTube Home" shortcut in the Start menu, next to FreeTube's own.
# freetube:// links still open FreeTube's own way, which hands them to the
# running FreeTube when it was started from the shortcut.

DESKTOP_MARKER = "X-FreeTube-Home-Launcher=true"
DESKTOP_SOURCES = [
    f"/var/lib/flatpak/exports/share/applications/{FLATPAK_ID}.desktop",
    f"~/.local/share/flatpak/exports/share/applications/{FLATPAK_ID}.desktop",
    "/usr/share/applications/freetube.desktop",
]
USER_APPLICATIONS = os.path.expanduser("~/.local/share/applications")
OWN_DESKTOP_FILE = "freetube-yt-home-page.desktop"  # when FreeTube has none (AppImage)
SHORTCUT = os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\FreeTube Home.lnk")


def launcher_options(args):
    """The options the menu entry passes on to --launch."""
    options = []
    if args.browser != "auto":
        options += ["--browser", args.browser]
    if args.profile:
        options += ["--profile", os.path.abspath(os.path.expanduser(args.profile))]
    if args.freetube_path:
        options += ["--freetube-path", os.path.abspath(os.path.expanduser(args.freetube_path))]
    return options


def desktop_quote(arg):
    """Quote one argument of a .desktop Exec line (Desktop Entry spec)."""
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'


def desktop_source():
    for path in map(os.path.expanduser, DESKTOP_SOURCES):
        if os.path.exists(path):
            return path
    return None


def install_launcher(args, quiet=False):
    if WINDOWS:
        install_windows_shortcut(args, quiet)
    else:
        install_desktop_entry(args, quiet)


def install_desktop_entry(args, quiet=False):
    source = desktop_source()
    if not source and not args.freetube_path:
        fail("FreeTube's .desktop file not found; for an AppImage, pass --freetube-path")
    command = [sys.executable, os.path.abspath(__file__), "--launch", *launcher_options(args)]
    exec_line = "Exec=" + " ".join(map(desktop_quote, command)) + " %u"
    out, section = [], None
    if source:
        with open(source, encoding="utf-8") as f:
            lines = f.read().splitlines()
    else:
        lines = ["[Desktop Entry]", "Type=Application", "Name=FreeTube",
                 "Comment=FreeTube with your YouTube Home page", "Icon=freetube", "Exec=",
                 "Categories=AudioVideo;Video;Network;", "MimeType=x-scheme-handler/freetube;"]
    for line in lines:
        if line.startswith("["):
            section = line.strip()
        if section == "[Desktop Entry]":
            if line.startswith("TryExec="):
                continue
            if line.startswith("Exec="):
                line = exec_line
        out.append(line)
        if line.strip() == "[Desktop Entry]":
            out.append(DESKTOP_MARKER)
    os.makedirs(USER_APPLICATIONS, exist_ok=True)
    target = os.path.join(USER_APPLICATIONS, os.path.basename(source) if source else OWN_DESKTOP_FILE)
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", USER_APPLICATIONS], capture_output=True)
    if not quiet:
        print(f"installed {target}: FreeTube from the app menu now has the Home page")


def refresh_desktop_entry(args):
    source = desktop_source()
    if not source:
        return
    target = os.path.join(USER_APPLICATIONS, os.path.basename(source))
    try:
        with open(target, encoding="utf-8") as f:
            ours = DESKTOP_MARKER in f.read()
        if ours and os.path.getmtime(source) > os.path.getmtime(target):
            install_desktop_entry(args, quiet=True)
            log("app-menu entry regenerated from the updated FreeTube one")
    except OSError:
        pass


def our_desktop_entries():
    names = [f"{FLATPAK_ID}.desktop", "freetube.desktop", OWN_DESKTOP_FILE]
    found = []
    for name in names:
        target = os.path.join(USER_APPLICATIONS, name)
        try:
            with open(target, encoding="utf-8") as f:
                if DESKTOP_MARKER in f.read():
                    found.append(target)
        except OSError:
            pass
    return found


def install_windows_shortcut(args, quiet=False):
    freetube = freetube_command(args.freetube_path)[0]
    # pythonw.exe: no console window next to FreeTube
    python = sys.executable
    if python.lower().endswith("python.exe") and os.path.exists(python[:-10] + "pythonw.exe"):
        python = python[:-10] + "pythonw.exe"
    arguments = subprocess.list2cmdline([os.path.abspath(__file__), "--launch", *launcher_options(args)])
    # Values go in through the environment: no quoting problems with spaces or quotes.
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FTH_LINK);"
              "$s.TargetPath = $env:FTH_TARGET; $s.Arguments = $env:FTH_ARGS;"
              "$s.WorkingDirectory = $env:FTH_DIR; $s.IconLocation = $env:FTH_ICON;"
              "$s.Description = 'FreeTube with your YouTube Home page'; $s.Save()")
    os.makedirs(os.path.dirname(SHORTCUT), exist_ok=True)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, **NO_WINDOW,
            env={**os.environ, "FTH_LINK": SHORTCUT, "FTH_TARGET": python, "FTH_ARGS": arguments,
                 "FTH_DIR": os.path.dirname(os.path.abspath(__file__)), "FTH_ICON": f"{freetube},0"})
        problem = (result.stderr or result.stdout).strip() or f"PowerShell exited with {result.returncode}"
    except OSError as e:
        result, problem = None, f"PowerShell could not be started ({e})"
    if not result or result.returncode != 0 or not os.path.exists(SHORTCUT):
        fail(f"could not create the Start-menu shortcut: {problem}")
    if not quiet:
        print(f'installed the Start-menu shortcut "FreeTube Home" ({SHORTCUT})')


def launcher_installed():
    return os.path.exists(SHORTCUT) if WINDOWS else bool(our_desktop_entries())


def uninstall_launcher():
    if WINDOWS:
        if os.path.exists(SHORTCUT):
            os.remove(SHORTCUT)
            print(f'removed the Start-menu shortcut "FreeTube Home" ({SHORTCUT})')
        else:
            print("no Start-menu shortcut of ours to remove")
        return
    removed = our_desktop_entries()
    for target in removed:
        os.remove(target)
        print(f"removed {target}: the app menu starts plain FreeTube again")
    if removed and shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", USER_APPLICATIONS], capture_output=True)
    if not removed:
        print("no app-menu entry of ours to remove")


# --- Main ----------------------------------------------------------------------

def check(args):
    """Report the setup without contacting YouTube; exit status 1 if it can't work."""
    ok = True
    try:
        name, path = find_cookie_db(args.browser, args.profile)
        print(f"browser:            {name} ({os.path.dirname(path)})")
        with tempfile.TemporaryDirectory(prefix="freetube_home-") as workdir:
            write_youtube_cookie_file((name, path), workdir)  # also decrypts Chromium cookies
        print("YouTube login:      found")
    except FeedError as e:
        print(f"YouTube login:      NOT USABLE — {e}")
        ok = False
    install_hint = "run install.ps1" if WINDOWS else "run install.sh, or put yt-dlp in ~/.local/bin"
    ytdlp = find_yt_dlp()
    if ytdlp:
        version = subprocess.run(ytdlp_command(ytdlp) + ["--version"], capture_output=True,
                                 text=True, **NO_WINDOW).stdout.strip()
        print(f"yt-dlp:             {ytdlp} ({version})")
        if import_yt_dlp() is None:
            print(f"                    not usable as a library: topic chips and infinite scroll need"
                  f" the self-contained yt-dlp ({install_hint})")
    else:
        print(f"yt-dlp:             NOT FOUND — {install_hint}")
        ok = False
    command = find_freetube(args.freetube_path)
    if not command:
        print("FreeTube:           NOT FOUND — " + ("install it, or pass --freetube-path" if WINDOWS
              else "neither the Flatpak nor a 'freetube' command; pass --freetube-path"))
        ok = False
    elif command[0] == "flatpak":
        print(f"FreeTube:           Flatpak ({FLATPAK_ID})")
    else:
        print(f"FreeTube:           {command[0]}")
    entry = "Start-menu shortcut" if WINDOWS else "app-menu entry"
    print(f"{entry + ':':<20}{'installed' if launcher_installed() else 'not installed (run --install-launcher)'}")
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--browser", default="auto", choices=["auto", *BROWSERS],
                        help="browser you are logged in to YouTube with"
                             " (default: the most recently used one that is)")
    parser.add_argument("--playlist", action="store_true",
                        help="save the feed as a FreeTube playlist instead of printing it")
    parser.add_argument("--name", default="YouTube Home", help="playlist name (default: %(default)s)")
    parser.add_argument("--count", type=int, default=60, help="how many videos (default: %(default)s)")
    parser.add_argument("--profile", help="browser profile dir (default: most recently used)")
    parser.add_argument("--freetube-dir", help="FreeTube config dir (default: auto-detect)")
    parser.add_argument("--freetube-path",
                        help="FreeTube program to start, e.g. a portable FreeTube.exe or an AppImage"
                             " (default: auto-detect)")
    parser.add_argument("--debug", action="store_true", help="show yt-dlp's log and what it returned")
    parser.add_argument("--check", action="store_true",
                        help="show which browser's YouTube login would be used, without contacting YouTube")
    parser.add_argument("--launch", action="store_true",
                        help="start FreeTube with a Home page showing the feed")
    parser.add_argument("--install-launcher", action="store_true",
                        help="make FreeTube's app-menu entry use --launch (Windows: add a"
                             " \"FreeTube Home\" Start-menu shortcut); --browser, --profile and"
                             " --freetube-path given with it are kept")
    parser.add_argument("--uninstall-launcher", action="store_true",
                        help="undo --install-launcher")
    parser.add_argument("urls", nargs="*", help=argparse.SUPPRESS)  # passed on by the menu entry
    args = parser.parse_args()
    if WINDOWS and sys.stdout is not None:  # titles in any script, even in a legacy console
        sys.stdout.reconfigure(errors="replace")

    if args.check:
        check(args)
        return
    if args.install_launcher:
        install_launcher(args)
        return
    if args.uninstall_launcher:
        uninstall_launcher()
        return
    if args.launch:
        launch(args)
        return

    if args.playlist:
        db_path = find_playlists_db(args.freetube_dir)
        if freetube_running():
            fail("FreeTube is running — close it first, or it will overwrite the playlist")

    try:
        with tempfile.TemporaryDirectory(prefix="freetube_home-") as workdir:
            cookie_db = find_cookie_db(args.browser, args.profile)
            cookie_file = write_youtube_cookie_file(cookie_db, workdir, args.debug)
            entries = fetch_entries(cookie_file, args.count, debug=args.debug)
    except FeedError as e:
        fail(str(e))

    if not entries:
        fail("YouTube returned no videos. Check youtube.com in your browser: if it says your"
             " watch history is off, YouTube shows no suggestions at all.")

    if not args.playlist:
        for e in entries:
            print(f"{e['id']} | {e.get('channel') or e.get('uploader') or '?'} | {e.get('title')}")
        return

    action = save_playlist(db_path, args.name, entries)
    print(f'{action} FreeTube playlist "{args.name}" with {len(entries)} videos'
          f" (backup: {db_path}.bak). Open FreeTube → Playlists.")


if __name__ == "__main__":
    main()
