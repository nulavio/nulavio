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
        self.assertEqual(
            [r[0] for r in listed], ["plasma-browser-integration", "xdg-portals", "secret-service", "default-browser"]
        )
        self.assertEqual(dict(listed)["xdg-portals"], "available")
        self.assertTrue(self.m.execute("return Boolean(document.querySelector('[data-focus-key=\"make-default\"]'));"))
        # Nothing on the page reached the network.
        external = self.m.execute(
            "return performance.getEntriesByType('resource').map(e => e.name)"
            ".filter(n => !n.startsWith('moz-extension:') && !n.startsWith('data:'));"
        )
        self.assertEqual(external, [])

    def test_99_real_desktop_settings_untouched(self):
        time.sleep(0.5)
        self.assertEqual(digest(REAL_SETTINGS), self.real_before, "the real desktop settings changed")


if __name__ == "__main__":
    unittest.main()
