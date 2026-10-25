#!/usr/bin/env python3
"""Render docs/brand/mockups/index.html artboards to PNG with the Gecko engine.

Uses a throwaway headless profile with Marionette (test-style automation),
never a user profile. Output: docs/brand/assets/mockups/<artboard-id>.png

    python3 -I scripts/brand/render_mockups.py
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from marionette import Marionette  # noqa: E402

from nulavio_launcher import engine  # noqa: E402

PAGE = ROOT / "docs" / "brand" / "mockups" / "index.html"
OUT = ROOT / "docs" / "brand" / "assets" / "mockups"
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def main() -> int:
    eng = engine.find_engine()
    tmp = Path(tempfile.mkdtemp(prefix="nulavio-mockups-"))
    profile = tmp / "profile"
    profile.mkdir(mode=0o700)
    (profile / "user.js").write_text(
        'user_pref("marionette.port", 0);\nuser_pref("remote.prefs.recommended", false);\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("browser.aboutwelcome.enabled", false);\n'
    )
    proc = subprocess.Popen(
        [str(eng.path), "--profile", str(profile), "--marionette", "--headless", "--new-instance", "about:blank"],
        env={**os.environ, "MOZ_HEADLESS": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port_file = profile / "MarionetteActivePort"
        for _ in range(200):
            if port_file.exists() and port_file.read_text().strip():
                break
            time.sleep(0.3)
        client = Marionette(int(port_file.read_text())).connect()
        client.new_session()
        client.send("WebDriver:SetWindowRect", {"width": 1320, "height": 1000})
        client.navigate(PAGE.as_uri())
        time.sleep(1.0)
        ids = client.execute("return [...document.querySelectorAll('section.artboard')].map(s => s.id);")
        OUT.mkdir(parents=True, exist_ok=True)
        for artboard in ids:
            element = client.send("WebDriver:FindElement", {"using": "css selector", "value": f"#{artboard}"})["value"]
            data = client.send("WebDriver:TakeScreenshot", {"id": element[ELEMENT_KEY], "full": False, "scroll": True})["value"]
            target = OUT / f"{artboard}.png"
            target.write_bytes(base64.b64decode(data))
            print(target.relative_to(ROOT))
        client.quit()
    finally:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
