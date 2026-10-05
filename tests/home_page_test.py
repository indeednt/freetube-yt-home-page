"""End-to-end check, used by the CI workflow: FreeTube started by the launcher
gets the Home page.

Run it after FreeTube has been started through the installed launcher (on
Windows: the "FreeTube Home" Start-menu shortcut). It reads the DevTools port
from the launcher's log, then, through that port: waits for the Home entry
in FreeTube's sidebar, opens the page, reports what it shows and saves a
screenshot; then opens a second window with FreeTube's own button and checks
that it gets the page too. There is no YouTube login on a CI machine, so the page is
expected to show the launcher's "no login" message rather than videos.

    python tests/home_page_test.py SCRIPT_DIR SCREENSHOT.png
"""

import base64
import json
import os
import re
import sys
import time
import urllib.request


def main():
    script_dir, screenshot = sys.argv[1], sys.argv[2]
    sys.path.insert(0, script_dir)
    import freetube_home as fh  # the installed copy: its paths, its DevTools client

    log_text, port, deadline = "", None, time.time() + 120
    while time.time() < deadline:
        try:
            with open(fh.LAUNCH_LOG, encoding="utf-8") as f:
                log_text = f.read()
        except OSError:
            log_text = ""
        match = re.search(r"DevTools on 127\.0\.0\.1:(\d+)", log_text)
        if match and "Home page added to FreeTube" in log_text:
            port = int(match.group(1))
            break
        time.sleep(1)
    print("--- launcher log ---\n" + log_text + "--------------------")
    if not port:
        sys.exit("FAIL: the launcher never added the Home page")

    first = windows(port)
    if not first:
        sys.exit("FAIL: no FreeTube window found")
    session = fh.DevTools(next(iter(first.values())))
    message = check_window(session, "first window")

    time.sleep(1)
    shot = command(session, "Page.captureScreenshot", {"format": "png"})
    with open(screenshot, "wb") as f:
        f.write(base64.b64decode(shot["data"]))
    print("screenshot saved:", screenshot)
    if not message:
        sys.exit("FAIL: the page never got an answer from the launcher")

    # A window opened later (FreeTube's "Open New Window" button) gets the page too.
    evaluate(session, "document.querySelector('.navNewWindowButton').click()")
    deadline, new = time.time() + 30, {}
    while time.time() < deadline and not new:
        new = {k: v for k, v in windows(port).items() if k not in first}
        time.sleep(1)
    if not new:
        sys.exit("FAIL: FreeTube's new-window button opened no window")
    if not check_window(fh.DevTools(next(iter(new.values()))), "new window"):
        sys.exit("FAIL: the new window's page never got an answer from the launcher")
    print("PASS")


def windows(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
        return {t["id"]: t["webSocketDebuggerUrl"] for t in json.load(r)
                if t.get("type") == "page" and "index.html" in t.get("url", "")}


def command(session, method, params=None):
    message_id = next(session.ids)
    session._send_frame(0x1, json.dumps({"id": message_id, "method": method,
                                         "params": params or {}}).encode())
    while True:
        message = session.receive(30)
        if message is None:
            raise TimeoutError(method)
        if message.get("id") == message_id:
            return message.get("result") or {}


def evaluate(session, expression):
    result = command(session, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return result.get("result", {}).get("value")


def wait_for(session, expression, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = evaluate(session, expression)
        if value:
            return value
        time.sleep(1)
    return None


def check_window(session, name):
    """Home entry present, page opens, launcher answers; returns the page's message."""
    if not wait_for(session, "!!document.querySelector('[data-ft-home-entry]')", 60):
        sys.exit(f"FAIL: no Home entry in the {name}'s sidebar")
    print(f"ok: Home entry in the {name}'s sidebar")
    evaluate(session, "document.querySelector('[data-ft-home-entry]').click()")
    page = "document.querySelector('[data-ft-home-page]')"
    if not wait_for(session, f"{page} && {page}.style.display === 'block'", 20):
        sys.exit(f"FAIL: the Home page did not open in the {name}")
    print(f"ok: Home page opens in the {name}; route:", evaluate(session, "location.hash"))
    # Without a YouTube login the launcher answers with an explanation.
    message = wait_for(session, f"(() => {{ const t = {page}.shadowRoot.querySelector('.msg').textContent;"
                                " return t && !t.startsWith('Loading') ? t : ''; })()", 120)
    print(f"{name} page message:", message or "(none)")
    return message


if __name__ == "__main__":
    main()
