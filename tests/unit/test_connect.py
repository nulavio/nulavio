"""Nulavio Connect P0 discovery (docs/adr/0004-nulavio-connect.md): `nulavio integrations`.

Runs the real CLI in a throwaway home with a private D-Bus session bus, so the
answers come from real probes (busctl, xdg-settings) against services the
test starts (dbus-test-tool), never from the developer's desktop.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import make_shell  # noqa: E402

TOOLS = ("dbus-daemon", "dbus-test-tool", "busctl", "xdg-settings", "xdg-mime")
DEFINITIONS = ROOT / "browser" / "config" / "integrations.json"


def tools_present() -> bool:
    return all(shutil.which(t) for t in TOOLS)


class DefinitionsTest(unittest.TestCase):
    def test_one_definition_file_for_launcher_and_shell(self):
        out = Path(tempfile.mkdtemp())
        try:
            make_shell.assemble(out / "shell")
            self.assertEqual((out / "shell" / "shared" / "integrations.json").read_bytes(), DEFINITIONS.read_bytes())
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_every_integration_has_a_probe(self):
        items = json.loads(DEFINITIONS.read_text(encoding="utf-8"))["integrations"]
        p0 = [i["id"] for i in items if i["priority"] == "P0"]
        later = [i["id"] for i in items if i["priority"] != "P0"]
        self.assertEqual(p0, ["plasma-browser-integration", "xdg-portals", "secret-service", "default-browser"])
        self.assertEqual(later, ["kde-connect", "screen-cast", "security-keys", "notifications", "krunner", "activities"])
        python = (ROOT / "launcher" / "nulavio_launcher" / "connect.py").read_text(encoding="utf-8")
        later_python = (ROOT / "launcher" / "nulavio_launcher" / "connect_p1.py").read_text(encoding="utf-8")
        shell = (ROOT / "browser" / "shell" / "modules" / "NulavioConnect.sys.mjs").read_text(encoding="utf-8")
        for integration in p0:  # in the launcher and, in the browser, probed directly
            self.assertIn(f'"{integration}":', python)
            self.assertIn(f'"{integration}": spec =>', shell)
        for integration in later:  # one implementation, in the Nulavio tools; the browser asks them
            self.assertIn(f'"{integration}":', later_python)
        self.assertIn('callTool(["integrations", "api"]', shell)

    def test_probes_never_use_a_shell(self):
        python = (ROOT / "launcher" / "nulavio_launcher" / "connect.py").read_text(encoding="utf-8")
        shell = (ROOT / "browser" / "shell" / "modules" / "NulavioConnect.sys.mjs").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", python)
        self.assertIsNone(re.search(r'"(/bin/sh|sh|bash)"|"-c"', shell))
        # Only one action writes anything, and only on the user's click.
        self.assertEqual(re.findall(r'run\("xdg-settings", \["set"', shell), ['run("xdg-settings", ["set"'] * 2)
        self.assertIsNone(re.search(r'"xdg-settings", "set"|"xdg-mime", "default"', python), "the CLI must only read")


@unittest.skipUnless(tools_present(), f"needs {', '.join(TOOLS)}")
class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nulavio-connect-"))
        self.home = self.tmp / "home"
        (self.tmp / "run").mkdir(mode=0o700)
        (self.home / ".config").mkdir(parents=True)  # exists in every real account; xdg-mime writes there
        bus = f"unix:path={self.tmp / 'run' / 'bus'}"
        self.env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_RUNTIME_DIR": str(self.tmp / "run"),
            "PATH": "/usr/bin:/bin",
            "DBUS_SESSION_BUS_ADDRESS": bus,
            "NULAVIO_HOME": str(self.tmp / "nulavio"),
        }
        sys.path.insert(0, str(ROOT / "tests" / "lib"))
        from harness import private_bus_config

        (self.tmp / "dbus.conf").write_text(private_bus_config(self.tmp / "run" / "bus"))
        self.processes = [
            subprocess.Popen(
                ["dbus-daemon", f"--config-file={self.tmp / 'dbus.conf'}", "--nofork", "--nopidfile"],
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        ]
        deadline = time.monotonic() + 10
        while not (self.tmp / "run" / "bus").exists() and time.monotonic() < deadline:
            time.sleep(0.05)

    def tearDown(self):
        for proc in self.processes:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def own(self, *names: str) -> None:
        for name in names:
            self.processes.append(
                subprocess.Popen(
                    ["dbus-test-tool", "echo", "--session", f"--name={name}"],
                    env=self.env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            listed = subprocess.run(
                ["busctl", "--user", "--no-pager", "list", "--acquired"], env=self.env, capture_output=True, text=True
            ).stdout
            if all(n in listed for n in names):
                return
            time.sleep(0.1)
        self.fail(f"fake services did not start: {names}")

    def discover(self) -> dict:
        out = subprocess.run(
            [str(ROOT / "bin" / "nulavio"), "integrations", "--json"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
        return {s["id"]: s for s in json.loads(out)}

    def snapshot(self) -> dict:
        return {
            str(p.relative_to(self.home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.home.rglob("*") if p.is_file()
        }

    def test_nothing_running(self):
        found = self.discover()
        self.assertEqual(found["xdg-portals"]["state"], "unavailable")
        self.assertEqual(found["secret-service"]["state"], "unavailable")
        self.assertIn(found["plasma-browser-integration"]["state"], {"unavailable"})
        # Whatever the system default is (distribution files), it is reported, and it is not Nulavio.
        self.assertEqual(found["default-browser"]["state"], "available")
        self.assertTrue(found["default-browser"]["evidence"][0].startswith("xdg-settings default-web-browser: "))

    def test_services_found_with_evidence(self):
        self.own("org.freedesktop.portal.Desktop", "org.freedesktop.secrets", "org.kde.plasmashell")
        hosts = self.home / ".mozilla" / "native-messaging-hosts"
        hosts.mkdir(parents=True)
        (hosts / "org.kde.plasma.browser_integration.json").write_text(
            json.dumps(
                {
                    "name": "org.kde.plasma.browser_integration",
                    "path": "/usr/bin/true",
                    "type": "stdio",
                    "allowed_extensions": ["plasma-browser-integration@kde.org"],
                }
            )
        )
        found = self.discover()
        self.assertEqual(found["xdg-portals"]["state"], "available")
        self.assertIn("not reported", found["xdg-portals"]["evidence"][1], "a version must not be invented")
        self.assertEqual(found["secret-service"]["state"], "available")
        self.assertIn("dbus-test-tool", found["secret-service"]["detail"])
        self.assertEqual(found["plasma-browser-integration"]["state"], "available")

    def test_discovery_never_starts_a_service(self):
        """Asking whether a service runs must not start it (D-Bus activation)."""
        for proc in self.processes:
            proc.kill()
            proc.wait(timeout=10)
        services = self.tmp / "services"
        services.mkdir()
        marker = self.tmp / "started"
        # Reading a property of an absent name would start it; discovery must ask first.
        for name in ("org.freedesktop.secrets", "org.freedesktop.portal.Desktop"):
            (services / f"{name}.service").write_text(f"[D-BUS Service]\nName={name}\nExec=/usr/bin/touch {marker}\n")
        sock = self.tmp / "run" / "bus"
        sock.unlink(missing_ok=True)
        config = (self.tmp / "dbus.conf").read_text().replace("</busconfig>", f"<servicedir>{services}</servicedir></busconfig>")
        (self.tmp / "dbus.conf").write_text(config)
        self.processes = [
            subprocess.Popen(
                ["dbus-daemon", f"--config-file={self.tmp / 'dbus.conf'}", "--nofork", "--nopidfile"],
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        ]
        deadline = time.monotonic() + 10
        while not sock.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        found = self.discover()
        self.assertEqual(found["secret-service"]["state"], "unavailable")
        self.assertEqual(found["xdg-portals"]["state"], "unavailable")
        time.sleep(0.5)
        self.assertFalse(marker.exists(), "discovery started an activatable service")

    def test_a_broken_host_is_reported_not_trusted(self):
        hosts = self.home / ".mozilla" / "native-messaging-hosts"
        hosts.mkdir(parents=True)
        (hosts / "org.kde.plasma.browser_integration.json").write_text(
            json.dumps({"name": "x", "path": str(self.tmp / "missing-host"), "allowed_extensions": []})
        )
        self.assertEqual(self.discover()["plasma-browser-integration"]["state"], "error")

    def test_default_browser_is_read_not_changed(self):
        apps = self.home / ".local" / "share" / "applications"
        apps.mkdir(parents=True)
        (apps / "test-browser.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Test Browser\nExec=/usr/bin/true %u\n"
            "MimeType=x-scheme-handler/http;x-scheme-handler/https;text/html;\n"
        )
        subprocess.run(
            ["xdg-settings", "set", "default-web-browser", "test-browser.desktop"], env=self.env, check=True, capture_output=True
        )
        before = self.snapshot()
        found = self.discover()
        self.assertEqual(found["default-browser"]["state"], "available")
        self.assertIn("Test Browser", found["default-browser"]["detail"])
        self.assertEqual(self.snapshot(), before, "discovery changed a file")


if __name__ == "__main__":
    unittest.main()
