"""Nulavio Guard at run time (Nulavio build): changes made to a profile outside the browser.

The test closes the browser, changes the closed profile the way tools and
generic malware do, starts it again and checks what Guard reports, then
undoes or keeps each change through the review page. Only artificial data:
a throwaway certificate authority made for this test (its key is never
used), a native-messaging manifest pointing to /usr/bin/true, a smart-card
module with no reader, a pinned extension from the launcher's own cache.
"""

from __future__ import annotations

import hashlib
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
              changed("swapped@x", ext("1.0"), ext("2.0")),              // the held version, but not the file the engine held
              changed("unread@x", ext("1.0"), ext("2.0")),               // the held version, and no digest to compare
              changed("old@x", ext("1.0"), ext("2.0")),                  // a record that only names the version
              { id: "extension-added:held@x", kind: "extension-added", key: "held@x", after: ext("2.0") },
              { id: "pref-changed:network.proxy.type", kind: "pref-changed", key: "network.proxy.type", before: null, after: 1 },
            ];
            const kept = (version, digest) => ({ version, digest });
            const expected = { "held@x": kept("2.0", "aa"), "other@x": kept("2.0", "aa"), "on@x": kept("2.0", "aa"),
                               "swapped@x": kept("2.0", "aa"), "unread@x": kept("2.0", null), "old@x": "2.0" };
            const installed = { "held@x": "aa", "other@x": "aa", "on@x": "aa", "swapped@x": "bb", "unread@x": null,
                                "old@x": "aa" };
            return G.constructor.withoutHeldUpdates(findings, expected, installed).map(f => f.id);
            """
        )
        self.assertEqual(
            kept,
            [
                "extension-changed:other@x",
                "extension-changed:on@x",
                "extension-changed:unknown@x",
                "extension-changed:swapped@x",
                "extension-changed:unread@x",
                "extension-changed:old@x",
                "extension-added:held@x",
                "pref-changed:network.proxy.type",
            ],
        )
        # A difference found while the browser runs: made outside it, or the browser's own doing?
        outside = self.guard(
            """
            const ext = (version, active = true, foreign = false) => ({ name: "X", version, active, foreign, policy: false });
            const added = (id, foreign) => ({ id: `extension-added:${id}`, kind: "extension-added", key: id,
                                              after: ext("1.0", false, foreign) });
            const changed = id => ({ id: `extension-changed:${id}`, kind: "extension-changed", key: id,
                                     before: ext("1.0"), after: ext("2.0") });
            const removed = id => ({ id: `extension-removed:${id}`, kind: "extension-removed", key: id, before: ext("1.0") });
            const is = finding => G.constructor.madeOutside(finding, new Set(["mine@x"]));
            return {
              placed: is(added("placed@x", true)),         // another program placed it
              placedAsMine: is(added("mine@x", true)),     // and it stays so, whatever the browser did meanwhile
              installed: is(added("mine@x", false)),       // installed in the browser
              replaced: is(changed("theirs@x")),           // another version, and the browser did not update it
              updated: is(changed("mine@x")),              // the browser updated it
              deleted: is(removed("theirs@x")),
              uninstalled: is(removed("mine@x")),
              bare: G.constructor.madeOutside(changed("theirs@x")),
            };
            """
        )
        self.assertEqual(
            outside,
            {"placed": True, "placedAsMine": True, "installed": False, "replaced": True, "updated": False, "deleted": True,
             "uninstalled": False, "bare": True},
        )  # fmt: skip
        record = self.profile / "nulavio-guard.json"
        self.assertEqual(json.loads(record.read_text())["expected"], {}, "the record says what the engine holds: nothing now")

        def start_with(change) -> list:
            """Close, let `change` edit the record as if the last session had left it so, and start again."""
            self.session.stop()
            data = json.loads(record.read_text())
            change(data)
            record.write_text(json.dumps(data))
            self.m = type(self).m = self.session.restart()
            return self.guard("return (await G.check()).findings;")

        def later_window() -> str:
            """What the bar says in a window opened now."""
            return chrome_async(
                self.m,
                """
                const win = OpenBrowserWindow();
                let text = "";
                for (let i = 0; i < 100 && !text; i++) {
                  await new Promise(r => setTimeout(r, 100));
                  text = win.gNotificationBox?.getNotificationWithValue("nulavio-guard")?.messageText?.textContent ?? "";
                }
                win.close();
                return text;
                """,
            )

        # The bar says what waits now. Two settings changed while closed: counted. One is settled: the bar names the
        # one left, in this window and in one opened afterwards, and goes when nothing waits.
        proxy, host = "pref-changed:network.proxy.type", "pref-changed:network.proxy.http"
        findings = start_with(
            lambda data: data["snapshot"]["prefs"].update({"network.proxy.type": 1, "network.proxy.http": "192.0.2.1"})
        )
        self.assertEqual({f["id"] for f in findings}, {proxy, host})
        self.assertTrue(harness.wait_until(lambda: "2 mudanças" in self.bar(), timeout=30), self.bar())
        self.guard("await G.resolve(args[0], 'keep');", host)
        one = "uma mudança feita fora do Nulavio desde a última vez que ele rodou. Configuração de proteção alterada."
        self.assertTrue(harness.wait_until(lambda: one in self.bar(), timeout=10), self.bar())
        self.assertIn(one, later_window())
        self.guard("await G.resolve(args[0], 'keep');", proxy)
        self.assertTrue(harness.wait_until(lambda: self.bar() == "", timeout=10), "the bar stayed with nothing waiting")

        # The rest needs a real extension in the profile.
        entry, xpi = cached_extension()
        if not xpi:
            self.skipTest("no pinned extension in the local cache: the held update over real restarts was not tried")
        placed = self.profile / "extensions" / entry.xpi_name
        self.session.stop()
        placed.parent.mkdir(exist_ok=True)
        shutil.copyfile(xpi, placed)
        self.m = type(self).m = self.session.restart()
        added, changed, removed = (f"extension-{what}:{entry.id}" for what in ("added", "changed", "removed"))
        waiting = lambda: [f["id"] for f in self.guard("return G.findings();")]  # noqa: E731
        # Nothing else changed while it was closed, so nothing else makes the Guard look again: the engine reads the
        # extensions folder after the start-up check, and the Guard has to hear that it did.
        if not harness.wait_until(lambda: added in waiting(), 30):
            data = json.loads(record.read_text())
            self.fail(f"the extension placed in the profile was not reported; the record: {data['snapshot']['extensions']}")
        self.guard("await G.resolve(args[0], 'keep');", added)
        version = self.guard("return (await AddonManager.getAddonByID(args[0])).version;", entry.id)

        def start_as_if(seen: str, held: dict) -> list:
            """The last session saw version `seen` and noted `held`; this start finds the real one."""

            def change(data):
                data["snapshot"]["extensions"][entry.id]["version"] = seen
                data["expected"] = held

            return start_with(change)

        # The engine held exactly this version and this file for this start: nothing to report, no bar.
        digest = hashlib.sha256(placed.read_bytes()).hexdigest()
        self.assertEqual(start_as_if("0.0.1", {entry.id: {"version": version, "digest": digest}}), [])
        self.assertEqual(self.bar(), "")
        self.assertEqual(json.loads(record.read_text())["snapshot"]["extensions"][entry.id]["version"], version)
        # It held this version but another file: what is there now is not what the engine held. Reported.
        swapped = start_as_if("0.0.1", {entry.id: {"version": version, "digest": "0" * 64}})
        self.assertEqual([f["id"] for f in swapped], [changed])
        self.guard("await G.resolve(args[0], 'keep');", changed)
        # It held another version: what is there now did not come from the engine. Reported, and named in the bar.
        findings = start_as_if("0.0.1", {entry.id: {"version": "0.0.2", "digest": digest}})
        self.assertEqual([f["id"] for f in findings], [changed])
        self.assertTrue(harness.wait_until(lambda: "Nulavio Guard" in self.bar(), timeout=30), "no Guard bar")
        name = findings[0]["after"]["name"]
        self.assertIn(f"Extensão alterada: {name}", self.bar())
        self.assertIn("uma mudança", self.bar())
        self.guard("await G.resolve(args[0], 'undo');", changed)  # undone: the extension is taken out
        self.assertTrue(harness.wait_until(lambda: self.bar() == "", timeout=10), "the bar stayed with nothing waiting")
        self.assertTrue(harness.wait_until(lambda: not placed.exists(), timeout=10), "undone, and the file is still there")

        # While the browser runs. What the browser itself does to an extension is followed and not reported:
        # installed, turned off and on again, removed and the removal undone.
        in_record = lambda: json.loads(record.read_text())["snapshot"]["extensions"].get(entry.id)  # noqa: E731
        mine = "const addon = await AddonManager.getAddonByID(args[0]); "
        self.guard(
            """
            const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
            file.initWithPath(args[0]);
            await (await AddonManager.getInstallForFile(file)).install();
            """,
            str(xpi),
        )
        self.assertTrue(harness.wait_until(lambda: (in_record() or {}).get("active") is True, timeout=10), in_record())
        self.guard(mine + "await addon.disable();", entry.id)
        self.assertTrue(harness.wait_until(lambda: in_record()["active"] is False, timeout=10), in_record())
        self.guard(mine + "await addon.enable();", entry.id)
        self.assertTrue(harness.wait_until(lambda: in_record()["active"] is True, timeout=10), in_record())
        self.guard(mine + "await addon.uninstall(true);", entry.id)  # as about:addons does: it can still be undone
        self.assertTrue(harness.wait_until(lambda: in_record()["active"] is False, timeout=10), in_record())
        self.guard(mine + "addon.cancelUninstall();", entry.id)
        self.assertTrue(harness.wait_until(lambda: in_record()["active"] is True, timeout=10), in_record())
        self.assertEqual(waiting(), [])
        self.assertEqual(self.bar(), "")
        # Its file deleted by another program: not the browser's doing. Reported at the Guard's next look, which a
        # setting changed in the browser brings about, and not taken into the record unseen.
        self.assertTrue(placed.exists(), "the engine keeps an installed extension somewhere else than expected")
        placed.unlink()
        self.m.chrome("Services.prefs.setBoolPref('signon.rememberSignons', true);")
        self.assertTrue(harness.wait_until(lambda: removed in waiting(), timeout=20), waiting())
        self.assertTrue(harness.wait_until(lambda: f"Extensão removida: {name}" in self.bar(), timeout=10), self.bar())
        self.guard("await G.resolve(args[0], 'keep');", removed)
        self.assertTrue(harness.wait_until(lambda: self.bar() == "", timeout=10), "the bar stayed with nothing waiting")


if __name__ == "__main__":
    unittest.main()
