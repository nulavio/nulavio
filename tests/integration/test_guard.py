"""Nulavio Guard at run time (Nulavio build): changes made to a profile outside the browser.

The test closes the browser, changes the closed profile the way tools and
generic malware do, starts it again and checks what Guard reports, then
undoes or keeps each change through the review page. Only artificial data:
a throwaway certificate authority made for this test (its key is never
used), a native-messaging manifest pointing to /usr/bin/true, a smart-card
module with no reader, a pinned extension from the launcher's own cache.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from nulavio_launcher import extensions

MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard'
# A module that loads without hardware or a daemon; its certificates are not in the profile's own store.
PKCS11 = next(
    (
        p
        for p in (Path("/usr/lib64/pkcs11/p11-kit-trust.so"), Path("/usr/lib/x86_64-linux-gnu/pkcs11/p11-kit-trust.so"))
        if p.exists()
    ),
    None,
)
HOST_NAME = "net.nulavio.guard_test"


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


def cached_extension():
    """A pinned extension already in a local cache (no download in tests); never uBlock Origin (installed by policy)."""
    lock = extensions.load_lock()
    caches = [Path(os.environ["NULAVIO_TEST_XPI_CACHE"])] if os.environ.get("NULAVIO_TEST_XPI_CACHE") else []
    caches.append(Path.home() / ".cache" / "nulavio" / "xpi")
    for key in ("proton-pass", "keepassxc-browser", "bitwarden"):
        entry = lock[key]
        for cache in caches:
            path = cache / f"{entry.sha256}.xpi"
            if path.is_file() and extensions.sha256_file(path) == entry.sha256:
                return entry, path
    return None, None


@unittest.skipUnless(harness.nulavio_engine(), "Guard runs in the Nulavio build's Shell (NULAVIO_ENGINE)")
class GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.profile = cls.session.profile_dir
        cls.home = Path(cls.session.env["HOME"])
        cls.shots = harness.artifacts_dir() / "guard"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def guard(self, body: str, *args):
        return chrome_async(self.m, f"const G = {MODULE}; {body}", args)

    def shell_url(self) -> str:
        return self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    def bar(self) -> str:
        return self.m.chrome(
            "const n = gNotificationBox.getNotificationWithValue('nulavio-guard'); return n ? n.messageText.textContent : '';"
        )

    def open_review(self) -> None:
        self.m.navigate(self.shell_url() + "guard/review.html")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 15)
        )

    def cards(self) -> dict:
        return {
            c["kind"] + ":" + c["id"].split(":", 1)[1]: c
            for c in self.m.execute(
                "return [...document.querySelectorAll('#findings > li')].map(li => ({id: li.dataset.findingId,"
                " kind: li.dataset.kind, title: li.querySelector('h2').textContent,"
                " detail: li.querySelector('.finding__detail').textContent,"
                " actions: [...li.querySelectorAll('button')].map(b => b.dataset.action)}));"
            )
        }

    def click(self, finding_id: str, action: str) -> None:
        before = int(self.m.execute("return Number(document.body.dataset.count);"))
        self.m.execute(
            'document.querySelector(`#findings > li[data-finding-id="${CSS.escape(arguments[0])}"]'
            ' button[data-action="${arguments[1]}"]`).click();',
            [finding_id, action],
        )
        self.assertTrue(
            harness.wait_until(lambda: int(self.m.execute("return Number(document.body.dataset.count);")) < before, 30)
        )

    def shoot(self, name: str) -> None:
        for scheme in ("light", "dark"):
            self.m.execute(
                "document.documentElement.dataset.theme = arguments[0]; document.body.style.display = 'none';"
                "document.body.offsetHeight; document.body.style.display = ''; return document.body.offsetHeight;",
                [scheme],
            )
            time.sleep(0.3)
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.execute("delete document.documentElement.dataset.theme;")

    # -- tests -------------------------------------------------------------------------

    def test_01_first_start_records_and_reports_nothing(self):
        record = self.profile / "nulavio-guard.json"
        self.assertTrue(harness.wait_until(record.exists, timeout=30), "no Guard record")
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        result = self.guard("return await G.check();")
        self.assertIn(result["state"], ("first", "clean"), result)
        self.assertEqual(result["findings"], [])
        self.assertEqual(self.bar(), "")
        data = json.loads(record.read_text())
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["pending"], [])
        self.assertIn("extensions", data["snapshot"])

    def test_02_changes_made_while_closed_are_reported_and_undone_or_kept(self):
        self.session.stop()
        # -- what tools and malware leave behind, on a closed profile --
        with open(self.profile / "prefs.js", "a", encoding="utf-8") as prefs_js:
            prefs_js.write('user_pref("network.proxy.type", 1);\nuser_pref("network.proxy.http", "127.0.0.1");\n')
        with open(self.profile / "user.js", "a", encoding="utf-8") as user_js:  # it holds the test's Marionette prefs
            user_js.write('user_pref("browser.safebrowsing.malware.enabled", false);\n')
        hosts = self.home / ".mozilla" / "native-messaging-hosts"
        hosts.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": HOST_NAME,
            "description": "test",
            "path": "/usr/bin/true",
            "type": "stdio",
            "allowed_extensions": ["x@y"],
        }
        (hosts / f"{HOST_NAME}.json").write_text(json.dumps(manifest))
        expected = {"pref-changed:network.proxy.type", "pref-changed:network.proxy.http", "userjs-changed:user.js"}
        expected.add(f"host-added:{hosts / f'{HOST_NAME}.json'}")
        entry, xpi = cached_extension()
        if xpi:
            (self.profile / "extensions").mkdir(exist_ok=True)
            shutil.copyfile(xpi, self.profile / "extensions" / entry.xpi_name)
            expected.add(f"extension-added:{entry.id}")
        tools = shutil.which("certutil") and shutil.which("openssl")
        if tools:
            ca = self.session.tmp / "ca"
            ca.mkdir()
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "2",
                 "-subj", "/CN=Nulavio Guard Test CA", "-keyout", str(ca / "key.pem"), "-out", str(ca / "ca.pem")],
                check=True, capture_output=True,
            )  # fmt: skip
            add_ca = ["certutil", "-A", "-d", f"sql:{self.profile}", "-n", "Nulavio Guard Test CA", "-t", "C,,"]
            subprocess.run([*add_ca, "-i", str(ca / "ca.pem")], stdin=subprocess.DEVNULL, check=True, capture_output=True)
            (ca / "key.pem").unlink()
        if shutil.which("modutil") and PKCS11:
            module = ["-add", "Nulavio Guard Test Module", "-libfile", str(PKCS11)]
            add_module = ["modutil", "-dbdir", f"sql:{self.profile}", *module]
            # modutil asks to press Enter before changing a database; answer it, never wait on a terminal.
            subprocess.run([*add_module, "-force"], input="\n", text=True, check=True, capture_output=True)
            expected.add("module-added:Nulavio Guard Test Module")

        self.m = type(self).m = self.session.restart()
        self.assertTrue(harness.wait_until(lambda: "Nulavio Guard" in self.bar(), timeout=30), "no Guard bar")
        if xpi:  # the engine registers a sideloaded extension a little after start-up; it joins the list then
            wanted = f"extension-added:{entry.id}"
            self.assertTrue(harness.wait_until(lambda: any(f["id"] == wanted for f in self.guard("return G.findings();")), 30))
        findings = {f["id"]: f for f in self.guard("return G.findings();")}
        if tools:
            roots = [f for f in findings.values() if f["kind"] == "root-added"]
            self.assertEqual(len(roots), 1, findings.keys())
            self.assertIn("Nulavio Guard Test CA", roots[0]["after"]["subject"])
            expected.add(roots[0]["id"])
        self.assertTrue(expected <= set(findings), f"missing: {expected - set(findings)}")
        self.assertIn(f"{len(findings)} mudança", self.bar())
        self.assertFalse(findings["pref-changed:browser.safebrowsing.malware.enabled"]["after"])
        self.assertEqual(findings["pref-changed:network.proxy.type"]["before"], None)
        self.assertTrue(findings["pref-changed:network.proxy.type"]["undoable"])
        self.assertFalse(findings["userjs-changed:user.js"]["undoable"])

        # -- the review page --
        self.open_review()
        cards = self.cards()
        self.assertEqual(len(cards), len(findings))
        self.assertEqual(cards["pref-changed:network.proxy.type"]["actions"], ["undo", "keep"])
        self.assertEqual(cards[f"host-added:{hosts / f'{HOST_NAME}.json'}"]["actions"], ["reveal", "keep"])
        self.assertIn("/usr/bin/true", cards[f"host-added:{hosts / f'{HOST_NAME}.json'}"]["detail"])
        self.shoot("review")

        self.click("pref-changed:network.proxy.type", "undo")
        self.click("pref-changed:network.proxy.http", "undo")
        self.assertFalse(self.m.chrome("return Services.prefs.prefHasUserValue('network.proxy.type');"))
        if tools:
            root = next(i for i in findings if i.startswith("root-added:"))
            self.click(root, "undo")
            gone = self.guard(
                "const db = Cc['@mozilla.org/security/x509certdb;1'].getService(Ci.nsIX509CertDB);"
                "return !(await db.getCerts()).some(c => c.sha256Fingerprint === args[0]);",
                root.split(":", 1)[1],
            )
            self.assertTrue(gone)
        if xpi:
            self.click(f"extension-added:{entry.id}", "undo")
            self.assertIsNone(self.guard("return (await AddonManager.getAddonByID(args[0]))?.id ?? null;", entry.id))
        if "module-added:Nulavio Guard Test Module" in findings:
            self.click("module-added:Nulavio Guard Test Module", "undo")
        for remaining in list(self.cards().values()):
            self.click(remaining["id"], "keep")
        self.assertEqual(self.m.execute("return document.body.dataset.state;"), "empty")
        self.assertTrue(harness.wait_until(lambda: self.bar() == "", timeout=10))

        # -- next start: what was undone stays undone; what was kept is not reported again --
        self.m = type(self).m = self.session.restart()
        result = self.guard("return await G.check();")
        self.assertEqual(result["findings"], [], result["findings"])
        self.assertFalse(self.m.chrome("return Services.prefs.prefHasUserValue('network.proxy.type');"))

    def test_03_changes_made_in_the_browser_are_not_reported(self):
        self.m.chrome("Services.prefs.setIntPref('network.cookie.cookieBehavior', 4);")
        self.m.chrome("Services.prefs.setBoolPref('signon.rememberSignons', false);")
        time.sleep(2)  # the record follows the session's own changes
        self.m = type(self).m = self.session.restart()
        result = self.guard("return await G.check();")
        self.assertEqual(result["findings"], [], result["findings"])
        self.assertEqual(self.bar(), "")
        # The Shell's event page starts with the browser on later starts too (the profile icon is its work).
        script = "return document.getElementById('shell_nulavio_net-BAP')?.getAttribute('tooltiptext') ?? '';"
        self.assertTrue(harness.wait_until(lambda: "Pessoal" in self.m.chrome(script), timeout=20), self.m.chrome(script))

    def test_04_an_update_the_engine_held_for_this_start_is_not_a_change_made_outside(self):
        # What counts as held: an update of an installed extension, in the engine's "postponed" state. Nothing else.
        held = self.guard(
            """
            const installs = [
              { state: AddonManager.STATE_POSTPONED, existingAddon: { id: "held@x" }, version: "2.0" },
              { state: AddonManager.STATE_DOWNLOADING, existingAddon: { id: "downloading@x" }, version: "9" },
              { state: AddonManager.STATE_POSTPONED, existingAddon: null, version: "1" },
            ];
            return G.constructor.heldUpdates(installs);
            """
        )
        self.assertEqual(held, {"held@x": "2.0"})
        kept = self.guard(
            """
            const ext = (version, active = true) => ({ name: "X", version, active, foreign: false, policy: false });
            const kind = "extension-changed";
            const changed = (id, before, after) => ({ id: `${kind}:${id}`, kind, key: id, before, after });
            const findings = [
              changed("held@x", ext("1.0"), ext("2.0")),                 // the version the engine held: the browser's own update
              changed("other@x", ext("1.0"), ext("2.1")),                // another version than the one held
              changed("on@x", ext("1.0", false), ext("2.0", true)),      // the held version, but also turned on while closed
              changed("unknown@x", ext("1.0"), ext("2.0")),              // nothing was held for it
              { id: "extension-added:held@x", kind: "extension-added", key: "held@x", after: ext("2.0") },
              { id: "pref-changed:network.proxy.type", kind: "pref-changed", key: "network.proxy.type", before: null, after: 1 },
            ];
            const expected = { "held@x": "2.0", "other@x": "2.0", "on@x": "2.0" };
            return G.constructor.withoutHeldUpdates(findings, expected).map(f => f.id);
            """
        )
        self.assertEqual(
            kept,
            [
                "extension-changed:other@x",
                "extension-changed:on@x",
                "extension-changed:unknown@x",
                "extension-added:held@x",
                "pref-changed:network.proxy.type",
            ],
        )
        record = self.profile / "nulavio-guard.json"
        self.assertEqual(json.loads(record.read_text())["expected"], {}, "the record says what the engine holds: nothing now")

        # The same through a real start, with a real extension in the profile.
        entry, xpi = cached_extension()
        if not xpi:
            self.skipTest("no pinned extension in the local cache")
        self.session.stop()
        (self.profile / "extensions").mkdir(exist_ok=True)
        shutil.copyfile(xpi, self.profile / "extensions" / entry.xpi_name)
        self.m = type(self).m = self.session.restart()
        added = f"extension-added:{entry.id}"
        self.assertTrue(harness.wait_until(lambda: any(f["id"] == added for f in self.guard("return G.findings();")), 30))
        self.guard("await G.resolve(args[0], 'keep');", added)
        version = self.guard("return (await AddonManager.getAddonByID(args[0])).version;", entry.id)

        def start_as_if(seen: str, held: dict) -> list:
            """The last session saw version `seen` and noted `held`; this start finds the real one."""
            self.session.stop()
            data = json.loads(record.read_text())
            data["snapshot"]["extensions"][entry.id]["version"] = seen
            data["expected"] = held
            record.write_text(json.dumps(data))
            self.m = type(self).m = self.session.restart()
            return self.guard("return (await G.check()).findings;")

        # The engine held exactly this version for this start: nothing to report, no bar.
        self.assertEqual(start_as_if("0.0.1", {entry.id: version}), [])
        self.assertEqual(self.bar(), "")
        self.assertEqual(json.loads(record.read_text())["snapshot"]["extensions"][entry.id]["version"], version)
        # It held another version: what is there now did not come from the engine. Reported, and named in the bar.
        findings = start_as_if("0.0.1", {entry.id: "0.0.2"})
        self.assertEqual([f["id"] for f in findings], [f"extension-changed:{entry.id}"])
        self.assertTrue(harness.wait_until(lambda: "Nulavio Guard" in self.bar(), timeout=30), "no Guard bar")
        name = findings[0]["after"]["name"]
        self.assertIn(f"Extensão alterada: {name}", self.bar())
        self.assertIn("uma mudança", self.bar())
        self.guard("await G.resolve(args[0], 'undo');", f"extension-changed:{entry.id}")


if __name__ == "__main__":
    unittest.main()
