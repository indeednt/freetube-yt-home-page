# FreeTube YouTube Home Page

[![test](https://github.com/indeednt/freetube-yt-home-page/actions/workflows/test.yml/badge.svg)](https://github.com/indeednt/freetube-yt-home-page/actions/workflows/test.yml)

Adds a **Home** page to [FreeTube](https://freetubeapp.io) with your personal YouTube recommendations, the
same feed you see on the front page of youtube.com, including the topic chips (All, Music, Podcasts,
Gaming…). Works on **Linux** and **Windows**.

FreeTube never logs in to YouTube, so it can't show personal recommendations. This project fetches
them for you using your browser's YouTube login, then shows them inside FreeTube. You watch the
videos in FreeTube as usual: with no ads, no Google account attached, and nothing added to your YouTube
watch history.

> **Before installing, read the [Privacy](#privacy) section.** Personal recommendations require Google to
> know who you are. This project limits what Google learns, but it can't make the feed itself anonymous.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Privacy](#privacy)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Choosing the browser](#choosing-the-browser)
- [Hardening: separate your IP address](#hardening-separate-your-ip-address)
- [Command-line reference](#command-line-reference)
- [Troubleshooting](#troubleshooting)
- [Files it creates](#files-it-creates)
- [Uninstall](#uninstall)
- [Security notes](#security-notes)
- [Limitations](#limitations)
- [License](#license)

---

## Features

- **Home entry in FreeTube's sidebar**, styled like FreeTube's own entries.
- **Your personal YouTube home feed** with thumbnails, durations, channels and view counts.
- **Topic chips** like on youtube.com: *All*, *Music*, *Podcasts*, *Gaming*, *Mixes*, *Live*, *Recently
  uploaded*, *Watched*, *New to you*… YouTube picks them for your account. Each chip has its own feed, and
  switching back to a chip you've already opened is instant.
- **Infinite scroll:** more videos load as you reach the bottom, like on youtube.com.
- **Opens videos in FreeTube's player.** Click a channel name to open the channel in FreeTube.
- **Save buttons** on each card: *Add to playlist* and FreeTube's quick bookmark, using FreeTube's own
  playlists. These never involve Google.
- **Matches FreeTube's theme** (light, dark, custom colours) and works with Back/Forward navigation.
- **Leaves FreeTube unmodified.** Nothing inside FreeTube is patched or replaced, and FreeTube updates
  keep working. If a FreeTube update changes something the page relies on, the page falls back to
  simpler behaviour rather than breaking FreeTube.
- **Silent startup:** nothing is fetched until you open the Home page.

## How it works

```
 Your browser (Zen, Firefox, Chrome…)         YouTube
 ┌──────────────────────────┐   cookies    ┌───────────┐
 │ logged in to youtube.com ├─────────────►│ home feed │
 └──────────────────────────┘  (read-only) └─────┬─────┘
                                                 │ video list (via yt-dlp)
                                                 ▼
 freetube_home.py --launch ─────────────► FreeTube window
   starts FreeTube with a local            "Home" page drawn into it;
   remote-control (DevTools) port          videos play through FreeTube's
                                           own, anonymous player
```

1. You start FreeTube through the launcher: your normal app-menu entry on Linux, or the **FreeTube Home**
   Start-menu shortcut on Windows.
2. The launcher starts FreeTube with Chromium's standard `--remote-debugging-port` switch, on
   `127.0.0.1` only.
3. Through that port it adds the Home page to FreeTube's window. The page uses its own isolated styles,
   adds itself to FreeTube's sidebar and router, and reads FreeTube's theme colours.
4. When you open Home, the launcher reads your browser's youtube.com cookies into a private temporary
   file and loads YouTube's home page with [yt-dlp](https://github.com/yt-dlp/yt-dlp). It sends the
   video list to the page. The temporary file is deleted right away.
5. When you click a video, it plays in FreeTube exactly as it would otherwise, without your login.

## Privacy

FreeTube exists so that you can use YouTube without being tracked. This project deliberately makes one
exception: **loading the Home feed tells Google it's you.** Here is exactly what that means.

### What Google learns

Each time the Home page loads a feed, YouTube receives a request carrying your login. Google can see:

- **when** you opened Home, and from **which IP address**;
- **which videos** it showed you;
- **which topic chips** you opened, and how far you scrolled (each "load more" is a request).

### What Google does not learn

- **What you watch in FreeTube.** Playback, video pages, comments, subscriptions and search all go through
  FreeTube as usual: anonymous, with no cookies. FreeTube's own browser session holds no Google cookies,
  and this project doesn't add any. Videos you watch in FreeTube **do not** appear in your YouTube
  history.
- **Behaviour on the page.** YouTube's tracking scripts (what you hover, what's on screen, what you click)
  never run. The feed is fetched as data, the way yt-dlp does it, and drawn by this project.
- **Your FreeTube playlists and bookmarks.** The save buttons are purely local FreeTube features.

### What the project does to limit tracking

- **No requests on startup.** Starting FreeTube doesn't contact YouTube as you. The feed loads only when
  you open Home, and is reused for 30 minutes.
- **Read-only cookies.** Only `youtube.com` cookies are read, into a temporary file in a private folder,
  deleted immediately after use. Your browser's cookie store is never modified, and cookies YouTube sends
  back are discarded.
- **Nothing is sent anywhere else.** The only other network request is a daily `yt-dlp -U` update check,
  which goes to GitHub. That request carries no login.

### The weak spot: your IP address

Your logged-in feed request and FreeTube's anonymous video requests both come from your home IP address.
Google could connect the two: it shows your account video *X*, and a minute later an anonymous client on
the same IP plays video *X*. **So with this project, your FreeTube viewing should be considered linkable
to your account**, unless FreeTube's traffic leaves from a different IP address. The fix is described
below in [Hardening](#hardening-separate-your-ip-address).

Also keep in mind: YouTube's recommendations learn from what you watch **in your browser**, not from what
you watch in FreeTube.

## Requirements

|                     | Linux | Windows 10 / 11 |
|---------------------|-------|-----------------|
| **FreeTube**        | Flatpak, `.deb`, `.rpm`, AUR or AppImage | installer (per user or for all users), Scoop or portable |
| **Python 3.8+**     | preinstalled on practically every distribution | **not preinstalled**: the installer offers to install it with `winget` |
| **yt-dlp**          | the installer sets it up | the installer sets it up |
| **A browser logged in to youtube.com** | Firefox or Chrome family (see below) | **Firefox family** (see below) |

The browser must be signed in on **youtube.com** itself. Being signed in to Google (Gmail, etc.) isn't
enough. yt-dlp keeps itself up to date: the launcher runs its update check once a day.

### Supported browsers

| Family  | Browsers                                      | Linux                                    | Windows |
|---------|-----------------------------------------------|------------------------------------------|---------|
| Firefox | Firefox, Zen, LibreWolf, Floorp, Waterfox     | ✅ native, Snap (Firefox), Flatpak        | ✅ including Firefox from the Microsoft Store |
| Chrome  | Chrome, Chromium, Brave, Edge, Vivaldi, Opera | ✅ native, Snap, Flatpak                  | ⚠️ in practice no: see below |

**Chrome family on Linux:** these browsers encrypt their cookies with a key stored in your desktop's
keyring (GNOME Keyring, KWallet…). yt-dlp reads it from there. On GNOME, Cinnamon, Xfce, MATE and similar
desktops that needs `python3-secretstorage`:

```bash
sudo apt install python3-secretstorage      # Debian, Ubuntu, Mint
sudo dnf install python3-secretstorage      # Fedora
sudo pacman -S python-secretstorage         # Arch
```

**Chrome family on Windows:** Chrome and Edge protect their cookies with *app-bound encryption*, which no
other program can decrypt. They also lock the cookie file while running. Other Chromium browsers are
increasingly doing the same. On Windows, keep a **Firefox-family browser logged in to YouTube** for this
project, even if it's not your main browser.

## Install

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/install.sh | sh
```

The installer runs as your user, never as root, and:

1. checks that FreeTube and Python are installed;
2. copies `freetube_home.py` to `~/.local/share/freetube-yt-home-page/`;
3. downloads the self-contained yt-dlp to `~/.local/bin/yt-dlp`, unless that file already exists;
4. puts a copy of FreeTube's app-menu entry in `~/.local/share/applications/` that starts FreeTube with
   the Home page. Your system's own entry is left untouched;
5. runs `--check` to confirm the browser login, yt-dlp, FreeTube and the menu entry.

Then **quit FreeTube completely** (including from the tray, if you use it) and start it again from the app
menu.

### Windows

Open **PowerShell** (Start menu → type *PowerShell*) and run:

```powershell
irm https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/install.ps1 | iex
```

The installer needs no administrator rights, and:

1. looks for FreeTube (if it's missing: `winget install -e --id FreeTube.FreeTube`, or get it from
   [freetubeapp.io](https://freetubeapp.io));
2. looks for Python. If there is none, it **asks** whether to install Python 3.13 from python.org with
   `winget`, for your user only;
3. puts `freetube_home.py` and the self-contained yt-dlp in `%LOCALAPPDATA%\freetube-yt-home-page\`;
4. adds a **FreeTube Home** shortcut to the Start menu, with FreeTube's icon;
5. runs `--check`.

Then **quit FreeTube completely** (including from the tray) and start it with **FreeTube Home** from the
Start menu. FreeTube's own shortcut still starts plain FreeTube, without the Home page. You can pin
**FreeTube Home** to the taskbar or Start menu instead.

### From a clone

```bash
git clone https://github.com/indeednt/freetube-yt-home-page.git
cd freetube-yt-home-page
sh install.sh                                              # Linux
powershell -ExecutionPolicy Bypass -File install.ps1       # Windows
```

To update, run the install command again.

## Usage

- Start FreeTube through the launcher: the normal app-menu entry on Linux, **FreeTube Home** on Windows.
  **Home** appears at the top of FreeTube's sidebar.
- Open **Home** to load your feed. Click a **chip** to switch topics. Scroll down to load more.
- **Refresh** (top right) loads a fresh feed and a fresh set of chips. Otherwise a feed is reused for 30
  minutes.
- Click a **thumbnail or title** to play the video in FreeTube. Click a **channel name** to open the
  channel.
- Hover a card for **Add to playlist** (+) and **Bookmark**, the same as FreeTube's own cards.
- `freetube://…` links (for example from a browser extension) open in the running FreeTube, Home page
  included.

The page only appears when FreeTube was started through the launcher. FreeTube started any other way is
plain FreeTube.

## Choosing the browser

By default (`--browser auto`), the most recently used browser profile **that is logged in to YouTube**
is used. To check which one that is, without contacting YouTube:

```bash
python3 ~/.local/share/freetube-yt-home-page/freetube_home.py --check                 # Linux
```
```powershell
python "$env:LOCALAPPDATA\freetube-yt-home-page\freetube_home.py" --check            # Windows
```

```
browser:            zen (/home/you/.var/app/app.zen_browser.zen/.zen/abcd1234.Default (release))
YouTube login:      found
yt-dlp:             /home/you/.local/bin/yt-dlp (2026.08.19)
FreeTube:           Flatpak (io.freetubeapp.FreeTube)
app-menu entry:     installed
```

To always use a specific browser or profile, reinstall the launcher with that choice. The menu entry or
shortcut remembers it:

```bash
python3 ~/.local/share/freetube-yt-home-page/freetube_home.py --install-launcher --browser librewolf
python3 ~/.local/share/freetube-yt-home-page/freetube_home.py --install-launcher --profile "/path/to/profile"
```

(On Windows, use the `python "$env:LOCALAPPDATA\…"` form shown above.)

**Firefox containers:** only the login of normal tabs is used. If you're logged in to YouTube only inside a
container tab, the launcher will tell you to log in in a normal tab.

## Hardening: separate your IP address

To stop Google linking your FreeTube viewing to your account through your IP (see
[Privacy](#the-weak-spot-your-ip-address)), **send FreeTube's traffic through a different, shared IP
address**. Keep the browser and the feed requests where they are.

Your browser already uses YouTube logged in from your home IP, so moving the *feed* requests elsewhere
wouldn't help. What has to move is FreeTube.

FreeTube has a built-in proxy setting that applies to **all** of its traffic: videos, pages and the Home
page's thumbnails. The feed requests come from the launcher, a separate program, so they're not affected,
which is what you want.

### Option 1: Tor (free)

**Linux:**

```bash
sudo apt install tor                                       # Debian, Ubuntu, Mint (starts by itself)
sudo dnf install tor && sudo systemctl enable --now tor    # Fedora
sudo pacman -S tor && sudo systemctl enable --now tor      # Arch
```

Then in FreeTube: **Settings → Proxy Settings → Enable Tor / Proxy**. The defaults (`SOCKS5`,
`127.0.0.1`, port `9050`) are Tor's.

**Windows:** the simplest way is [Tor Browser](https://www.torproject.org/download/). While it's open, it
provides a proxy at `127.0.0.1`, port **`9150`**. In FreeTube: **Settings → Proxy Settings → Enable Tor /
Proxy**, protocol `SOCKS5`, host `127.0.0.1`, port `9150`.

In both cases, press **Test Proxy**; it should show an IP address that isn't yours. Tor addresses are
shared by many people, so they don't identify you. The downside: YouTube often blocks Tor, so expect
slower loading and occasional *"Sign in to confirm you're not a bot"* errors.

### Option 2: a VPN provider's SOCKS5 proxy (paid)

Some VPN services offer SOCKS5 proxy servers that work without connecting the whole VPN. Enter one in the
same FreeTube setting. Their IPs are also shared and are blocked less often than Tor's. Check that it
works *without* the VPN tunnel, so that only FreeTube uses it.

### Option 3: Invidious

In FreeTube's settings, set the API backend to **Invidious** and enable **Proxy Videos Through
Invidious**. YouTube then sees the Invidious server's IP. It's free, but public servers are often slow or
blocked, and the server's operator can see what you watch.

### What doesn't help

- **A VPN for the whole computer:** the browser and FreeTube share one IP again.
- **Your own private server or proxy:** an IP used only by you becomes a fingerprint of its own.

### What remains

Timing is still a weak signal. Google shows your account a list of videos, and shortly afterwards someone
on a Tor or VPN address plays one of them. On a shared address that's a hint among thousands of users,
not a reliable link. It can't be removed completely while Google chooses your recommendations.

## Command-line reference

```
python3 freetube_home.py [options]          # Windows: python freetube_home.py [options]
```

| Option                  | What it does |
|-------------------------|--------------|
| `--launch`              | Start FreeTube with the Home page. This is what the menu entry / shortcut runs. |
| `--install-launcher`    | Linux: make FreeTube's app-menu entry use `--launch`. Windows: add the **FreeTube Home** Start-menu shortcut. `--browser`, `--profile` and `--freetube-path` given with it are remembered. |
| `--uninstall-launcher`  | Remove that menu entry or shortcut. |
| `--check`               | Show which browser login, yt-dlp, FreeTube and menu entry would be used. Doesn't contact YouTube. |
| `--browser NAME`        | `auto` (default) or one of: `firefox zen librewolf floorp waterfox chrome chromium brave edge vivaldi opera`. |
| `--profile DIR`         | Use this browser profile folder instead of searching for one. |
| `--freetube-path FILE`  | The FreeTube program to start: a portable `FreeTube.exe`, an AppImage… (default: found automatically). |
| *(no option)*           | Print your home feed in the terminal (`id \| channel \| title`). |
| `--count N`             | How many videos to print or save (default 60). |
| `--playlist`            | Save the feed as a FreeTube playlist instead of printing it. Close FreeTube first. |
| `--name NAME`           | Playlist name for `--playlist` (default "YouTube Home"). |
| `--freetube-dir DIR`    | FreeTube's settings folder, if not found automatically. |
| `--debug`               | Show yt-dlp's log and a summary of what YouTube returned. Cookie names and dates only, never values. |

The `--playlist` mode is an alternative that doesn't use the launcher at all. It writes the feed into
FreeTube's playlist database once (with a backup in `playlists.db.bak`), and you open it under
**Playlists**.

## Troubleshooting

Start with `--check` (see [Choosing the browser](#choosing-the-browser)). The launcher's log of the last
start is `~/.cache/freetube_home/launcher.log` on Linux and
`%LOCALAPPDATA%\freetube-yt-home-page\cache\launcher.log` on Windows.

**No "Home" in the sidebar**
- FreeTube was already running when you started it through the launcher, so the launcher could only hand
  over to it. Quit FreeTube completely (including the tray icon) and start it through the launcher again.
- You started FreeTube some other way: on Windows, use **FreeTube Home**, not FreeTube's own shortcut.
- The log says *"FreeTube did not open DevTools"*: your FreeTube build doesn't allow the remote-debugging
  switch. Please open an issue with your FreeTube version and install type.

**"no YouTube login found"**
- Sign in on **youtube.com** in that browser. Being signed in to Google alone isn't enough.
- Several browsers? Choose one with `--browser` (see [Choosing the browser](#choosing-the-browser)).
- *"this profile was last used …"*: the login of a browser you no longer use has probably expired.

**"could not decrypt chrome's cookies"**
- Linux: install `python3-secretstorage` (see [Supported browsers](#supported-browsers)), and make sure your
  keyring is unlocked. It normally unlocks when you log in to your desktop.
- Windows: Chrome-family cookies can't be read by other programs. Use a Firefox-family browser.

**"YouTube returned no videos"**
- Open youtube.com in your browser. If it says your watch history is off, YouTube shows no
  recommendations at all, in the browser or here.

**No chips, or "topics need yt-dlp's self-contained version"**
- The chips need yt-dlp usable as a library. Run the installer again. It sets up the official
  self-contained build, which a Linux distribution's package or Windows' `yt-dlp.exe` is not.
- If YouTube changes its page, the chips may disappear until yt-dlp catches up. The plain feed keeps
  working.

**Windows: "running scripts is disabled on this system"**
- That happens with `.\install.ps1`. Use `irm … | iex` as shown above, or
  `powershell -ExecutionPolicy Bypass -File install.ps1`.

**Windows: "Python was not found; run without arguments to install from the Microsoft Store"**
- That's Windows' placeholder, not Python. Run the installer again and let it install Python, or install
  it from [python.org](https://www.python.org/downloads/windows/).

**Portable FreeTube (Windows) or AppImage (Linux)**
- Tell the launcher where it is; the menu entry or shortcut remembers it:
  `freetube_home.py --install-launcher --freetube-path "C:\Apps\FreeTube\FreeTube.exe"`
  (or the path to the AppImage).

**"HTTP Error 413"**
- Shouldn't happen: oversized `ST-*` cookies are skipped. If it does, run with `--debug` and open an
  issue.

## Files it creates

**Linux**

| Path | What |
|------|------|
| `~/.local/share/freetube-yt-home-page/freetube_home.py` | the script |
| `~/.local/share/applications/io.freetubeapp.FreeTube.desktop` (Flatpak), `freetube.desktop` (packages) or `freetube-yt-home-page.desktop` (AppImage) | the app-menu entry, marked `X-FreeTube-Home-Launcher=true` |
| `~/.local/bin/yt-dlp` | yt-dlp, only if you didn't have it there |
| `~/.cache/freetube_home/` | the last "All" feed (`feed.json`) and the launch log |

**Windows**

| Path | What |
|------|------|
| `%LOCALAPPDATA%\freetube-yt-home-page\freetube_home.py` | the script |
| `%LOCALAPPDATA%\freetube-yt-home-page\yt-dlp` | the self-contained yt-dlp |
| `%LOCALAPPDATA%\freetube-yt-home-page\cache\` | the last "All" feed (`feed.json`) and the launch log |
| Start menu → **FreeTube Home** (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\FreeTube Home.lnk`) | the shortcut |

The cached feed holds video ids, titles, channels, durations, view counts and chip names. No cookies are
ever written to disk outside a private temporary folder, which is deleted right after each feed load.

On Linux, when FreeTube updates its app-menu entry, the launcher notices on the next start and regenerates
its copy automatically.

## Uninstall

**Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/uninstall.sh | sh
```

This removes the script, the app-menu entry and the cache. yt-dlp is left in `~/.local/bin` because other
programs may use it; delete it yourself if you don't need it.

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/indeednt/freetube-yt-home-page/main/uninstall.ps1 | iex
```

This removes the **FreeTube Home** shortcut and `%LOCALAPPDATA%\freetube-yt-home-page` (script, yt-dlp,
cache). Python stays installed; remove it under *Settings → Apps* if you installed it only for this.

In both cases FreeTube itself, its settings and its data are not touched.

## Security notes

- **Remote-debugging port.** The launcher starts FreeTube with a DevTools port on `127.0.0.1` (a random
  free port). It can't be reached from the network. But while FreeTube runs, **any program running on
  your computer as your user** could connect to it and control FreeTube. Such a program could read your
  browser cookies anyway, so this doesn't give malware much new access, but you should know about it.
  FreeTube started without the launcher has no such port.
- **Your browser cookies** are read, never modified, and never leave your computer except in requests to
  youtube.com.
- **yt-dlp updates itself** from its official GitHub releases (`yt-dlp -U`) once a day, when the launcher
  starts. This only applies to the self-contained build that the installers set up.
- **Piping an installer into a shell** (`curl … | sh`, `irm … | iex`) runs whatever that URL serves. If
  you prefer, download `install.sh` / `install.ps1` first, read it, and run it from the file.

## Limitations

- **Linux and Windows only**; macOS isn't supported.
- **On Windows, only Firefox-family browsers** can provide the YouTube login (see
  [Supported browsers](#supported-browsers)).
- The Home page exists only while FreeTube runs under the launcher.
- Recommendations learn from your **browser's** YouTube history, not from what you watch in FreeTube.
- Topic chips use yt-dlp internals that aren't a public interface. A yt-dlp update can break them for a
  while; the page then shows the plain feed without chips.
- Chip feeds are shorter than "All" (about 25–30 videos before YouTube runs out), the same as on
  youtube.com.
- Not affiliated with FreeTube, YouTube or Google.

## License

[MIT](LICENSE)
