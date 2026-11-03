"""Encrypted profile storage (S5): gocryptfs containers, encrypted launcher profiles, supervised runs.

Real FUSE mounts in a temporary NULAVIO_HOME, artificial passwords. `nulavio run`
is exercised with a stand-in engine (a shell script that writes into the
profile and holds the engine lock) so the test can see the volume mounted
while "the engine" runs and locked after it exits; the real engine on an
encrypted profile is in tests/integration/test_vault_profiles.py.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from nulavio_launcher.vault import sodium, storage

REQUIRED = os.environ.get("NULAVIO_REQUIRE_GOCRYPTFS") == "1"
if not (sodium.available() and storage.tools_available()):  # pragma: no cover - CI installs both
    if REQUIRED:
        raise RuntimeError("gocryptfs, FUSE and libsodium are required for the storage tests")
    raise unittest.SkipTest("needs gocryptfs, FUSE (/dev/fuse) and libsodium")

from nulavio_launcher import profile  # noqa: E402
from nulavio_launcher.vault import profiles  # noqa: E402
from nulavio_launcher.vault.core import Vault, VaultError  # noqa: E402
from nulavio_launcher.vault.providers import Keyring  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}
PASSWORD = "artificial password 5"
MARKER = "FAKE-ENGINE-PLAINTEXT-MARKER"
FAKE_ENGINE = f"""#!/bin/sh
# Stand-in engine: answers --version, otherwise writes into its profile, holds the lock, waits.
if [ "$1" = "--version" ]; then echo "Nulavio Nulavio 158.0.1"; exit 0; fi
profile=""
while [ $# -gt 0 ]; do [ "$1" = "--profile" ] && profile="$2"; shift; done
echo "{MARKER}" > "$profile/session-data.txt"
ln -s "127.0.0.1:+$$" "$profile/lock"
trap 'rm -f "$profile/lock"; exit 0' TERM INT
while [ ! -e "$STOP_FILE" ]; do sleep 0.1; done
rm -f "$profile/lock"
"""
FAKE_SECRET_TOOL = """#!{python} -I
import json, os, sys
store = os.environ["NV_FAKE_KEYRING"]
items = json.load(open(store)) if os.path.exists(store) else []
cmd, rest = sys.argv[1], sys.argv[2:]
if cmd == "store":
    rest = rest[1:]
attrs = dict(zip(rest[::2], rest[1::2]))
if cmd == "store":
    items = [i for i in items if i["attrs"] != attrs] + [{{"attrs": attrs, "secret": sys.stdin.read()}}]
elif cmd == "lookup":
    match = [i for i in items if i["attrs"] == attrs]
    if not match:
        sys.exit(1)
    sys.stdout.write(match[0]["secret"])
elif cmd == "clear":
    items = [i for i in items if i["attrs"] != attrs]
open(store, "w").write(json.dumps(items))
"""


def wait_for(predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def contains(directory: Path, needle: bytes) -> bool:
    return any(needle in p.read_bytes() for p in directory.rglob("*") if p.is_file())


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-store-"))
        self.home = self.tmp / "home"
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for mountpoint in sorted(storage.mounted_paths()):
            if mountpoint.startswith(str(self.tmp)):
                subprocess.run(["fusermount3", "-u", "-z", mountpoint], check=False, capture_output=True)
        for dirpath, _dirs, _files in os.walk(self.tmp):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new_container(self, name: str = "work") -> tuple[storage.Container, Vault]:
        box = storage.Container(self.tmp / name)
        box.root.mkdir(mode=0o700)
        vault = Vault.create(box.vault_path)
        vault.add_password(PASSWORD, FAST)
        vault.save()
        box.init(vault)
        return box, vault

    def encrypted_profile(self, name: str = "work", keyring: Keyring | None = None) -> tuple[profile.Profile, str]:
        return profiles.create(name, password=PASSWORD, keyring=keyring, kdf=FAST, recovery_kdf=FAST)

    def fake_engine(self) -> dict:
        engine = self.tmp / "engine.sh"
        engine.write_text(FAKE_ENGINE)
        engine.chmod(0o700)
        self.stop_file = self.tmp / "stop-engine"
        return {**os.environ, "NULAVIO_ENGINE": str(engine), "STOP_FILE": str(self.stop_file)}

    def nulavio(self, *args, env=None, stdin: str = "", wait: bool = True):
        command = [str(ROOT / "bin" / "nulavio"), *args]
        if not wait:
            proc = subprocess.Popen(
                command,
                env=env or os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc.stdin.write(stdin)
            proc.stdin.close()
            return proc
        return subprocess.run(command, env=env or os.environ.copy(), input=stdin, capture_output=True, text=True, timeout=120)


class ContainerTest(StorageCase):
    def test_locked_volume_hides_files_and_names(self):
        box, vault = self.new_container()
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)
        box.mount(vault)
        self.assertTrue(box.mounted())
        (box.mountpoint / "bank-statement.txt").write_text(MARKER)
        box.unmount()
        self.assertFalse(box.mounted())
        self.assertEqual(list(box.mountpoint.iterdir()), [])
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)
        self.assertFalse(contains(box.root, MARKER.encode()))
        self.assertFalse(any("bank" in p.name for p in box.cipher.rglob("*")))  # names are encrypted too

    def test_locked_mount_point_takes_no_writes(self):
        box, _ = self.new_container()
        with self.assertRaises(PermissionError):
            (box.mountpoint / "prefs.js").write_text("plaintext")

    def test_wrong_key_and_wrong_container(self):
        box, _vault = self.new_container("a")
        _other, other_vault = self.new_container("b")
        stranger = Vault.load(box.vault_path)
        stranger.dek = bytearray(os.urandom(32))
        with self.assertRaises(storage.StorageError) as ctx:
            box.mount(stranger)
        self.assertEqual(ctx.exception.code, "wrong-key")
        with self.assertRaises(storage.StorageError):
            box.mount(other_vault)  # another profile's key
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)

    def test_plaintext_in_a_locked_profile_blocks_unlock(self):
        box, vault = self.new_container()
        os.chmod(box.mountpoint, 0o700)
        (box.mountpoint / "planted.js").write_text("x")
        with self.assertRaises(storage.StorageError) as ctx:
            box.mount(vault)
        self.assertEqual(ctx.exception.code, "mountpoint-not-empty")

    def test_rolled_back_key_file_is_refused(self):
        box, vault = self.new_container()
        old = box.vault_path.read_bytes()  # generation 1
        box.mount(vault)
        vault.add_recovery_code(FAST)
        vault.save()
        box.record_generation(vault)  # generation 2 inside the volume
        box.unmount()
        box.vault_path.write_bytes(old)
        restored = Vault.load(box.vault_path)
        restored.unlock_password(PASSWORD)
        with self.assertRaises(storage.StorageError) as ctx:
            box.mount(restored)
        self.assertEqual(ctx.exception.code, "rollback")
        self.assertFalse(box.mounted())

    def test_encrypt_existing_profile(self):
        plain = self.tmp / "old"
        plain.mkdir()
        (plain / "places.sqlite").write_text(MARKER)
        (plain / "sub").mkdir()
        (plain / "sub" / "x.json").write_text("{}")
        box = storage.Container(plain)
        box.root.mkdir(mode=0o700)
        vault = Vault.create(box.vault_path)
        vault.add_password(PASSWORD, FAST)
        vault.save()
        storage.encrypt_existing(plain, vault)
        self.assertEqual(list(plain.iterdir()), [])
        self.assertFalse((self.tmp / "old.plaintext-migrating").exists())
        self.assertFalse(contains(box.root, MARKER.encode()))
        box.mount(vault)
        self.assertEqual((plain / "places.sqlite").read_text(), MARKER)
        self.assertTrue((plain / "sub" / "x.json").exists())
        box.unmount()

    def test_failed_migration_restores_the_original(self):
        plain = self.tmp / "keep"
        plain.mkdir()
        (plain / "places.sqlite").write_text("data")
        box = storage.Container(plain)
        box.root.mkdir(mode=0o700)
        vault = Vault.create(box.vault_path)
        vault.add_password(PASSWORD, FAST)
        vault.save()
        with mock.patch.object(storage.shutil, "copy2", side_effect=OSError("disk full")), self.assertRaises(OSError):
            storage.encrypt_existing(plain, vault)
        self.assertEqual((plain / "places.sqlite").read_text(), "data")
        self.assertFalse(box.root.exists())
        self.assertEqual(storage.mounted_paths() & {str(plain)}, set())


class EncryptedProfileTest(StorageCase):
    def test_create_unlock_lock(self):
        prof, code = self.encrypted_profile()
        self.assertTrue(profiles.is_encrypted(prof))
        self.assertFalse(prof.exists())  # settings live inside the locked volume
        state = profiles.status(prof)
        self.assertEqual((state["locked"], sorted(m["method"] for m in state["methods"])), (True, ["password", "recovery-code"]))
        with self.assertRaises(VaultError):
            profiles.unlock(prof, password="not it")
        profiles.unlock(prof, password=PASSWORD).lock()
        self.assertTrue(prof.exists())
        self.assertEqual(prof.load_settings()["provider"], "builtin")
        profiles.lock(prof)
        self.assertFalse(prof.exists())
        profiles.unlock(prof, recovery_code=code).lock()
        profiles.lock(prof)

    def test_keyring_profile(self):
        tool = self.tmp / "secret-tool"
        tool.write_text(FAKE_SECRET_TOOL.format(python=sys.executable))
        tool.chmod(0o700)
        with mock.patch.dict(os.environ, {"NV_FAKE_KEYRING": str(self.tmp / "keyring.json")}):
            prof, _ = self.encrypted_profile(keyring=Keyring(str(tool)))
            self.assertIn("os_user_protected", profiles.status(prof)["protection"])
            profiles.unlock(prof, keyring=Keyring(str(tool))).lock()
            profiles.lock(prof)

    def test_cli_create_and_status(self):
        result = self.nulavio("vault", "create", "home", "--password-stdin", stdin=f"{PASSWORD}\n{PASSWORD}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"([0-9A-Z]{4}-){6}[0-9A-Z]{4}")
        status = json.loads(self.nulavio("vault", "status", "home", "--json").stdout)[0]
        self.assertTrue(status["locked"])
        self.assertEqual(self.nulavio("vault", "unlock", "home", "--password-stdin", stdin="nope\n").returncode, 1)


class SupervisedRunTest(StorageCase):
    def start(self, env):
        proc = self.nulavio("run", "--profile", "work", "--password-stdin", env=env, stdin=PASSWORD + "\n", wait=False)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        prof = profile.get("work")
        box = profiles.container(prof)
        wait_for(lambda: box.mounted() and (prof.path / "session-data.txt").exists())
        return proc, prof, box

    def test_volume_is_open_only_while_the_engine_runs(self):
        self.encrypted_profile()
        env = self.fake_engine()
        proc, prof, box = self.start(env)
        self.assertTrue(prof.running_pid())
        self.assertFalse(contains(box.root, MARKER.encode()))
        self.stop_file.touch()
        self.assertEqual(proc.wait(30), 0, proc.stderr.read())
        self.assertFalse(box.mounted())
        self.assertEqual(list(prof.path.iterdir()), [])
        self.assertFalse(contains(box.root, MARKER.encode()))

    def test_wrong_password_starts_nothing(self):
        self.encrypted_profile()
        env = self.fake_engine()
        result = self.nulavio("run", "--profile", "work", "--password-stdin", env=env, stdin="wrong\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not unlock", result.stderr)
        self.assertFalse(profiles.container(profile.get("work")).mounted())

    def test_stopping_the_launcher_closes_the_engine_and_locks(self):
        self.encrypted_profile()
        proc, prof, box = self.start(self.fake_engine())
        proc.send_signal(signal.SIGTERM)
        proc.wait(30)
        self.assertFalse(box.mounted())
        self.assertIsNone(prof.running_pid())

    def test_crashed_launcher_leaves_an_open_volume_that_status_reports(self):
        self.encrypted_profile()
        proc, prof, box = self.start(self.fake_engine())
        proc.kill()  # the supervisor dies; the engine (own session) keeps running
        proc.wait(10)
        self.assertTrue(box.mounted())
        with self.assertRaises(profile.ProfileInUse):
            profiles.lock(prof)  # never pulled from under a running engine without --force
        self.stop_file.touch()
        wait_for(lambda: prof.running_pid() is None)
        self.assertTrue(profiles.status(prof)["open_without_engine"])
        self.assertEqual(self.nulavio("vault", "lock", "work").returncode, 0)
        self.assertFalse(box.mounted())

    def test_force_lock_closes_the_engine(self):
        self.encrypted_profile()
        proc, prof, box = self.start(self.fake_engine())
        profiles.lock(prof, force=True)
        self.assertFalse(box.mounted())
        proc.wait(30)


class HelperApiTest(StorageCase):
    """`nulavio vault api`: what the browser's Shell calls (S6). Secrets travel on stdin only."""

    def api(self, request: dict) -> dict:
        result = self.nulavio("vault", "api", stdin=json.dumps(request))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_lifecycle(self):
        path = self.tmp / "group" / "abc.Cofre"
        path.mkdir(parents=True)
        (path / "prefs.js").write_text(MARKER)
        self.assertTrue(self.api({"op": "capabilities"})["storage"])
        code = self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})["recovery_code"]
        self.assertEqual(list(path.iterdir()), [])
        self.assertEqual(self.api({"op": "encrypt", "path": str(path), "password": PASSWORD}), {"error": "exists"})
        status = self.api({"op": "status", "path": str(path)})
        self.assertEqual((status["encrypted"], status["locked"]), (True, True))
        self.assertEqual(
            self.api({"op": "unlock", "path": str(path), "method": "password", "secret": "no"}), {"error": "wrong-secret"}
        )
        self.assertEqual(
            self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False}),
            {"unlocked": True},
        )
        self.assertEqual((path / "prefs.js").read_text(), MARKER)
        self.assertEqual(self.api({"op": "lock", "path": str(path)}), {"locked": True})
        new_code = self.api({"op": "new-recovery-code", "path": str(path), "current": code})["recovery_code"]
        self.assertEqual(
            self.api({"op": "unlock", "path": str(path), "method": "recovery-code", "secret": code}), {"error": "wrong-secret"}
        )
        self.assertEqual(
            self.api({"op": "add-password", "path": str(path), "current": new_code, "password": "second password"}),
            {"done": True},
        )
        password_ids = [m["id"] for m in self.api({"op": "status", "path": str(path)})["methods"] if m["method"] == "password"]
        self.assertEqual(len(password_ids), 2)
        self.api({"op": "remove-method", "path": str(path), "current": "second password", "envelope": password_ids[0]})
        self.assertEqual(
            self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD}), {"error": "wrong-secret"}
        )
        self.assertEqual(
            self.api({"op": "unlock", "path": str(path), "method": "password", "secret": "second password", "autolock": False}),
            {"unlocked": True},
        )
        self.api({"op": "lock", "path": str(path)})

    def test_lock_on_exit_watches_only_a_protected_profile(self):
        """UX4 "Bloquear agora" for the profile open in the browser: a watcher locks it once the engine is gone."""
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(self.api({"op": "lock-on-exit", "path": str(plain)}), {"error": "not-encrypted"})
        path = self.tmp / "aberto"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        from nulavio_launcher.vault import cli as vault_cli

        with mock.patch.object(vault_cli, "spawn_autolock") as spawn:
            self.assertEqual(vault_cli.api_request({"op": "lock-on-exit", "path": str(path)}), {"watching": True})
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0].path, path)

    def test_forget_before_deletion(self):
        path = self.tmp / "gone"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        self.assertEqual(self.api({"op": "forget", "path": str(path)}), {"error": "unlocked"})
        self.api({"op": "lock", "path": str(path)})
        self.assertEqual(self.api({"op": "forget", "path": str(path)}), {"forgotten": True})
        self.assertFalse(storage.Container(path).root.exists())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)  # an empty, deletable folder is all that is left

    def test_bad_requests(self):
        for request in (
            {"op": "status"},
            {"op": "status", "path": "relative/dir"},
            {"op": "explode", "path": "/x"},
            {"op": "unlock", "path": str(self.tmp), "method": "telepathy"},
        ):
            self.assertIn("error", self.api(request))
        too_big = self.nulavio("vault", "api", stdin="{" + " " * (70 * 1024) + "}")
        self.assertEqual(json.loads(too_big.stdout), {"error": "bad-request"})
        self.assertEqual(json.loads(self.nulavio("vault", "api", stdin="not json").stdout)["error"], "failed")

    def test_secrets_never_reach_argv_or_logs(self):
        path = self.tmp / "p"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        log = self.home / "state" / "launcher.log"
        self.assertNotIn(PASSWORD, log.read_text() if log.exists() else "")

    def test_autolock_after_the_profile_closes(self):
        path = self.tmp / "q"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD})  # starts the watcher
        box = storage.Container(path)
        self.assertTrue(box.mounted())
        env = self.fake_engine()
        engine = subprocess.Popen([env["NULAVIO_ENGINE"], "--profile", str(path)], env=env)
        wait_for(lambda: (path / "lock").is_symlink())
        time.sleep(1)
        self.assertTrue(box.mounted())  # still open while the engine runs
        self.stop_file.touch()
        engine.wait(10)
        wait_for(lambda: not box.mounted(), timeout=20)
        self.assertEqual(list(path.iterdir()), [])

    def test_autolock_when_nobody_opens_it(self):
        path = self.tmp / "r"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        prof = profile.Profile(name="r", path=path)
        self.assertEqual(profiles.autolock(prof, grace=0.5, poll=0.1), "unused")
        self.assertFalse(storage.Container(path).mounted())


if __name__ == "__main__":
    unittest.main()
