#!/usr/bin/env python3
"""UX7 capture matrix: Nulavio's pages inside the real window, at 100/125/150 %, light and dark.

Each shot is the whole window (band, address bar, tabs and the page) on a 1366x768 screen, from a
throwaway profile of a real Track B build, with reduced motion on (nothing mid-animation), taken from
the X server's pixels (run it under xvfb-run). The only change to the window is removing the striped
address bar the engine draws under automation.

    env -u WAYLAND_DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" env GDK_BACKEND=x11 MOZ_ENABLE_WAYLAND=0 \\
      NULAVIO_TEST_HEADFUL=1 NULAVIO_ENGINE=<build>/nulavio/nulavio \\
      python3 -I scripts/research/ux7_captures.py --out docs/design/screenshots/ux7

Writes <page>-<theme>@<scale>.png, manifest.json (each file's sha256, page, theme, scale and size, the
build's BuildID and SourceStamp, the git commit and whether the tree had changes) and, when ImageMagick's
`montage` is installed, a contact sheet matrix.png (the command is recorded in the manifest).

Captures stay in the history for good: nothing is rewritten to remove them. Each release measures
the media in the history against ADR 0013's budget (250 MB, docs/adr/0013-repository-layout.md);
once it is over, new capture sets go to a repository of their own instead of docs/design/screenshots/.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tests" / "lib")]

import harness  # noqa: E402

SCREEN = (1366, 768)
SCALES = (1.0, 1.25, 1.5)
THEMES = {"light": 0, "dark": 1}
SIDEBAR = "shell_nulavio_net-sidebar-action"
FIRST_RUN = (
    "Services.prefs.setStringPref('nulavio.firstrun.done', '');"
    "Services.prefs.setBoolPref('nulavio.startpage.shellFirstTab', true);"
    "Services.prefs.setBoolPref('nulavio.layout.choicePending', true);"
    "Services.prefs.setBoolPref('nulavio.dns.chosen', false);"
)
# Back to the harness profile's state (first run finished), so the pages after it are not in it.
FIRST_RUN_OVER = (
    "Services.prefs.setStringPref('nulavio.firstrun.done', 'finished');"
    "Services.prefs.clearUserPref('nulavio.startpage.shellFirstTab');"
    "Services.prefs.clearUserPref('nulavio.layout.choicePending');"
    "Services.prefs.clearUserPref('nulavio.dns.chosen');"
)


def pages(server) -> dict[str, dict]:
    """name -> where it is and what says it has settled."""
    ready = "return document.documentElement.dataset.ready === 'true';"
    return {
        "newtab-first-run": {
            "path": "newtab/newtab.html",
            "before": FIRST_RUN,
            "after": FIRST_RUN_OVER,
            "settled": "return document.documentElement.hasAttribute('data-painted');",
        },
        "settings-layout": {"path": "settings/settings.html#layout", "settled": ready},
        "settings-appearance": {"path": "settings/settings.html#appearance", "settled": ready},
        "assistant": {"path": None, "sidebar": True},
        "lookalike": {
            "path": "passwords/lookalike.html?" + "url=" + server.url("/page/Login") + "&site=examp1e.com&similar=example.com",
            "settled": "return document.readyState === 'complete';",
        },
        "guard-review": {"path": "guard/review.html", "settled": ready},
    }


def settle(m, check: str | None) -> None:
    """Loaded, fonts ready, nothing busy, the page's own ready mark, then two frames."""
    if check:
        harness.wait_until(lambda: m.execute(check), 20)
    m.execute_async(
        "const done = arguments[arguments.length - 1];"
        "(async () => { await document.fonts.ready;"
        " const busy = () => document.querySelector('[aria-busy=\"true\"]');"
        " for (let i = 0; i < 50 && busy(); i++) await new Promise(r => setTimeout(r, 100));"
        " await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); done(true); })();"
    )


def screen_grab() -> bool:
    """The X server shows the window only when the browser runs headful on X (as under xvfb-run with
    NULAVIO_TEST_HEADFUL=1 and no Wayland); otherwise a grab would be the caller's desktop."""
    return bool(
        shutil.which("import")
        and os.environ.get("DISPLAY")
        and os.environ.get("NULAVIO_TEST_HEADFUL") == "1"
        and not os.environ.get("WAYLAND_DISPLAY")
    )


