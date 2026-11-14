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
import re
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
from nulavio_launcher.vault import cli as vault_cli  # noqa: E402
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


INTERRUPTED_MIGRATION = """
import os, shutil, signal, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nulavio_launcher.vault import storage
from nulavio_launcher.vault.core import Vault
path, how, password = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
vault = Vault.create(storage.Container(path).vault_path)
vault.add_password(password, {"ops": 1, "mem": 8 * 1024 * 1024})
vault.save()
copied = []
real_copy, real_rmtree = shutil.copy2, shutil.rmtree
def copy(*args, **kwargs):
    copied.append(args[0])
    if len(copied) == 3 and how in ("kill-mid-copy", "term-mid-copy"):
        os.kill(os.getpid(), signal.SIGKILL if how == "kill-mid-copy" else signal.SIGTERM)
    return real_copy(*args, **kwargs)
def rmtree(target, *args, **kwargs):
    if how == "kill-after-copy" and str(target).endswith(".plaintext-migrating"):
        os.kill(os.getpid(), signal.SIGKILL)
    return real_rmtree(target, *args, **kwargs)
shutil.copy2, shutil.rmtree = copy, rmtree
storage.encrypt_existing(path, vault)
"""


class InterruptedMigrationTest(StorageCase):
    # Audit V5: an interrupted migration left the whole profile in the clear next to it,
    # marked as protected, and nothing ever looked at it again.
    def plain_profile(self) -> Path:
        path = self.tmp / "work"
        path.mkdir()
        for index in range(10):
            (path / f"file{index}.txt").write_text(f"{MARKER} {index}")
        return path

    def interrupt(self, path: Path, how: str) -> subprocess.CompletedProcess:
        script = self.tmp / "migrate.py"
        script.write_text(INTERRUPTED_MIGRATION)
        args = [sys.executable, str(script), str(ROOT / "launcher"), str(path), how, PASSWORD]
        return subprocess.run(args, capture_output=True, text=True, timeout=120)

    def staging(self, path: Path) -> Path:
        return path.with_name(path.name + ".plaintext-migrating")

    def test_sigterm_is_cleaned_up_at_once(self):
        path = self.plain_profile()
        self.assertNotEqual(self.interrupt(path, "term-mid-copy").returncode, 0)
        self.assertFalse(self.staging(path).exists())
        self.assertFalse(storage.Container(path).root.exists())
        self.assertEqual(len(list(path.iterdir())), 10)

    def test_a_killed_copy_is_undone_the_next_time(self):
        path = self.plain_profile()
        self.assertEqual(self.interrupt(path, "kill-mid-copy").returncode, -signal.SIGKILL)
        self.assertTrue(self.staging(path).exists())
        prof = profile.Profile(name="work", path=path)
        self.assertFalse(profiles.is_encrypted(prof))  # the profile is back as it was, unprotected
        self.assertFalse(self.staging(path).exists())
        self.assertFalse(storage.Container(path).mounted())
        self.assertEqual(sorted(p.name for p in path.iterdir()), [f"file{i}.txt" for i in range(10)])

    def test_a_complete_copy_is_finished_the_next_time(self):
        path = self.plain_profile()
        self.assertEqual(self.interrupt(path, "kill-after-copy").returncode, -signal.SIGKILL)
        self.assertTrue(self.staging(path).exists())
        prof = profile.Profile(name="work", path=path)
        self.assertTrue(profiles.is_encrypted(prof))
        self.assertFalse(self.staging(path).exists())  # the plaintext copy is gone
        self.assertFalse((storage.Container(path).root / storage.MIGRATED).exists())
        self.assertFalse(contains(self.tmp, MARKER.encode()))
        profiles.unlock(prof, password=PASSWORD).lock()
        self.assertEqual(len(list(path.iterdir())), 10 + 1)  # and the state directory
        profiles.lock(prof)


