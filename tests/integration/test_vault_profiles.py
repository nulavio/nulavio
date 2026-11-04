"""Encrypted profiles with the real engine (S5, ADR 0006). Needs gocryptfs and FUSE.

Track A: a launcher profile is created encrypted, unlocked, used by the engine
(a unique address is visited), locked again; then nothing readable is left on
disk, and an engine started directly on the locked profile writes nothing.
Track B (Nulavio build): a profile of the browser's own group is encrypted; the
profile selector shows it locked, switching refuses, and a typed address that
routing would send there stops with an explanation instead of starting it.
Artificial passwords only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from marionette import Marionette

from nulavio_launcher.vault import sodium, storage
from nulavio_launcher.vault.core import Vault

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "artificial password 7"
READY = sodium.available() and storage.tools_available()


def contains(directory: Path, needle: bytes) -> bool:
    return any(needle in p.read_bytes() for p in directory.rglob("*") if p.is_file())


def force_cleanup(tmp: Path) -> None:
    for mountpoint in sorted(storage.mounted_paths()):
        if mountpoint.startswith(str(tmp)):
            subprocess.run(["fusermount3", "-u", "-z", mountpoint], check=False, capture_output=True)
    for dirpath, _dirs, _files in os.walk(tmp):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(READY and harness.engine_available(), "needs gocryptfs, FUSE, libsodium and a Gecko engine")
class EncryptedLauncherProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-vault-itest-"))
        self.addCleanup(force_cleanup, self.tmp)
        self.env = {**os.environ, "NULAVIO_HOME": str(self.tmp / "home")}
        self.profile_dir = self.tmp / "home" / "data" / "profiles" / "work"
        self.box = storage.Container(self.profile_dir)

    def nulavio(self, *args, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / "nulavio"), *args], env=self.env, input=stdin, capture_output=True, text=True, timeout=300
        )

    def test_profile_data_is_unreadable_when_locked(self):
        created = self.nulavio("vault", "create", "work", "--password-stdin", stdin=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.nulavio("vault", "unlock", "work", "--password-stdin", stdin=PASSWORD + "\n").returncode, 0)
        command = self.nulavio("run", "--dry-run", "--profile", "work").stdout.strip().split()
        prefs = dict(harness.TEST_PREFS)
        with open(self.profile_dir / "user.js", "a", encoding="utf-8") as handle:
            handle.write("".join(f"user_pref({k!r}, {harness.Session._js(v)});\n".replace("'", '"') for k, v in prefs.items()))
        token = f"vault-{uuid.uuid4().hex[:12]}"
        with harness.FixtureServer() as fx:
            engine = subprocess.Popen(
                [*command, "--marionette", "--headless", "--new-instance"],
                env={**self.env, "MOZ_HEADLESS": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            port_file = self.profile_dir / "MarionetteActivePort"
            self.assertTrue(harness.wait_until(lambda: port_file.exists() and port_file.read_text().strip(), timeout=90))
            client = Marionette(int(port_file.read_text().strip())).connect()
            client.new_session()
            client.navigate(fx.url(f"/page/{token}"))
            self.assertEqual(client.execute("return document.title;"), token)
            client.quit()
            engine.wait(60)
        self.assertTrue(contains(self.profile_dir, token.encode()))  # history is in the profile while unlocked
        locked = self.nulavio("vault", "lock", "work")
        self.assertEqual(locked.returncode, 0, locked.stderr)
        self.assertEqual(list(self.profile_dir.iterdir()), [])
        self.assertFalse(contains(self.box.root, token.encode()), "the visited address is readable on disk")

        # An engine started directly on the locked profile cannot write plaintext there.
        direct = subprocess.Popen(
            [command[0], "--profile", str(self.profile_dir), "--headless", "--no-remote", "about:blank"],
            env={**self.env, "MOZ_HEADLESS": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            direct.wait(20)
        except subprocess.TimeoutExpired:
            direct.kill()
            direct.wait()
        self.assertEqual(list(self.profile_dir.iterdir()), [])
        self.assertFalse(self.box.mounted())


SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
    ".SelectableProfileService;"
)
TYPE_JS = """
const [text] = arguments;
gURLBar.focus();
gURLBar.select();
const tip = Cc["@mozilla.org/text-input-processor;1"].createInstance(Ci.nsITextInputProcessor);
if (!tip.beginInputTransactionForTests(window)) {
  throw new Error("could not start an input transaction");
}
for (const ch of text) {
  const event = ch === "\\n"
    ? new KeyboardEvent("", {key: "Enter", code: "Enter", keyCode: 13})
    : new KeyboardEvent("", {key: ch});
  tip.keydown(event);
  tip.keyup(event);
}
"""


@unittest.skipUnless(READY and harness.nulavio_engine(), "needs gocryptfs, FUSE, libsodium and the Nulavio build")
class LockedGroupProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.vault_id = cls.call("return P.create({templateId: 'banking', name: 'Cofre'});")["ok"]
        cls.path = Path(cls.call("return (await SPS.getProfile(args[0])).path;", cls.vault_id)["ok"])
        box = storage.Container(cls.path)
        box.root.mkdir(mode=0o700)
        vault = Vault.create(box.vault_path)
        vault.add_password(PASSWORD, {"ops": 1, "mem": 8 * 1024 * 1024})
        vault.save()
        storage.encrypt_existing(cls.path, vault)
        vault.lock()
        cls.box = box

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.box.mounted():
                cls.box.unmount()
            for top in (cls.box.root, cls.path):
                for dirpath, _d, _f in os.walk(top):
                    os.chmod(dirpath, 0o700)
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    @classmethod
    def call(cls, body: str, *args):
        script = (
            "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
            f"(async () => {{ {PRELUDE} {body} }})()"
            ".then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
        )
        cls.m.set_context("chrome")
        try:
            result = cls.m.execute_async(script, list(args))
        finally:
            cls.m.set_context("content")
        return result

    def test_selector_shows_locked_switching_refuses_and_delete_drops_the_keys(self):
        profiles = self.call("return (await P.list()).profiles;")["ok"]
        cofre = next(p for p in profiles if p["id"] == self.vault_id)
        self.assertEqual((cofre["encrypted"], cofre["locked"]), (True, True))
        self.assertEqual(self.call("return P.switchTo(args[0]);", self.vault_id), {"error": "locked"})
        self.assertEqual(
            self.call("return R.openIn(args[0], args[1]);", self.vault_id, self.server.url("/page/x")), {"error": "locked"}
        )
        time.sleep(2)
        self.assertEqual(self.session.processes_for(self.path), [])
        self.assertEqual(list(self.path.iterdir()), [])
        # Deleting a locked protected profile drops its keys first, then the profile.
        self.assertEqual(self.call("return P.remove(args[0]);", self.vault_id), {"ok": None})
        self.assertFalse(self.box.root.exists())
        self.assertFalse(any(p["id"] == self.vault_id for p in self.call("return (await P.list()).profiles;")["ok"]))

    def test_routing_default_destination_locked_asks_to_unlock_instead_of_starting_it(self):
        """UX6: a locked profile as the default destination for links from other apps asks to unlock it here."""
        self.assertEqual(self.call("await R.setFallback(args[0]); return R.fallback();", self.vault_id), {"ok": self.vault_id})
        try:
            # This instance receives links from other apps: the group's default profile. The link arrives as
            # a remote command line does (an instance cannot send one to itself), through the same handler.
            self.call(
                "const S = ChromeUtils.importESModule('resource:///modules/profiles/SelectableProfileService.sys.mjs')"
                ".SelectableProfileService; await S.setDefaultProfileForGroup(); return true;"
            )
            url = self.server.url("/page/default-to-the-vault")
            self.call(
                "const line = Cu.createCommandLine([args[0]], null, Ci.nsICommandLine.STATE_REMOTE_EXPLICIT);"
                "R.handleCommandLine(line); return line.length;",
                url,
            )
            tabs = lambda: self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);")  # noqa: E731
            self.assertTrue(
                harness.wait_until(
                    lambda: any("/vault/unlock.html" in u and f"p={self.vault_id}" in u for u in tabs()), timeout=20
                ),
                tabs(),
            )
            time.sleep(1)
            self.assertEqual(self.server.requests_to("/page/default-to-the-vault"), [])
            self.assertEqual(self.session.processes_for(self.path), [])
            self.assertEqual(list(self.path.iterdir()), [])
        finally:
            self.call("await R.setFallback(0);")

    def test_routing_to_a_locked_profile_asks_to_unlock_instead_of_starting_it(self):
        rule = self.call(
            "return R.addRule({site: '127.0.0.1', match: 'host', action: 'open-in', profileId: args[0]});", self.vault_id
        )["ok"]
        try:
            self.m.navigate("about:blank")
            self.m.chrome("if (window.gDialogBox?.isOpen) { window.gDialogBox.dialog?.close(); }")
            self.m.chrome(TYPE_JS, [self.server.url("/page/to-the-vault")])
            time.sleep(0.3)
            self.m.chrome(TYPE_JS.replace("gURLBar.select();", ""), ["\n"])
            tabs = lambda: self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);")  # noqa: E731
            self.assertTrue(
                harness.wait_until(
                    lambda: any("/vault/unlock.html" in u and f"p={self.vault_id}" in u for u in tabs()), timeout=20
                ),
                tabs(),
            )
            time.sleep(1)
            self.assertEqual(self.server.requests_to("/page/to-the-vault"), [])
            self.assertEqual(self.session.processes_for(self.path), [])
            self.assertEqual(list(self.path.iterdir()), [])
        finally:
            self.call("await R.removeRule(args[0]);", rule)


if __name__ == "__main__":
    unittest.main()