def window_png(m) -> bytes:
    """The window as the screen shows it: the X server's pixels (ImageMagick `import`), cropped to the
    window. WebDriver's chrome screenshot redraws the window itself and drops masked content (the
    disclosure chevrons, the narrow Settings rail), so it is only the fallback."""
    m.set_context("chrome")
    try:
        m.execute("document.documentElement.removeAttribute('remotecontrol');")
        if screen_grab():
            x, y, width, height = m.execute(
                "const r = window.devicePixelRatio;"
                "return [screenX, screenY, outerWidth, outerHeight].map(v => Math.round(v * r));"
            )
            time.sleep(0.2)  # the frame the removal asked for
            grab = subprocess.run(
                ["import", "-window", "root", "-crop", f"{width}x{height}+{x}+{y}", "+repage", "png:-"],
                capture_output=True,
                check=True,
            )
            return grab.stdout
        return base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"])
    finally:
        m.set_context("content")


def capture_method() -> str:
    if screen_grab():
        return "X server pixels (ImageMagick import -window root, cropped to the window)"
    return "WebDriver chrome screenshot (drops masked content: chevrons, the narrow Settings rail)"


def provenance(engine: Path) -> dict:
    ini = configparser.ConfigParser()
    ini.read(engine.parent / "application.ini")
    app = ini["App"] if ini.has_section("App") else {}
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {
        "buildID": app.get("BuildID"),
        "sourceStamp": app.get("SourceStamp"),
        "version": app.get("Version"),
        "git": git("rev-parse", "HEAD"),
        "gitDirty": bool(git("status", "--porcelain", "--", "browser", "scripts")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    engine = harness.nulavio_engine().path
    manifest = {
        "screen": list(SCREEN),
        "reducedMotion": True,
        "method": capture_method(),
        "build": provenance(Path(engine)),
        "files": [],
    }
    with harness.FixtureServer() as server:
        for theme, dark in THEMES.items():
            for scale in SCALES:
                session = harness.GeckoProfileSession(name="Pessoal")
                m = session.start()
                try:
                    m.chrome(
                        "Services.prefs.setIntPref('ui.prefersReducedMotion', 1);"
                        "Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);"
                        "Services.prefs.setCharPref('layout.css.devPixelsPerPx', arguments[1]);",
                        [dark, str(scale)],
                    )
                    m.send("WebDriver:SetWindowRect", {"width": round(SCREEN[0] / scale), "height": round(SCREEN[1] / scale)})
                    base = m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
                    for name, page in pages(server).items():
                        if page.get("before"):
                            m.chrome(page["before"])
                        if page.get("sidebar"):
                            m.navigate(server.url("/page/Notas"))
                            m.set_context("chrome")
                            m.execute_async(
                                "const done = arguments[arguments.length - 1];"
                                "SidebarController.show(arguments[0]).then(() => setTimeout(() => done(true), 1500));",
                                [SIDEBAR],
                            )
                            m.set_context("content")
                        else:
                            m.navigate(base + page["path"])
                            settle(m, page["settled"])
                        time.sleep(0.3)
                        file = f"{name}-{theme}@{int(scale * 100)}.png"
                        data = window_png(m)
                        (args.out / file).write_bytes(data)
                        manifest["files"].append(
                            {
                                "file": file,
                                "sha256": hashlib.sha256(data).hexdigest(),
                                "page": name,
                                "theme": theme,
                                "scale": scale,
                                # Device pixels, from the PNG header.
                                "size": list(struct.unpack(">II", data[16:24])),
                            }
                        )
                        if page.get("sidebar"):
                            m.chrome("SidebarController.hide();")
                        if page.get("after"):
                            m.chrome(page["after"])
                        print(file, flush=True)
                finally:
                    session.cleanup()
    if shutil.which("montage"):
        files = [str(args.out / f["file"]) for f in manifest["files"]]
        command = [
            "montage",
            *files,
            "-tile",
            "6x",
            "-geometry",
            "456x256+4+4",
            "-background",
            "#F1F7F5",
            str(args.out / "matrix.png"),
        ]
        subprocess.run(command, check=True)
        manifest["contactSheet"] = {
            "file": "matrix.png",
            "command": "montage <files> -tile 6x -geometry 456x256+4+4 -background #F1F7F5 matrix.png",
        }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