class CoreDumpTest(unittest.TestCase):
    def test_vault_commands_and_gocryptfs_write_no_core_dumps(self):
        # Threat model U-T13, audit V8: a crash would write the password, the DEK or the volume key.
        script = (
            "import resource, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'launcher')!r})\n"
            "from nulavio_launcher.vault import cli\n"
            "cli.no_core_dumps()\n"
            "print(resource.getrlimit(resource.RLIMIT_CORE)[0])\n"
            "import subprocess\n"
            "print(subprocess.run(['sh', '-c', 'ulimit -c'], capture_output=True, text=True).stdout.strip())\n"
        )
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=True)
        lines = out.stdout.split()
        self.assertEqual(lines[0], "0")  # no core file from this process
        self.assertEqual(lines[-1], "0")  # nor from gocryptfs, which it starts
        dumpable = script.replace(
            "print(resource", "import ctypes\nprint(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))\nprint(resource"
        )
        out = subprocess.run([sys.executable, "-c", dumpable], capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(out.stdout.split()[0], "0")  # PR_GET_DUMPABLE: no debugger from other processes either


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

    def test_a_volume_that_ended_without_a_lock_is_read_only_again(self):
        # Audit V6: a crash, a killed gocryptfs or its -idle timer left the empty mount point
        # writable (0700); an engine started on it would write a new profile in the clear.
        prof, _ = self.encrypted_profile()
        profiles.unlock(prof, password=PASSWORD).lock()
        box = profiles.container(prof)
        subprocess.run(["fusermount3", "-u", "-z", str(box.mountpoint)], check=True, capture_output=True)  # not unmount()
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o700)
        self.assertTrue(profiles.status(prof)["locked"])
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)
        with self.assertRaises(PermissionError):
            (box.mountpoint / "prefs.js").write_text("plaintext")

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
        # The stand-in engine writes its file before it takes the lock: wait for both, or a test that
        # reads the lock right away races it (seen once in CI, run 42809091803).
        wait_for(lambda: box.mounted() and (prof.path / "session-data.txt").exists() and prof.running_pid())
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

    def test_a_run_says_what_it_did_with_a_replacement_left_unfinished(self):
        # Codex review of #252: `nulavio run` settled a replacement left unfinished and said nothing, so a new
        # code someone had written down stopped working without a word.
        self.encrypted_profile()
        prof = profile.get("work")
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        env = self.fake_engine()
        proc, _prof, _box = self.start(env)
        self.stop_file.touch()
        self.assertEqual(proc.wait(30), 0)
        self.assertIn("was undone", proc.stderr.read())

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
        # Until the new code is typed back, the old one still opens the profile; only the new one confirms (#187).
        self.assertEqual(self.api({"op": "confirm-recovery-code", "path": str(path), "current": code}), {"error": "wrong-secret"})
        self.assertEqual(self.api({"op": "confirm-recovery-code", "path": str(path), "current": new_code}), {"done": True})
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

    def test_a_method_changed_while_locked_is_recorded_in_the_volume(self):
        # LESIS 38ec3168: the recovery code was replaced with the profile locked, so the generation
        # inside the volume stayed behind, and the key file from before, put back, opened the
        # profile with the old code (threat model U-T21).
        prof, old_code = self.encrypted_profile()
        box = profiles.container(prof)
        self.assertFalse(box.mounted())
        before = box.vault_path.read_bytes()
        request = {"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD}
        new_code = vault_cli.api_request(request)["recovery_code"]
        # The profile stayed locked, and nothing of the maintenance mount is left.
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(prof.path).st_mode & 0o777, 0o500)
        self.assertEqual([p.name for p in box.root.glob("maintenance-*")], [])
        self.assertEqual([m for m in storage.mounted_paths() if m.startswith(str(box.root))], [])
        after = box.vault_path.read_bytes()
        for path in (box.vault_path, box.vault_path.with_suffix(".json.bak")):
            path.write_bytes(before)  # what someone with the old code and an old copy of the file does
        for attempt in ({"recovery_code": old_code}, {"password": PASSWORD}):
            with self.subTest(attempt=next(iter(attempt))), self.assertRaises(storage.StorageError) as ctx:
                profiles.unlock(prof, **attempt)
            self.assertEqual(ctx.exception.code, "rollback")
            self.assertFalse(box.mounted())
        # The old file is refused for another change too, and stays as it was.
        with self.assertRaises(storage.StorageError) as ctx:
            vault_cli.api_request({"op": "add-password", "path": str(prof.path), "current": PASSWORD, "password": "another one"})
        self.assertEqual(ctx.exception.code, "rollback")
        self.assertEqual(box.vault_path.read_bytes(), before)
        for path in (box.vault_path, box.vault_path.with_suffix(".json.bak")):
            path.write_bytes(after)
        profiles.unlock(prof, recovery_code=new_code).lock()
        profiles.lock(prof)

    def test_a_method_is_not_changed_when_the_volume_cannot_record_it(self):
        prof, code = self.encrypted_profile()
        box = profiles.container(prof)
        before = box.vault_path.read_bytes()
        unavailable = storage.StorageError("storage-unavailable", "FileNotFoundError")
        with mock.patch.object(storage.Container, "_gocryptfs", side_effect=unavailable):
            for op in ("new-recovery-code", "add-password", "remove-method"):
                with self.subTest(op=op), self.assertRaises(storage.StorageError) as ctx:
                    vault_cli.api_request({"op": op, "path": str(prof.path), "current": PASSWORD, "password": "another one"})
                self.assertEqual(ctx.exception.code, "storage-unavailable")
        self.assertEqual(box.vault_path.read_bytes(), before)  # nothing was signed, nothing was removed
        self.assertEqual([p.name for p in box.root.glob("maintenance-*")], [])
        profiles.unlock(prof, recovery_code=code).lock()
        profiles.lock(prof)

    def test_two_changes_from_the_same_key_file_do_not_both_go_through(self):
        # Each read generation N. The first removes a method and saves N+1; the second, still holding
        # what it read, would save its own N+1 with that method back in it.
        prof, code = self.encrypted_profile()
        box = profiles.container(prof)
        stale = box.load_vault()
        stale.unlock_password(PASSWORD)
        self.addCleanup(stale.lock)
        request = {"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD}
        new_code = vault_cli.api_request(request)["recovery_code"]
        vault_cli.api_request({"op": "confirm-recovery-code", "path": str(prof.path), "current": new_code})
        after = box.vault_path.read_bytes()
        with self.assertRaises(storage.StorageError) as ctx, box.recording(stale) as record:
            stale.add_password("a second password", FAST)
            stale.save()
            record()
        self.assertEqual(ctx.exception.code, "changed")
        self.assertEqual(box.vault_path.read_bytes(), after)
        with self.assertRaises(VaultError):  # the code the first change replaced stays replaced
            profiles.unlock(prof, recovery_code=code)
        self.assertEqual([p.name for p in box.root.glob("maintenance-*")], [])

    def test_the_record_goes_into_the_volume_or_nowhere(self):
        # The volume is mounted for the change alone. Written by path, the record of a volume that
        # had gone away meanwhile landed in the clear beside the key file, and the volume kept the
        # old one. It is written through a handle on the volume instead.
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        before = box.vault_path.read_bytes()
        vault = box.load_vault()
        vault.unlock_password(PASSWORD)
        self.addCleanup(vault.lock)
        with box.recording(vault) as record:
            (mount,) = box.root.glob("maintenance-*")
            self.assertIn(str(mount), storage.mounted_paths())
            self.assertEqual(os.stat(mount).st_mode & 0o077, 0)
            self.assertFalse(box.mounted())  # never at the profile's own path
            with self.assertRaises(subprocess.CalledProcessError):  # held open: an ordinary unmount is refused
                subprocess.run(["fusermount3", "-u", str(mount)], check=True, capture_output=True)
            subprocess.run(["fusermount3", "-u", "-z", str(mount)], check=True, capture_output=True)  # it goes away
            vault.add_password("a second password", FAST)
            vault.save()
            record()
            self.assertEqual(list(mount.iterdir()), [])  # nothing in the clear on the bare directory
        self.assertEqual([p.name for p in box.root.glob("maintenance-*")], [])
        box.vault_path.write_bytes(before)  # the record did reach the volume: the key file from before is refused
        with self.assertRaises(storage.StorageError) as ctx:
            profiles.unlock(prof, password=PASSWORD)
        self.assertEqual(ctx.exception.code, "rollback")

    def test_an_unlocked_profile_that_locks_during_a_change_gets_no_record_in_the_clear(self):
        # The same for a profile that is open: its volume can go (the idle timer, "lock now")
        # between the save and the record.
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        profiles.unlock(prof, password=PASSWORD).lock()
        vault = box.load_vault()
        vault.unlock_password(PASSWORD)
        self.addCleanup(vault.lock)
        with box.recording(vault) as record:
            subprocess.run(["fusermount3", "-u", "-z", str(prof.path)], check=True, capture_output=True)
            vault.add_password("a second password", FAST)
            vault.save()
            record()
            self.assertEqual(list(prof.path.iterdir()), [])  # the bare mount point stays empty
        box.secure_if_locked()
        profiles.unlock(prof, password="a second password").lock()  # and the profile still opens
        self.assertEqual(
            json.loads(box.state_path.read_text())["generation"], json.loads(box.vault_path.read_text())["generation"]
        )
        profiles.lock(prof)

    def test_a_change_that_was_saved_is_reported_even_when_its_record_failed(self):
        # The new recovery code exists only in the answer: it must arrive once the key file is saved.
        prof, old_code = self.encrypted_profile()
        box = profiles.container(prof)
        real, calls = storage.Container._check_state, []

        def check_state(self, vault, volume_fd=None):
            calls.append(volume_fd)
            if len(calls) == 2:  # the record after the save: the volume has gone
                raise OSError(107, "Transport endpoint is not connected")
            return real(self, vault, volume_fd)

        with mock.patch.object(storage.Container, "_check_state", check_state):
            result = vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        self.assertEqual(result["warning"], "not-recorded")
        self.assertEqual([p.name for p in box.root.glob("maintenance-*")], [])
        vault = profiles.unlock(prof, recovery_code=result["recovery_code"])  # unlocking once records it
        self.assertEqual(vault.settled, "finished")  # and, with the new code, finishes the replacement
        vault.lock()
        self.assertEqual(
            json.loads(box.state_path.read_text())["generation"], json.loads(box.vault_path.read_text())["generation"]
        )
        profiles.lock(prof)
        with self.assertRaises(VaultError):
            profiles.unlock(prof, recovery_code=old_code)

    # #187: a replacement cut short at any point leaves a code the person has seen that opens the profile.

    def replace_from_the_command_line(self, prof: profile.Profile, confirm=None) -> tuple[subprocess.Popen, str]:
        """`nulavio vault new-recovery-code`, read up to the new code; `confirm` is typed back if given."""
        proc = subprocess.Popen(
            [str(ROOT / "bin" / "nulavio"), "vault", "new-recovery-code", prof.name, "--password-stdin"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )  # fmt: skip
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        proc.stdin.write(PASSWORD + "\n")
        proc.stdin.flush()
        code = None
        for line in proc.stdout:
            if re.fullmatch(r"\s+([0-9A-Z]{4}-){6}[0-9A-Z]{4}\s*", line):
                code = line.strip()
                break
        self.assertIsNotNone(code, proc.stderr.read() if proc.poll() is not None else "no code shown")
        if confirm is not None:
            proc.stdin.write(confirm(code) + "\n")
            proc.stdin.close()
            proc.wait(120)
        return proc, code

    def test_the_command_line_drops_the_old_code_once_the_new_one_is_typed_back(self):
        prof, old_code = self.encrypted_profile()
        proc, new_code = self.replace_from_the_command_line(prof, confirm=lambda code: code.lower())
        self.assertEqual(proc.returncode, 0, proc.stderr.read())
        with self.assertRaises(VaultError):
            profiles.unlock(prof, recovery_code=old_code)
        vault = profiles.unlock(prof, recovery_code=new_code)
        self.assertIsNone(vault.settled)  # nothing was left to settle
        vault.lock()
        profiles.lock(prof)

    def test_a_replacement_not_confirmed_on_the_command_line_keeps_the_old_code(self):
        prof, old_code = self.encrypted_profile()
        proc, new_code = self.replace_from_the_command_line(prof, confirm=lambda _code: old_code)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("was not confirmed", proc.stderr.read())
        self.assertEqual(sum(m.get("unconfirmed", False) for m in profiles.status(prof)["methods"]), 1)
        vault = profiles.unlock(prof, recovery_code=old_code)
        self.assertEqual(vault.settled, "undone")
        vault.lock()
        profiles.lock(prof)
        with self.assertRaises(VaultError):
            profiles.unlock(prof, recovery_code=new_code)

    def test_a_replacement_killed_after_its_code_was_shown_is_settled_by_the_next_unlock(self):
        # Killed while it waits for the new code to be typed back (a closed terminal, a power cut):
        # both codes were shown. The next unlock finishes the replacement if it used the new code,
        # and undoes it otherwise.
        for unlock_with, outcome in (("new code", "finished"), ("password", "undone")):
            with self.subTest(unlock_with=unlock_with):
                prof, old_code = self.encrypted_profile(f"killed-{outcome}")
                proc, new_code = self.replace_from_the_command_line(prof)
                proc.kill()
                proc.wait(30)
                box = profiles.container(prof)
                self.assertFalse(box.mounted())
                if unlock_with == "password":
                    vault = profiles.unlock(prof, password=PASSWORD)
                else:
                    vault = profiles.unlock(prof, recovery_code=new_code)
                self.assertEqual(vault.settled, outcome)
                vault.lock()
                profiles.lock(prof)
                works, refused = (new_code, old_code) if outcome == "finished" else (old_code, new_code)
                with self.assertRaises(VaultError):
                    profiles.unlock(prof, recovery_code=refused)
                profiles.unlock(prof, recovery_code=works).lock()
                profiles.lock(prof)
                self.assertNotIn("pending_recovery", json.loads(box.vault_path.read_text()))

    def test_a_replacement_killed_before_its_code_was_shown_leaves_the_old_code(self):
        # Killed once the key file is saved and before the answer leaves (the issue's window of about
        # a second): the new code was never seen. Nothing after the save runs, as in a kill.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        self.assertIsNotNone(json.loads(profiles.container(prof).vault_path.read_text()).get("pending_recovery"))
        vault = profiles.unlock(prof, recovery_code=old_code)
        self.assertEqual(vault.settled, "undone")
        vault.lock()
        profiles.lock(prof)
        status = profiles.status(prof)
        self.assertEqual([m["method"] for m in status["methods"]], ["password", "recovery-code"])
        profiles.unlock(prof, recovery_code=old_code).lock()
        profiles.lock(prof)

    def test_the_code_being_replaced_cannot_be_removed_while_the_new_answer_was_lost(self):
        # Review of #187: a recovery-only profile, its replacement killed before the answer left. Removing
        # the old code with the old code then left only the new one, which nobody had seen.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        old_id = next(
            m["id"] for m in profiles.status(prof)["methods"] if m["method"] == "recovery-code" and not m.get("unconfirmed")
        )
        password_id = next(m["id"] for m in profiles.status(prof)["methods"] if m["method"] == "password")
        vault_cli.api_request({"op": "remove-method", "path": str(prof.path), "current": old_code, "envelope": password_id})
        with self.assertRaises(VaultError) as ctx:
            vault_cli.api_request({"op": "remove-method", "path": str(prof.path), "current": old_code, "envelope": old_id})
        self.assertEqual(ctx.exception.code, "replacement-pending")
        vault = profiles.unlock(prof, recovery_code=old_code)  # the code that was seen still opens it
        self.assertEqual(vault.settled, "undone")
        vault.lock()
        profiles.lock(prof)

    def test_a_first_recovery_code_is_confirmed_through_the_helper(self):
        # Review of #187: with no recovery code left to replace, confirming the new one answered "not-found".
        prof, _code = self.encrypted_profile()
        code_id = next(m["id"] for m in profiles.status(prof)["methods"] if m["method"] == "recovery-code")
        vault_cli.api_request({"op": "remove-method", "path": str(prof.path), "current": PASSWORD, "envelope": code_id})
        new = vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})["recovery_code"]
        self.assertFalse(any(m.get("unconfirmed") for m in profiles.status(prof)["methods"]))
        self.assertEqual(
            vault_cli.api_request({"op": "confirm-recovery-code", "path": str(prof.path), "current": new}), {"done": True}
        )
        profiles.unlock(prof, recovery_code=new).lock()
        profiles.lock(prof)

    def test_a_settled_replacement_is_recorded_in_the_volume_or_nowhere(self):
        # Review of #187: the settlement at unlock recorded by path; a volume gone between its save and its
        # record got the record in the clear on the bare mount point, and the next unlock was refused.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        box = profiles.container(prof)
        real_save = Vault.save

        def save_then_detach(vault, *args, **kwargs):
            real_save(vault, *args, **kwargs)
            if vault.settled is None and box.mounted():  # the settlement's save: the volume goes away now
                subprocess.run(["fusermount3", "-u", "-z", str(prof.path)], check=True, capture_output=True)

        with mock.patch.object(Vault, "save", save_then_detach):
            vault = profiles.unlock(prof, recovery_code=old_code)
        self.assertEqual(vault.settled, "undone")
        vault.lock()
        box.secure_if_locked()
        self.assertEqual([p.name for p in prof.path.iterdir()], [])  # nothing written in the clear
        profiles.unlock(prof, recovery_code=old_code).lock()  # and it opens, its record and key file agreeing
        self.assertEqual(
            json.loads(box.state_path.read_text())["generation"], json.loads(box.vault_path.read_text())["generation"]
        )
        profiles.lock(prof)

    def test_a_settlement_that_cannot_be_saved_says_so_and_is_tried_again(self):
        # Review of #187, round 2: a full disk at the settlement left both codes working and said nothing.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        full = mock.patch.object(Vault, "save", side_effect=OSError(28, "No space left on device"))
        request = {"op": "unlock", "path": str(prof.path), "method": "recovery-code", "secret": old_code, "autolock": False}
        with full:
            self.assertEqual(vault_cli.api_request(request), {"unlocked": True, "recovery_code": "unsettled"})
        self.assertIsNotNone(json.loads(profiles.container(prof).vault_path.read_text()).get("pending_recovery"))
        profiles.lock(prof)
        self.assertEqual(vault_cli.api_request(request), {"unlocked": True, "recovery_code": "undone"})  # next time
        profiles.lock(prof)

    def test_a_settlement_whose_save_failed_after_writing_says_what_is_on_disk(self):
        # Review of #187, round 3: the save replaced the key file and then failed (syncing its directory); the
        # unlock said "both codes still work" while the old one no longer did.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        real = Vault.save

        def written_then_failed(vault, *args, **kwargs):
            real(vault, *args, **kwargs)
            raise OSError(5, "Input/output error")

        request = {"op": "unlock", "path": str(prof.path), "method": "recovery-code", "secret": old_code, "autolock": False}
        with mock.patch.object(Vault, "save", written_then_failed):
            self.assertEqual(vault_cli.api_request(request), {"unlocked": True, "recovery_code": "undone"})
        self.assertIsNone(json.loads(profiles.container(prof).vault_path.read_text()).get("pending_recovery"))
        profiles.lock(prof)

    def test_a_settlement_that_cannot_be_read_back_says_it_is_not_known(self):
        # Verification of round 3: the save failed after writing and the key file could not be read back either.
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        real_save, real_read = Vault.save, Path.read_text
        state = {"saved": False}

        def written_then_failed(vault, *args, **kwargs):
            real_save(vault, *args, **kwargs)
            state["saved"] = True
            raise OSError(5, "Input/output error")

        def unreadable_after(path, *args, **kwargs):
            if state["saved"] and path.name == "vault.json":
                raise OSError(5, "Input/output error")
            return real_read(path, *args, **kwargs)

        request = {"op": "unlock", "path": str(prof.path), "method": "recovery-code", "secret": old_code, "autolock": False}
        with mock.patch.object(Vault, "save", written_then_failed), mock.patch.object(Path, "read_text", unreadable_after):
            self.assertEqual(vault_cli.api_request(request), {"unlocked": True, "recovery_code": "unknown"})
        profiles.lock(prof)

    def test_a_settlement_saved_but_not_recorded_says_so(self):
        prof, old_code = self.encrypted_profile()
        killed = mock.patch.object(vault_cli, "_record", side_effect=SystemExit("killed"))
        with killed, self.assertRaises(SystemExit):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        real = storage.Container._check_state

        def check_state(self, vault, volume_fd=None):
            if vault.settled is not None:  # the settlement's record, after its save: the volume is gone
                raise OSError(107, "Transport endpoint is not connected")
            return real(self, vault, volume_fd)

        request = {"op": "unlock", "path": str(prof.path), "method": "recovery-code", "secret": old_code, "autolock": False}
        with mock.patch.object(storage.Container, "_check_state", check_state):
            answer = vault_cli.api_request(request)
        self.assertEqual(answer, {"unlocked": True, "recovery_code": "undone", "warning": "not-recorded"})
        profiles.lock(prof)

    def test_the_command_line_confirms_only_the_code_it_showed(self):
        # Review of #187, round 2: while the command waited, another unlock undid the replacement; typing the
        # old code then "confirmed" it and said the old code no longer opened the profile.
        prof, old_code = self.encrypted_profile()

        def typed_back(code):
            vault = profiles.unlock(prof, password=PASSWORD)  # meanwhile: the replacement is undone
            self.assertEqual(vault.settled, "undone")
            vault.lock()
            profiles.lock(prof)
            return old_code

        proc, _new_code = self.replace_from_the_command_line(prof, confirm=typed_back)
        self.assertEqual(proc.returncode, 1)
        out = proc.stdout.read()
        self.assertNotIn("no longer opens", out)
        self.assertIn("was not confirmed", proc.stderr.read())
        profiles.unlock(prof, recovery_code=old_code).lock()  # the old code still opens it, as it was said
        profiles.lock(prof)

    def test_a_failure_before_the_change_is_not_called_saved(self):
        # "Saved, but not recorded" was also the answer when the check before the change failed
        # (a full disk): nothing had been saved, and the old code still opened the profile.
        prof, old_code = self.encrypted_profile()
        box = profiles.container(prof)
        before = box.vault_path.read_bytes()
        full = OSError(28, "No space left on device")
        with (
            mock.patch.object(storage.Container, "_check_state", side_effect=full),
            self.assertRaises(storage.StorageError) as ctx,
        ):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        self.assertEqual(ctx.exception.code, "storage-failed")
        self.assertEqual(box.vault_path.read_bytes(), before)
        profiles.unlock(prof, recovery_code=old_code).lock()
        profiles.lock(prof)

    def test_an_unlock_that_waited_for_a_change_is_told_the_key_file_changed(self):
        # Checked against what it had read before the change, it was refused as a rollback
        # ("restored from a backup?").
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        waiting = box.load_vault()
        waiting.unlock_password(PASSWORD)
        self.addCleanup(waiting.lock)
        vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        with self.assertRaises(storage.StorageError) as ctx:
            box.mount(waiting)
        self.assertEqual(ctx.exception.code, "changed")
        self.assertFalse(box.mounted())
        profiles.unlock(prof, password=PASSWORD).lock()  # read again, it opens
        profiles.lock(prof)

    def test_a_profile_whose_generation_cannot_be_checked_does_not_stay_open(self):
        # The lock file is beside the key file, where whoever puts an old key file back can write.
        prof, old_code = self.encrypted_profile()
        box = profiles.container(prof)
        before = box.vault_path.read_bytes()
        vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        for path in (box.vault_path, box.vault_path.with_suffix(".json.bak")):
            path.write_bytes(before)
        (box.root / "state.lock").unlink()
        (box.root / "state.lock").mkdir()
        with self.assertRaises(storage.StorageError) as ctx:
            profiles.unlock(prof, recovery_code=old_code)
        self.assertEqual(ctx.exception.code, "storage-failed")
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(prof.path).st_mode & 0o777, 0o500)
        (box.root / "state.lock").rmdir()
        # A record that cannot be read is no reason to stay open either.
        damaged = mock.patch.object(storage.Container, "_check_state", side_effect=ValueError("damaged"))
        with damaged, self.assertRaises(storage.StorageError) as ctx:
            profiles.unlock(prof, recovery_code=old_code)
        self.assertEqual(ctx.exception.code, "storage-failed")
        self.assertFalse(box.mounted())

    def test_one_change_at_a_time_and_nothing_left_mounted_by_a_killed_one(self):
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        with box._state_lock():
            with self.assertRaises(storage.StorageError) as ctx, box._state_lock(wait=0.3):
                self.fail("two holders")
            self.assertEqual(ctx.exception.code, "busy")
            # What a killed change left behind: the volume mounted at a maintenance directory.
            left = box.root / "maintenance-left"
            left.mkdir(mode=0o700)
            vault = box.load_vault()
            vault.unlock_password(PASSWORD)
            self.addCleanup(vault.lock)
            box._gocryptfs(["-q", "-nosyslog", str(box.cipher), str(left)], storage.storage_password(vault))
            profiles.container(prof)  # a change is running (the lock is held): it is left alone
            self.assertIn(str(left), storage.mounted_paths())
        profiles.container(prof)  # every use of the profile comes here: now it is cleared
        self.assertNotIn(str(left), storage.mounted_paths())
        self.assertFalse(left.exists())

    def test_every_question_is_asked_before_the_volume_is_mounted(self):
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        asked = []

        def read_secret(prompt, **_kwargs):
            asked.append((prompt.split()[0], [p.name for p in box.root.glob("maintenance-*")]))
            return PASSWORD if prompt.startswith("Current") else "a second password"

        args = mock.Mock(vault_cmd="add-password", password_stdin=False, path=str(prof.path))
        with mock.patch.object(vault_cli, "read_secret", read_secret), mock.patch("builtins.print"):
            self.assertEqual(vault_cli._change(args), 0)
        self.assertEqual(asked, [("Current", []), ("New", [])])
        profiles.unlock(prof, password="a second password").lock()
        profiles.lock(prof)

    def test_a_method_changed_while_unlocked_is_recorded_through_the_profiles_own_mount(self):
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        profiles.unlock(prof, password=PASSWORD).lock()
        before = box.vault_path.read_bytes()
        with mock.patch.object(storage.tempfile, "mkdtemp", side_effect=AssertionError("a second mount")):
            vault_cli.api_request({"op": "new-recovery-code", "path": str(prof.path), "current": PASSWORD})
        state = json.loads(box.state_path.read_text())
        self.assertEqual(state["generation"], json.loads(box.vault_path.read_text())["generation"])
        self.assertTrue(box.mounted())  # still unlocked: the change does not lock it
        profiles.lock(prof)
        box.vault_path.write_bytes(before)
        with self.assertRaises(storage.StorageError) as ctx:
            profiles.unlock(prof, password=PASSWORD)
        self.assertEqual(ctx.exception.code, "rollback")

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
