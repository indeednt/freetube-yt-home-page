"""End-to-end check, used by the CI workflow: FreeTube started by the launcher
gets the Home page.

Run it after FreeTube has been started through the installed launcher (on
Windows: the "FreeTube Home" Start-menu shortcut). It reads the DevTools port
from the launcher's log, then, through that port: waits for the Home entry
in FreeTube's sidebar, opens the page, reports what it shows and saves a
screenshot. There is no YouTube login on a CI machine, so the page is
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

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
        pages = [t for t in json.load(r) if t.get("type") == "page" and "index.html" in t.get("url", "")]
    session = fh.DevTools(pages[0]["webSocketDebuggerUrl"])

    def command(method, params=None):
        message_id = next(session.ids)
        session._send_frame(0x1, json.dumps({"id": message_id, "method": method,
                                             "params": params or {}}).encode())
        while True:
            message = session.receive(30)
            if message is None:
                raise TimeoutError(method)
            if message.get("id") == message_id:
                return message.get("result") or {}

    def evaluate(expression):
        result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result.get("result", {}).get("value")

    def wait_for(expression, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            value = evaluate(expression)
            if value:
                return value
            time.sleep(1)
        return None

    if not wait_for("!!document.querySelector('[data-ft-home-entry]')", 60):
        sys.exit("FAIL: no Home entry in FreeTube's sidebar")
    print("ok: Home entry in the sidebar")

    evaluate("document.querySelector('[data-ft-home-entry]').click()")
    page = "document.querySelector('[data-ft-home-page]')"
    if not wait_for(f"{page} && {page}.style.display === 'block'", 20):
        sys.exit("FAIL: the Home page did not open")
    print("ok: Home page opens; route:", evaluate("location.hash"))

    # Without a YouTube login the launcher answers with an explanation.
    message = wait_for(f"(() => {{ const t = {page}.shadowRoot.querySelector('.msg').textContent;"
                       " return t && !t.startsWith('Loading') ? t : ''; })()", 120)
    print("page message:", message or "(none)")

    time.sleep(1)
    shot = command("Page.captureScreenshot", {"format": "png"})
    with open(screenshot, "wb") as f:
        f.write(base64.b64decode(shot["data"]))
    print("screenshot saved:", screenshot)
    if not message:
        sys.exit("FAIL: the page never got an answer from the launcher")
    print("PASS")


if __name__ == "__main__":
    main()
