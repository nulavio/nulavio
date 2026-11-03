"""Nulavio Connect P0 inside the browser (docs/adr/0004-nulavio-connect.md). Nulavio build only.

The registered test profile runs in a throwaway home with a private D-Bus
session bus (harness.GeckoProfileSession), so discovery talks to services the
test starts (dbus-test-tool) and the default-browser offer writes only to the
throwaway home's settings. The real desktop's settings are hashed before and
after to prove they were not touched.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from marionette import MarionetteError

MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioConnect.sys.mjs").NulavioConnect'
REAL_SETTINGS = [Path.home() / ".config" / name for name in ("mimeapps.list", "kdeglobals")]
TOOLS = ("dbus-test-tool", "busctl", "xdg-settings", "xdg-mime")


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        f"(async () => {{ const C = {MODULE}; {body} }})()"
        ".then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


def digest(paths: list[Path]) -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}


@unittest.skipUnless(harness.nulavio_engine(), "Nulavio Connect needs the Nulavio build (NULAVIO_ENGINE)")
@unittest.skipUnless(all(shutil.which(t) for t in TOOLS), f"needs {', '.join(TOOLS)}")
class ConnectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_before = digest(REAL_SETTINGS)
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        # A stand-in kdeconnect-cli (P1): two reachable devices, and a log of what was shared.
        fake_bin = cls.session.tmp / "bin"
        fake_bin.mkdir()
        cls.kdeconnect_log = cls.session.tmp / "kdeconnect.log"
        (fake_bin / "kdeconnect-cli").write_text(
            f'#!/bin/sh\necho "$@" >> "{cls.kdeconnect_log}"\n'
            'case "$1" in --list-available) echo "abc123_def Pixel"; echo "zzz999 Tablet" ;; esac\n'
        )
        (fake_bin / "kdeconnect-cli").chmod(0o700)
        cls.session.env["PATH"] = f"{fake_bin}:{cls.session.env['PATH']}"
        cls.m = cls.session.start()
        cls.fakes: list[subprocess.Popen] = []

    @classmethod
    def tearDownClass(cls):
        try:
            for proc in cls.fakes:
                proc.kill()
                proc.wait(timeout=10)
            cls.session.cleanup()
        finally:
            pass

    def call(self, body: str, *args):
        result = chrome_async(self.m, body, args)
        if "error" in result:
            raise AssertionError(f"NulavioConnect failed: {result['error']}")
        return result["ok"]

    def found(self) -> dict:
        return {s["id"]: s for s in self.call("return C.discover();")}

    def own(self, *names: str) -> None:
        for name in names:
            self.fakes.append(
                subprocess.Popen(
                    ["dbus-test-tool", "echo", "--session", f"--name={name}"],
                    env=self.session.env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )

        def listed():
            out = subprocess.run(
                ["busctl", "--user", "--no-pager", "list", "--acquired"], env=self.session.env, capture_output=True, text=True
            ).stdout
            return all(n in out for n in names)

        self.assertTrue(harness.wait_until(listed, timeout=10), f"fake services did not start: {names}")

    def xdg(self, *args: str) -> str:
        return subprocess.run(list(args), env=self.session.env, capture_output=True, text=True, check=True).stdout.strip()

    # -- discovery -------------------------------------------------------------

    def test_01_nothing_on_the_bus(self):
        found = self.found()
        self.assertEqual(found["xdg-portals"]["state"], "unavailable")
        self.assertEqual(found["secret-service"]["state"], "unavailable")
        self.assertIn(found["plasma-browser-integration"]["reason"], {"no-session", "not-installed"})
        self.assertEqual(found["default-browser"]["state"], "available")

    def test_02_services_found_with_evidence(self):
        self.own("org.freedesktop.portal.Desktop", "org.freedesktop.secrets", "org.kde.plasmashell")
        found = self.found()
        portals = found["xdg-portals"]
        self.assertEqual((portals["state"], portals["reason"]), ("available", "ready"))
        self.assertIn("not reported", portals["evidence"][1], "a portal version must not be invented")
        self.assertIn("widget.use-xdg-desktop-portal.file-picker", portals["evidence"][2])
        self.assertEqual(found["secret-service"]["params"]["provider"], "dbus-test-tool")
        plasma = found["plasma-browser-integration"]
        read_dir = self.m.chrome("return Services.dirsvc.get('XRESysNativeManifests', Ci.nsIFile).path;")
        installed = Path(read_dir) / "native-messaging-hosts" / "org.kde.plasma.browser_integration.json"
        elsewhere = [
            d
            for d in ("/usr/lib64/mozilla", "/usr/lib/mozilla")
            if d != read_dir and (Path(d) / "native-messaging-hosts" / "org.kde.plasma.browser_integration.json").exists()
        ]
        if not installed.exists() and elsewhere:
            # Installed where this build does not read: said plainly, never "not installed".
            self.assertEqual((plasma["state"], plasma["reason"]), ("unavailable", "not-read"))
            self.assertEqual(plasma["params"]["dir"], f"{elsewhere[0]}/native-messaging-hosts")
        elif installed.exists():
            self.assertEqual((plasma["state"], plasma["reason"]), ("available", "ready"))
            self.assertTrue(plasma["params"]["page"].startswith("https://addons.mozilla.org/"))
            self.assertIn("not installed in this profile", plasma["evidence"][-1])
        else:
            self.assertEqual(plasma["reason"], "not-installed")

    # -- the one change: default browser, on request, reversible ---------------

    def test_03_make_default_and_restore(self):
        apps = Path(self.session.env["XDG_DATA_HOME"]) / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        (apps / "test-browser.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Test Browser\nExec=/usr/bin/true %u\n"
            "MimeType=x-scheme-handler/http;x-scheme-handler/https;text/html;\n"
        )
        self.xdg("xdg-settings", "set", "default-web-browser", "test-browser.desktop")
        before = self.found()["default-browser"]
        self.assertEqual((before["state"], before["reason"], before["params"]["name"]), ("available", "other", "Test Browser"))

        result = self.call("return C.setDefaultBrowser();")
        entry = Path(result["desktopEntry"])
        self.assertEqual(entry, apps / "net.nulavio.Nulavio.desktop")
        text = entry.read_text()
        self.assertIn("MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;", text)
        exec_line = next(line for line in text.splitlines() if line.startswith("Exec="))
        self.assertTrue(Path(exec_line[5:].split()[0]).is_file(), exec_line)
        self.assertEqual(self.xdg("xdg-settings", "get", "default-web-browser"), "net.nulavio.Nulavio.desktop")
        now = self.found()["default-browser"]
        self.assertEqual(
            (now["state"], now["params"]["previous"], now["params"]["previousName"]),
            ("enabled", "test-browser.desktop", "Test Browser"),
        )

        self.call("return C.restoreDefaultBrowser();")
        self.assertEqual(self.xdg("xdg-settings", "get", "default-web-browser"), "test-browser.desktop")
        self.assertEqual(self.found()["default-browser"]["state"], "available")
        self.assertEqual(chrome_async(self.m, "return C.restoreDefaultBrowser();").get("error"), "no-previous")

    def test_04_settings_page_shows_real_states(self):
        url = self.m.chrome(
            "return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('settings/settings.html#integrations');"
        )
        self.m.navigate(url)

        def rows():
            try:
                return self.m.execute(
                    "const l = document.getElementById('integration-list');"
                    "return l.dataset.ready ? [...l.children].map(li => [li.dataset.integration, li.dataset.state]) : null;"
                )
            except MarionetteError:
                return None

        listed = harness.wait_until(rows, timeout=20)
        p0 = ["plasma-browser-integration", "xdg-portals", "secret-service", "default-browser"]
        later = ["kde-connect", "screen-cast", "security-keys", "notifications", "krunner", "activities"]
        self.assertEqual([r[0] for r in listed], p0 + later)
        self.assertEqual(dict(listed)["xdg-portals"], "available")
        self.assertTrue(self.m.execute("return Boolean(document.querySelector('[data-focus-key=\"make-default\"]'));"))
        # Nothing on the page reached the network.
        external = self.m.execute(
            "return performance.getEntriesByType('resource').map(e => e.name)"
            ".filter(n => !n.startsWith('moz-extension:') && !n.startsWith('data:'));"
        )
        self.assertEqual(external, [])

    # -- P1/P2, through the Nulavio tools -------------------------------------------

    def test_05_p1_and_p2_states_from_the_tools(self):
        self.own("org.kde.kdeconnect.daemon", "org.freedesktop.Notifications", "org.kde.ActivityManager")
        found = self.found()
        self.assertEqual((found["kde-connect"]["state"], found["kde-connect"]["reason"]), ("available", "devices"))
        self.assertEqual(found["kde-connect"]["params"]["devices"], "Pixel, Tablet")
        self.assertEqual((found["notifications"]["state"], found["notifications"]["reason"]), ("available", "ready"))
        self.assertEqual(found["activities"]["reason"], "not-used")
        self.assertIn(found["security-keys"]["reason"], {"none", "usable", "no-permission"})  # the real hardware
        self.assertIn(found["krunner"]["reason"], {"available", "no-krunner", "no-gi"})
        self.assertEqual(found["screen-cast"]["priority"], "P1")

    def test_06_send_one_link_and_krunner_on_request(self):
        self.call("return C.sendLink(args[0], args[1]);", "https://example.org/shared", "abc123_def")
        self.assertIn("--device abc123_def --share https://example.org/shared", self.kdeconnect_log.read_text())
        self.assertEqual(
            chrome_async(self.m, "return C.sendLink(args[0], args[1]);", ["file:///etc/passwd", "abc123_def"]).get("error"),
            "bad-url",
        )
        if self.found()["krunner"]["state"] != "available":
            self.skipTest("KRunner or Python's GLib bindings are not installed")
        data = Path(self.session.env["XDG_DATA_HOME"])
        self.call("return C.setKrunner(true);")
        self.assertTrue((data / "krunner" / "dbusplugins" / "net.nulavio.krunner.desktop").exists())
        self.assertEqual(self.found()["krunner"]["state"], "enabled")
        self.call("return C.setKrunner(false);")
        self.assertFalse((data / "krunner" / "dbusplugins" / "net.nulavio.krunner.desktop").exists())

    def test_07_link_menu_offers_reachable_devices_and_sends_one_link(self):
        # The item starts hidden and appears once the reachable devices are known; the
        # engine leaves hidden items out of onShown's menuIds, so it once never appeared.
        page = 'data:text/html,<a id="go" href="https://example.org/from-menu">link</a>'
        self.m.navigate(page)
        self.m.context_click("#go")
        devices = harness.wait_until(lambda: self.m.menu_entries("nulavio-send-link") or None, timeout=15)
        self.assertEqual(devices, ["Pixel", "Tablet"], "the link menu has no 'Send link to device' item")
        clicked = self.m.chrome(
            "const item = document.querySelector(`[id$='nulavio-send-link']`);"
            "[...item.querySelectorAll('menuitem')].find(i => i.getAttribute('label') === 'Pixel').click();"
            "document.getElementById('contentAreaContextMenu').hidePopup(); return 'clicked';"
        )
        self.assertEqual(clicked, "clicked")
        self.assertTrue(
            harness.wait_until(
                lambda: "--device abc123_def --share https://example.org/from-menu" in self.kdeconnect_log.read_text(),
                timeout=15,
            ),
            "the link was not sent to the chosen device",
        )

        # Never offered in a private window, and back in the normal window afterwards.
        handles = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            harness.wait_until(lambda: self.m.current_url() == "about:privatebrowsing", timeout=20)
            self.m.navigate(page)
            self.m.context_click("#go")
            self.assertTrue(harness.wait_until(self.m.menu_open))
            time.sleep(2)  # longer than the device lookup takes in the normal window
            self.assertIsNone(self.m.menu_entries("nulavio-send-link"), "offered in a private window")
            self.m.close_menu()
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)
        self.m.context_click("#go")
        self.assertEqual(
            harness.wait_until(lambda: self.m.menu_entries("nulavio-send-link") or None, timeout=15), ["Pixel", "Tablet"]
        )
        self.m.close_menu()

    def test_99_real_desktop_settings_untouched(self):
        time.sleep(0.5)
        self.assertEqual(digest(REAL_SETTINGS), self.real_before, "the real desktop settings changed")


if __name__ == "__main__":
    unittest.main()
