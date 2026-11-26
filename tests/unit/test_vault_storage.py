"""Encrypted profile storage (S5): gocryptfs containers, encrypted launcher profiles, supervised runs.

Real FUSE mounts in a temporary NULAVIO_HOME, artificial passwords. `nulavio run`
is exercised with a stand-in engine (a shell script that writes into the
profile and holds the engine lock) so the test can see the volume mounted
while "the engine" runs and locked after it exits; the real engine on an
encrypted profile is in tests/integration/test_vault_profiles.py.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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
from nulavio_launcher.vault import core, profiles  # noqa: E402
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

    def test_a_volume_gone_without_a_lock_leaves_a_read_only_folder(self):
        """The bare mount point is read-only underneath the open volume: a volume that goes away without Nulavio's
        lock (a crash, a reboot, a killed gocryptfs, its -idle timer) leaves a folder no engine can write to, before
        any launcher call has looked at the profile again."""
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "inside.txt").write_text(MARKER)
        subprocess.run(["fusermount3", "-u", str(box.mountpoint)], check=True, capture_output=True)  # not box.unmount()
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)
        with self.assertRaises(PermissionError):
            (box.mountpoint / "prefs.js").write_text("plaintext")
        # The volume's own root keeps its mode: unlocked again, the profile takes writes as before.
        self.assertEqual(os.stat(box.cipher).st_mode & 0o777, 0o700)
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("inside")
        self.assertEqual((box.mountpoint / "inside.txt").read_text(), MARKER)
        box.unmount()
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)

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

    def test_a_backup_of_the_whole_folder_restored_whole_opens_as_it_was(self):
        # vault-and-unlock.md, "Backing up a protected profile" (#413): the .vault folder copied with the
        # profile locked, then put back whole over a profile that went on changing, opens with the
        # secrets of then and holds the files of then. Nothing outside the folder says it is older.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("then")
        box.record_generation(vault)
        box.unmount()
        backup = self.tmp / "backup.vault"
        shutil.copytree(box.root, backup, symlinks=True)
        later = Vault.load(box.vault_path)
        later.unlock_password(PASSWORD)
        box.mount(later)
        code = later.add_recovery_code(FAST)
        later.save()
        box.record_generation(later)  # a later generation, in the key file and in the volume
        (box.mountpoint / "prefs.js").write_text("later")
        box.unmount()
        shutil.rmtree(box.root)
        shutil.copytree(backup, box.root, symlinks=True)
        restored = Vault.load(box.vault_path)
        with self.assertRaises(VaultError):
            restored.unlock_recovery_code(code)  # the backup was made before this code existed
        restored.unlock_password(PASSWORD)
        box.mount(restored)
        self.assertEqual((box.mountpoint / "prefs.js").read_text(), "then")
        box.unmount()

    def test_a_key_file_is_refused_when_its_record_is_missing(self):
        # U-T21: a password removed, then the key file from before put back and the record in the volume
        # removed (writing the volume's files needs no key). Refused, as a rollback is.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("user_pref('x', 1);")  # a profile in use
        bob = vault.add_password("bob's password", FAST)
        vault.save()
        box.record_generation(vault)
        before = box.vault_path.read_bytes()  # Bob's password still in it
        self.assertIs(json.loads(before)["recorded"], True)
        vault.remove(bob.id)
        vault.save()
        box.record_generation(vault)
        (box.mountpoint / storage.STATE_DIR / "state.json").unlink()
        box.unmount()
        for path in (box.vault_path, box.vault_path.with_suffix(".json.bak")):
            path.write_bytes(before)
        restored = Vault.load(box.vault_path)
        restored.unlock_password("bob's password")
        with self.assertRaises(storage.StorageError) as ctx:
            storage.Container(box.mountpoint).mount(restored)
        self.assertEqual(ctx.exception.code, "record-missing")
        self.assertIn("record-missing", vault_cli.MESSAGES)
        for lang in ("en", "pt_BR"):  # the pages look the code up with "-" as "_" (browser/shell/lib/ui.js errorText)
            messages = json.loads((ROOT / "browser" / "shell" / "_locales" / lang / "messages.json").read_text(encoding="utf-8"))
            self.assertIn("err_record_missing", messages, lang)
        self.assertFalse(box.mounted())

    def test_a_refused_unlock_writes_nothing_into_the_volume(self):
        # #412: the record's directory was made before the record was read, so a mount refused for a
        # missing record left an empty directory in a volume it was about to refuse.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("user_pref('x', 1);")
        box.record_generation(vault)
        shutil.rmtree(box.mountpoint / storage.STATE_DIR)  # the record and its directory are gone
        box.unmount()

        def listing() -> list[tuple[str, int]]:
            return sorted((str(path.relative_to(box.cipher)), path.stat().st_size) for path in box.cipher.rglob("*"))

        before = listing()
        again = Vault.load(box.vault_path)
        again.unlock_password(PASSWORD)
        for _ in range(2):  # the refusal holds at the next try, and that try writes nothing either
            with self.assertRaises(storage.StorageError) as ctx:
                storage.Container(box.mountpoint).mount(again)
            self.assertEqual(ctx.exception.code, "record-missing")
            self.assertFalse(box.mounted())
            self.assertEqual(listing(), before)

    def test_the_first_mount_of_a_new_volume_still_makes_its_record(self):
        box, vault = self.new_container()  # init() makes the volume; nothing is mounted yet
        box.mount(vault)
        self.assertEqual(json.loads(box.state_path.read_text())["generation"], int(vault.meta["generation"]))
        self.assertEqual(os.stat(box.mountpoint / storage.STATE_DIR).st_mode & 0o777, 0o700)
        box.unmount()

    def test_a_key_file_saved_before_the_record_was_required_still_opens(self):
        # Key files saved by 160.0-0.5 and earlier have no `recorded`: their volumes stay usable, and
        # their next save adds it.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / storage.STATE_DIR / "state.json").unlink()
        box.unmount()
        del vault.meta["recorded"]
        vault.meta["mac"] = core.b64e(vault._mac())
        box.vault_path.write_text(json.dumps(vault.meta))
        old = Vault.load(box.vault_path)
        old.unlock_password(PASSWORD)
        self.assertFalse(old.tampered)
        again = storage.Container(box.mountpoint)
        again.mount(old)
        old.save()
        again.record_generation(old)
        again.unmount()
        self.assertIs(json.loads(box.vault_path.read_text())["recorded"], True)

    def test_only_the_first_mount_of_a_new_volume_has_no_record_to_read(self):
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / storage.STATE_DIR / "state.json").unlink()
        box.unmount()
        with self.assertRaises(storage.StorageError) as ctx:
            box.mount(vault)  # the same object, a second time
        self.assertEqual(ctx.exception.code, "record-missing")

    def test_hiding_the_encrypted_files_does_not_make_the_volume_new(self):
        # Delta review: gocryptfs leaves out of a listing the names it cannot decrypt, so whoever can write the
        # encrypted files can make a used volume look empty. That is not a volume just made: still refused.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("user_pref('x', 1);")
        box.unmount()
        aside = self.tmp / "aside"
        aside.mkdir()
        for entry in box.cipher.iterdir():
            if entry.name not in ("gocryptfs.conf", "gocryptfs.diriv"):
                entry.rename(aside / entry.name)
        with self.assertRaises(storage.StorageError) as ctx:
            storage.Container(box.mountpoint).mount(vault)
        self.assertEqual(ctx.exception.code, "record-missing")
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
        storage.encrypt_existing(plain, vault)  # saves the key file itself (#411)
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
        with mock.patch.object(storage.shutil, "copy2", side_effect=OSError("disk full")), self.assertRaises(OSError):
            storage.encrypt_existing(plain, vault)
        self.assertEqual((plain / "places.sqlite").read_text(), "data")
        self.assertFalse(box.root.exists())
        self.assertEqual(storage.mounted_paths() & {str(plain)}, set())


def mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


class OverlappingUnlockTest(StorageCase):
    """Two unlocks of one profile at once (#620): two unlock tabs, the chooser and a tab, a phone approval during a
    password unlock, `nulavio vault unlock` beside the browser. gocryptfs keeps the mode of the volume's root as the
    mode of P.vault/cipher, so a chmod of the profile's folder by its path while the volume is mounted there makes
    the encrypted folder read-only, and every later unlock opens a profile the engine cannot write to."""

    def hold_at_the_lock(self, callers: int = 2) -> None:
        """The first `callers` calls to the state lock wait for each other: all have passed the checks made before
        it, as when the requests come at the same moment. Later calls go straight through."""
        gate = threading.Barrier(callers, timeout=20)
        count = []
        guard = threading.Lock()
        real = storage.Container._state_lock

        def held(box, *args, **kwargs):
            with guard:
                count.append(1)
                first = len(count) <= callers
            if first:
                gate.wait()
            return real(box, *args, **kwargs)

        patcher = mock.patch.object(storage.Container, "_state_lock", held)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_unlocks_at_once_both_open_the_profile_and_leave_it_writable(self):
        prof, _code = self.encrypted_profile()
        box = profiles.container(prof)
        self.hold_at_the_lock()
        opened, failed = [], []

        def unlock() -> None:
            try:
                opened.append(profiles.unlock(prof, password=PASSWORD))
            except BaseException as exc:  # reported by the assertion below
                failed.append(f"{getattr(exc, 'code', type(exc).__name__)}: {exc}")

        threads = [threading.Thread(target=unlock, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        for vault in opened:
            self.addCleanup(vault.lock)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failed, [])  # the one that did not mount says the profile is open, which it is
        self.assertEqual(len(opened), 2)
        self.assertTrue(all(vault.unlocked for vault in opened))
        self.assertTrue(box.mounted())
        self.assertEqual(mode(box.cipher), 0o700)
        (prof.path / "prefs.js").write_text("inside")
        profiles.lock(prof)
        self.assertEqual(mode(box.cipher), 0o700)
        self.assertEqual(mode(prof.path), 0o500)
        profiles.unlock(prof, password=PASSWORD).lock()
        self.assertEqual((prof.path / "prefs.js").read_text(), "inside")
        (prof.path / "prefs.js").write_text("again")  # the profile's own folder still takes writes
        profiles.lock(prof)

    def test_a_volume_mounted_after_the_first_check_is_not_taken_for_plaintext(self):
        # The other request mounted the volume between this one's check for a mounted volume and its check for
        # files in the folder: those are the volume's own files, not plaintext in a locked profile.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("inside")
        second = box.load_vault()
        second.unlock_password(PASSWORD)
        self.addCleanup(second.lock)
        real = storage.Container.mounted
        asked = []

        def mounted(box) -> bool:
            asked.append(1)
            return False if len(asked) == 1 else real(box)

        with mock.patch.object(storage.Container, "mounted", mounted):
            box.mount(second)
        self.assertTrue(box.mounted())
        self.assertEqual(mode(box.cipher), 0o700)
        self.assertEqual((box.mountpoint / "prefs.js").read_text(), "inside")
        box.unmount()

    def test_an_unlock_restores_an_encrypted_folder_left_read_only(self):
        # What the overlapping unlocks of earlier versions left behind: P.vault/cipher at 0500.
        box, vault = self.new_container()
        box.mount(vault)
        (box.mountpoint / "prefs.js").write_text("inside")
        box.unmount()
        os.chmod(box.cipher, 0o500)
        box.mount(vault)
        self.assertEqual(mode(box.cipher), 0o700)
        (box.mountpoint / "lock").write_text("engine")
        box.unmount()
        self.assertEqual(mode(box.mountpoint), 0o500)

    def test_securing_a_locked_folder_never_reaches_a_volume_mounted_meanwhile(self):
        box, vault = self.new_container()
        box.mount(vault)
        with mock.patch.object(storage.Container, "mounted", return_value=False):  # mounted right after the check
            box.secure_if_locked()
        self.assertEqual(mode(box.cipher), 0o700)
        (box.mountpoint / "prefs.js").write_text("inside")
        box.unmount()
        self.assertEqual(mode(box.mountpoint), 0o500)

    def test_the_end_of_a_lock_never_reaches_a_volume_mounted_meanwhile(self):
        box, vault = self.new_container()
        box.mount(vault)
        with mock.patch.object(storage.Container, "mounted", return_value=False):  # mounted again after the unmount
            box.unmount()
        self.assertTrue(box.mounted())
        self.assertEqual(mode(box.cipher), 0o700)
        (box.mountpoint / "prefs.js").write_text("inside")
        box.unmount()
        self.assertEqual(mode(box.mountpoint), 0o500)


INTERRUPTED_MIGRATION = """
import os, shutil, signal, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nulavio_launcher.vault import storage
from nulavio_launcher.vault.core import Vault
path, how, password = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
vault = Vault.create(storage.Container(path).vault_path)
vault.add_password(password, {"ops": 1, "mem": 8 * 1024 * 1024})
copied = []
real_copy, real_rmtree, real_rename, real_init = shutil.copy2, shutil.rmtree, os.rename, storage.Container.init
def rename(source, target, *args, **kwargs):
    if how == "kill-before-rename" and str(target).endswith(".plaintext-migrating"):
        os.kill(os.getpid(), signal.SIGKILL)
    return real_rename(source, target, *args, **kwargs)
def init(self, vault):
    if how == "kill-before-volume":  # the key file is saved, the volume is not made yet (#411)
        os.kill(os.getpid(), signal.SIGKILL)
    return real_init(self, vault)
os.rename, storage.Container.init = rename, init
if len(sys.argv) > 5:  # two runs at once: say "ready", then wait for the parent's word
    import time
    go = Path(sys.argv[5])
    go.with_name(f"{go.name}.{os.getpid()}").write_text("")
    while not go.exists():
        time.sleep(0.01)
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

    def test_a_stop_between_the_key_file_and_the_volume_is_undone_the_next_time(self):
        # #411: the key file was saved before the migration began, so a stop here left a key file with no
        # volume: a profile that said it was protected, could not be opened, and had its files in the clear.
        path = self.plain_profile()
        self.assertEqual(self.interrupt(path, "kill-before-volume").returncode, -signal.SIGKILL)
        box = storage.Container(path)
        self.assertTrue(box.vault_path.exists())  # the state the stop leaves: a key file,
        self.assertFalse(box.cipher.exists())  # no volume,
        self.assertTrue(self.staging(path).exists())  # and the files in staging, which is what makes it recoverable
        prof = profile.Profile(name="work", path=path)
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertFalse(profiles.is_encrypted(prof))
        self.assertIn("back as it was, not protected", said.getvalue())
        self.assertFalse(box.root.exists())  # the key file is gone with it
        self.assertFalse(self.staging(path).exists())
        self.assertEqual(sorted(p.name for p in path.iterdir()), [f"file{i}.txt" for i in range(10)])
        self.assertTrue(os.access(path, os.W_OK))
        again = self.interrupt(path, "none")  # and it can be protected again
        self.assertEqual(again.returncode, 0, again.stderr)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(profiles.is_encrypted(prof))

    def test_the_move_into_staging_is_on_disk_before_the_key_file_is_written(self):
        # A power cut must not keep the key file and lose the rename (the state #411 rules out).
        path = self.plain_profile()
        box = storage.Container(path)
        vault = Vault.create(box.vault_path)
        vault.add_password(PASSWORD, FAST)
        order: list[str] = []
        real_fsync_dir, real_save = storage._fsync_dir, Vault.save

        def fsync_dir(target):
            order.append(f"fsync {Path(target).name}")
            return real_fsync_dir(target)

        def save(self, **kwargs):
            order.append("save" if self.path == box.vault_path else "other save")
            return real_save(self, **kwargs)

        with mock.patch.object(storage, "_fsync_dir", fsync_dir), mock.patch.object(Vault, "save", save):
            storage.encrypt_existing(path, vault)
        self.assertIn("save", order)
        self.assertEqual(order[: order.index("save")], [f"fsync {path.parent.name}"])
        vault.lock()

    def test_two_runs_at_once_protect_the_profile_once(self):
        # Both runs pass every check made before the lock. The one that waits for the lock must then
        # find the other's key file and stop: it used to write its own key file over it and, when making
        # the volume failed, remove the folder with the only copy of the profile's files.
        path = self.plain_profile()
        script = self.tmp / "migrate.py"
        script.write_text(INTERRUPTED_MIGRATION)
        go = self.tmp / "go"
        args = [sys.executable, str(script), str(ROOT / "launcher"), str(path), "none", PASSWORD, str(go)]
        runs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            wait_for(lambda: len(list(self.tmp.glob("go.*"))) == 2)  # both have their new vault in hand
            go.write_text("")
            errors = [run.communicate(timeout=120)[1] for run in runs]
        finally:
            for run in runs:
                if run.poll() is None:
                    run.kill()
        codes = [run.returncode for run in runs]
        self.assertEqual(sorted(code != 0 for code in codes), [False, True], errors)
        self.assertIn("exists", errors[codes.index(next(code for code in codes if code != 0))])
        box = storage.Container(path)
        self.assertTrue(box.exists())
        self.assertFalse(self.staging(path).exists())
        vault = Vault.load(box.vault_path)
        vault.unlock_password(PASSWORD)
        box.mount(vault)  # the key file on disk is the one the volume was made with
        self.assertEqual(
            sorted(p.name for p in path.iterdir() if p.name != storage.STATE_DIR), [f"file{i}.txt" for i in range(10)]
        )
        box.unmount()
        vault.lock()

    def test_a_stop_before_the_files_are_moved_leaves_no_key_file(self):
        path = self.plain_profile()
        self.assertEqual(self.interrupt(path, "kill-before-rename").returncode, -signal.SIGKILL)
        box = storage.Container(path)
        self.assertFalse(box.vault_path.exists())
        self.assertFalse(self.staging(path).exists())
        prof = profile.Profile(name="work", path=path)
        self.assertFalse(profiles.is_encrypted(prof))
        self.assertEqual(sorted(p.name for p in path.iterdir()), [f"file{i}.txt" for i in range(10)])

    def test_a_key_file_already_there_is_not_replaced(self):
        path = self.plain_profile()
        box = storage.Container(path)
        other = Vault.create(box.vault_path)
        other.add_password(PASSWORD, FAST)
        other.save()
        before = box.vault_path.read_bytes()
        vault = Vault.create(self.tmp / "elsewhere" / "vault.json")
        vault.add_password(PASSWORD, FAST)
        with self.assertRaises(storage.StorageError) as ctx:
            storage.encrypt_existing(path, vault)
        self.assertEqual(ctx.exception.code, "exists")
        self.assertEqual(box.vault_path.read_bytes(), before)
        self.assertEqual(len(list(path.iterdir())), 10)  # nothing was moved

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


INTERRUPTED_REKEY = """
import os, signal, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from nulavio_launcher import profile
from nulavio_launcher.vault import profiles, storage
path, how, password = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
stop = lambda: os.kill(os.getpid(), signal.SIGTERM if how.startswith("term") else signal.SIGKILL)
real_copy, real_finish, real_rename, real_replace = storage._copy_checked, storage._rekey_finish, os.rename, os.replace
calls = {"rename": 0, "replace": 0}
def copy(source, target):
    real_copy(source, target)
    if how in ("kill-mid-copy", "term-mid-copy"):
        stop()
def finish(box):
    if how == "kill-before-switch":
        stop()
    real_finish(box)
def rename(a, b, *args, **kwargs):
    real_rename(a, b, *args, **kwargs)
    if str(b).endswith(("cipher.old", "cipher")):
        calls["rename"] += 1
        if how == f"kill-after-rename-{calls['rename']}":
            stop()
def replace(a, b, *args, **kwargs):
    real_replace(a, b, *args, **kwargs)
    if "rekey" in str(a) and "rekey" not in str(b):  # into place, not the new key file's own save
        calls["replace"] += 1
        if how == f"kill-after-key-file-{calls['replace']}":
            stop()
storage._copy_checked, storage._rekey_finish = copy, finish
storage.os.rename, storage.os.replace = rename, replace
profiles.rekey(profile.Profile(name=path.name, path=path), current=password)
"""


class MemoryKeyring:
    """The system keyring, in memory: what the launcher's Keyring gives, without a program to run."""

    def __init__(self):
        self.items: dict[tuple, bytes] = {}

    def available(self) -> bool:
        return True

    def store(self, label: str, attributes: dict[str, str], value) -> None:
        self.items[tuple(sorted(attributes.items()))] = bytes(value)

    def lookup(self, attributes: dict[str, str]) -> bytearray | None:
        found = self.items.get(tuple(sorted(attributes.items())))
        return None if found is None else bytearray(found)

    def clear(self, attributes: dict[str, str]) -> None:
        self.items.pop(tuple(sorted(attributes.items())), None)


class MigrationLockTest(unittest.TestCase):
    """#434: the lock between two protections of one profile is on a file that is removed when it is released.

    Three runs: one holds the lock, one waits for it, one starts when the first ends. The one that waited got
    its lock on the removed file, and the one that started made the file anew and locked that: both went on.
    That is harmless when the first run succeeded (both see its key file and stop), and not when it failed and
    was undone: then both protect the profile at once, which is what the lock is there to rule out (#433).
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-lock-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "work"
        self.name = self.tmp / "work.migrating.lock"

    def holds_the_named_file(self, fd: int) -> bool:
        try:
            named = os.stat(self.name)
        except FileNotFoundError:
            return False
        held = os.fstat(fd)
        return (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)

    def test_a_run_that_waited_and_a_run_that_starts_then_never_both_hold_the_lock(self):
        first = storage._migration_lock(self.path, wait=True)
        self.assertTrue(self.holds_the_named_file(first))
        got: list[int | None] = []
        asked: list[int] = []
        waiting = threading.Event()
        real = storage.fcntl.flock

        def flock(fd, how):
            if threading.current_thread() is second:
                asked.append(fd)
                waiting.set()  # its file is open: from here on it waits on the file the first run holds
            return real(fd, how)

        second = threading.Thread(target=lambda: got.append(storage._migration_lock(self.path, wait=True)))
        with mock.patch.object(storage.fcntl, "flock", flock):
            second.start()
            self.assertTrue(waiting.wait(10))
            storage._release(self.path, first)  # the first run ends: its lock file is removed, then let go
            second.join(10)
            self.assertFalse(second.is_alive())
        self.assertTrue(self.holds_the_named_file(got[0]), "the run that waited holds a file the name does not point to")
        # A third run, starting now, finds the lock taken (as recover_interrupted asks: without waiting).
        self.assertIsNone(storage._migration_lock(self.path, wait=False))
        # And the run that waited really waited on the first run's file, then asked for the new one: otherwise
        # this test would pass without having met the case.
        self.assertEqual(len(asked), 2)
        storage._release(self.path, got[0])
        self.assertFalse(self.name.exists())
        third = storage._migration_lock(self.path, wait=False)
        self.assertIsNotNone(third)
        self.assertTrue(self.holds_the_named_file(third))
        storage._release(self.path, third)
        self.assertFalse(self.name.exists())

    def test_a_lock_that_is_refused_leaves_the_holders_file_alone(self):
        first = storage._migration_lock(self.path, wait=True)
        self.assertIsNone(storage._migration_lock(self.path, wait=False))
        self.assertTrue(self.holds_the_named_file(first))
        storage._release(self.path, first)
        self.assertFalse(self.name.exists())


class RekeyTest(StorageCase):
    """ADR 0015 (#204): a new key for a profile's volume. After it, a key file kept from before opens
    nothing, with any secret; before it, a removed secret still opens the files with that key file (R70)."""

    LEAKED = "leaked password 9"

    def profile_with_files(self, keyring: Keyring | None = None) -> tuple[profile.Profile, str]:
        prof, code = self.encrypted_profile(keyring=keyring)
        profiles.unlock(prof, password=PASSWORD).lock()
        (prof.path / "places.sqlite").write_bytes(os.urandom(300_000))
        (prof.path / "storage" / "default").mkdir(parents=True)
        (prof.path / "storage" / "default" / "site.txt").write_text(MARKER)
        os.symlink("places.sqlite", prof.path / "link")
        profiles.lock(prof)
        return prof, code

    def files(self, prof: profile.Profile, **how) -> dict:
        """The profile's files as an unlock with `how` shows them (without the launcher's own record)."""
        profiles.unlock(prof, **how).lock()
        try:
            return {
                str(p.relative_to(prof.path)): (os.readlink(p) if p.is_symlink() else p.read_bytes())
                for p in sorted(prof.path.rglob("*"))
                if (p.is_file() or p.is_symlink()) and storage.STATE_DIR not in p.parts
            }
        finally:
            profiles.lock(prof)

    def api(self, prof: profile.Profile, op: str, **fields) -> dict:
        return vault_cli.api_request({"op": op, "path": str(prof.path), **fields})

    def kept(self, prof: profile.Profile) -> dict:
        """What someone who kept "the key file" has: the small files next to the encrypted ones."""
        box = profiles.container(prof)
        return {"vault.json": box.vault_path.read_bytes(), "gocryptfs.conf": (box.cipher / "gocryptfs.conf").read_bytes()}

    def reads_the_files(self, prof: profile.Profile, kept: dict, secret: str, *, their_conf: bool) -> bool:
        """Whether `kept` and `secret` read the profile's files as they are now, outside Nulavio (gocryptfs alone)."""
        work = Path(tempfile.mkdtemp(prefix="outside-", dir=self.tmp))
        (work / "vault.json").write_bytes(kept["vault.json"])
        vault = Vault.load(work / "vault.json")
        vault.unlock_password(secret)
        password = storage.storage_password(vault)
        vault.lock()
        cipher = work / "cipher"
        shutil.copytree(profiles.container(prof).cipher, cipher, symlinks=True)  # the encrypted files as they are now
        if their_conf:
            (cipher / "gocryptfs.conf").unlink()  # read-only, as gocryptfs makes it
            (cipher / "gocryptfs.conf").write_bytes(kept["gocryptfs.conf"])
        (work / "mnt").mkdir()
        # Not pipes for the output: the mounting daemon inherits them and would keep them open.
        mounted = subprocess.run(
            ["gocryptfs", "-q", "-nosyslog", str(cipher), str(work / "mnt")],
            input=(password + "\n").encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        if mounted.returncode != 0:
            return False
        try:
            return contains(work / "mnt", MARKER.encode())
        except OSError:
            return False
        finally:
            subprocess.run(["fusermount3", "-u", "-z", str(work / "mnt")], check=False, capture_output=True)

    def remove_a_leaked_password(self, prof: profile.Profile) -> dict:
        """A second password added and removed again; returns what was kept from while it was valid."""
        self.api(prof, "add-password", current=PASSWORD, password=self.LEAKED)
        kept = self.kept(prof)
        leaked = next(
            m["id"] for m in profiles.status(prof)["methods"] if m["method"] == "password" and m["id"] != self.first_password
        )
        self.api(prof, "remove-method", current=PASSWORD, envelope=leaked)
        return kept

    def setUp(self):
        super().setUp()
        self.prof, self.code = self.profile_with_files()
        self.first_password = next(m["id"] for m in profiles.status(self.prof)["methods"] if m["method"] == "password")
        self.before = self.files(self.prof, password=PASSWORD)

    def test_after_a_new_key_the_old_key_file_and_secret_open_nothing(self):
        prof = self.prof
        self.assertEqual(profiles.status(prof)["key"]["last_removal"], None)
        kept = self.remove_a_leaked_password(prof)
        key = profiles.status(prof)["key"]
        self.assertTrue(key["tracked"] and key["last_removal"], key)
        # The limit this closes (R70): the removed password still reads the files with the key file from before.
        self.assertTrue(self.reads_the_files(prof, kept, self.LEAKED, their_conf=False))
        result = self.api(prof, "rekey", current=PASSWORD)
        self.assertEqual(result["done"], True)
        self.assertEqual([m["method"] for m in result["carried"]], ["password"])
        self.assertEqual([m["method"] for m in result["dropped"]], ["recovery-code"])
        # Now neither that key file nor it together with the volume's own key file of then reads anything.
        self.assertFalse(self.reads_the_files(prof, kept, self.LEAKED, their_conf=False))
        self.assertFalse(self.reads_the_files(prof, kept, self.LEAKED, their_conf=True))
        self.assertFalse(self.reads_the_files(prof, kept, PASSWORD, their_conf=True))  # nor a secret that is still valid
        # Put back in place, the key file from before opens nothing through Nulavio either.
        box = profiles.container(prof)
        current = box.vault_path.read_bytes()
        for name in ("vault.json", "vault.json.bak"):
            (box.root / name).write_bytes(kept["vault.json"])
        for secret in (self.LEAKED, PASSWORD):
            with self.assertRaises(VaultError) as ctx:
                profiles.unlock(prof, password=secret)
            self.assertEqual(ctx.exception.code, "wrong-key")
            self.assertFalse(box.mounted())
        for name in ("vault.json", "vault.json.bak"):
            (box.root / name).write_bytes(current)
        # The profile itself: every file as it was, opened by the password that was typed; the code is gone.
        self.assertEqual(self.files(prof, password=PASSWORD), self.before)
        with self.assertRaises(VaultError) as ctx:
            profiles.unlock(prof, recovery_code=self.code)
        self.assertEqual(ctx.exception.code, "no-such-method")
        after = profiles.status(prof)
        self.assertEqual([m["method"] for m in after["methods"]], ["password"])
        self.assertEqual(after["key"]["last_removal"], None)
        self.assertFalse((box.root / storage.REKEY).exists() or (box.root / "cipher.old").exists())
        # Its record inside the new volume is the new key file's: the next unlock checks it and passes.
        profiles.unlock(prof, password=PASSWORD).lock()
        state = json.loads(box.state_path.read_text())
        self.assertEqual(state["generation"], json.loads(box.vault_path.read_text())["generation"])
        profiles.lock(prof)
        # A first recovery code is made the usual way afterwards.
        new_code = self.api(prof, "new-recovery-code", current=PASSWORD)["recovery_code"]
        self.assertEqual(self.api(prof, "confirm-recovery-code", current=new_code), {"done": True})

    def test_the_recovery_code_typed_is_the_one_carried(self):
        result = self.api(self.prof, "rekey", current=self.code)
        self.assertEqual([m["method"] for m in result["carried"]], ["recovery-code"])
        self.assertEqual([m["method"] for m in result["dropped"]], ["password"])
        self.assertEqual(self.files(self.prof, recovery_code=self.code), self.before)
        with self.assertRaises(VaultError):
            profiles.unlock(self.prof, password=PASSWORD)

    def test_this_computers_login_is_carried_with_a_new_keyring_key(self):
        keyring = MemoryKeyring()
        with mock.patch.object(vault_cli, "keyring", return_value=keyring):
            self.api(self.prof, "add-keyring", current=PASSWORD)
            before = dict(keyring.items)
            result = self.api(self.prof, "rekey", current=PASSWORD)
            self.assertEqual(sorted(m["method"] for m in result["carried"]), ["os-keyring", "password"])
            self.assertEqual(len(keyring.items), 1)  # the key of before is gone from the keyring: it wraps nothing now
            self.assertFalse(set(keyring.items) & set(before))
            self.assertEqual(self.files(self.prof, keyring=keyring), self.before)

    def test_refused_before_anything_changes(self):
        prof, box = self.prof, profiles.container(self.prof)
        untouched = lambda: (box.vault_path.read_bytes(), sorted(p.name for p in box.root.iterdir()))  # noqa: E731
        was = untouched()
        cases = {"wrong-secret": {"current": "not the password"}, "no-space": {"current": PASSWORD}}
        for code, fields in cases.items():
            enough = code != "no-space"
            space = {"size": 1, "free": 0, "enough": enough}
            with self.subTest(code=code), mock.patch.object(storage, "rekey_space", return_value=space):
                with self.assertRaises(VaultError) as ctx:
                    self.api(prof, "rekey", **fields)
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(untouched(), was)
        profiles.unlock(prof, password=PASSWORD).lock()  # open: its files are in use
        with self.assertRaises(VaultError) as ctx:
            self.api(prof, "rekey", current=PASSWORD)
        self.assertEqual(ctx.exception.code, "unlocked")
        profiles.lock(prof)
        self.assertEqual(untouched()[0], was[0])
        check = self.api(prof, "rekey-check")
        self.assertTrue(check["enough"] and check["locked"] and not check["running"], check)
        self.assertGreater(check["size"], 300_000)

    def interrupt(self, how: str) -> subprocess.CompletedProcess:
        script = self.tmp / "rekey.py"
        script.write_text(INTERRUPTED_REKEY)
        args = [sys.executable, str(script), str(ROOT / "launcher"), str(self.prof.path), how, PASSWORD]
        return subprocess.run(args, capture_output=True, text=True, timeout=120)

    def assert_as_before(self) -> None:
        box = storage.Container(self.prof.path)
        self.assertEqual(sorted(m["method"] for m in profiles.status(self.prof)["methods"]), ["password", "recovery-code"])
        self.assertFalse((box.root / storage.REKEY).exists())
        self.assertFalse(any(m.startswith(str(box.root)) for m in storage.mounted_paths()), "a volume stayed mounted")
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)
        self.assertEqual(self.files(self.prof, recovery_code=self.code), self.before)

    def test_an_interruption_before_the_copy_is_whole_is_undone(self):
        box = storage.Container(self.prof.path)
        # Stopped (SIGTERM, a closed terminal): cleaned up at once, before anything looks at the profile again.
        self.assertNotEqual(self.interrupt("term-mid-copy").returncode, 0)
        self.assertFalse((box.root / storage.REKEY).exists())
        self.assertFalse(any(m.startswith(str(box.root)) for m in storage.mounted_paths()), "a volume stayed mounted")
        self.assert_as_before()
        # Killed: what it left (the staging directory, two mounted volumes) is undone by the next use of the profile.
        self.assertEqual(self.interrupt("kill-mid-copy").returncode, -signal.SIGKILL)
        self.assertTrue((box.root / storage.REKEY).exists())
        self.assert_as_before()

    def test_an_interruption_after_the_copy_is_whole_is_finished(self):
        box = storage.Container(self.prof.path)
        for how in (
            "kill-before-switch",
            "kill-after-rename-1",
            "kill-after-rename-2",
            "kill-after-key-file-1",
            "kill-after-key-file-2",
        ):
            with self.subTest(how=how):
                self.assertEqual(self.interrupt(how).returncode, -signal.SIGKILL)
                self.assertTrue((box.root / storage.REKEY / storage.REKEY_COMPLETE).exists())
                status = profiles.status(self.prof)  # any use of the profile finishes it
                self.assertEqual([m["method"] for m in status["methods"]], ["password"])
                self.assertFalse((box.root / storage.REKEY).exists() or (box.root / "cipher.old").exists())
                self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)
                with self.assertRaises(VaultError):
                    profiles.unlock(self.prof, recovery_code=self.code)
                # For the next round: a recovery code again, as the page makes one right after.
                self.code = self.api(self.prof, "new-recovery-code", current=PASSWORD)["recovery_code"]
                self.api(self.prof, "confirm-recovery-code", current=self.code)

    def test_the_command_line_says_what_a_removal_leaves_and_what_the_new_key_did(self):
        self.api(self.prof, "add-password", current=PASSWORD, password=self.LEAKED)
        leaked = next(
            m["id"] for m in profiles.status(self.prof)["methods"] if m["method"] == "password" and m["id"] != self.first_password
        )
        removed = self.nulavio(
            "vault", "remove-method", "--path", str(self.prof.path), leaked, "--password-stdin", stdin=PASSWORD + "\n"
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertIn("nulavio vault rekey", removed.stdout)
        listed = self.nulavio("vault", "status", "--path", str(self.prof.path))
        self.assertIn("a method was removed or replaced on", listed.stdout)
        done = self.nulavio("vault", "rekey", "--path", str(self.prof.path), "--password-stdin", stdin=PASSWORD + "\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("has a new key. Still opens it: password.", done.stdout)
        self.assertIn("No longer opens it: recovery code.", done.stdout)
        self.assertIn("vault new-recovery-code", done.stdout)
        self.assertNotIn("a method was removed", self.nulavio("vault", "status", "--path", str(self.prof.path)).stdout)
        self.assertNotIn(PASSWORD, done.stdout + done.stderr)
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    # -- review of #275 ------------------------------------------------------------------------------

    def test_a_volume_detached_during_the_copy_is_still_the_one_copied(self):
        # The copy went by the mount points' paths: with the old volume detached under it, it "copied" the empty
        # directory beneath, the two empty listings matched, and the old volume was deleted. Every file was lost.
        box, real = profiles.container(self.prof), storage._copy_checked
        tool = shutil.which("fusermount3") or "fusermount"

        def detached(source, target):
            for name in ("old", "new"):
                subprocess.run([tool, "-u", "-z", str(box.root / storage.REKEY / name)], check=True, capture_output=True)
            real(source, target)

        with mock.patch.object(storage, "_copy_checked", detached):
            self.assertEqual(self.api(self.prof, "rekey", current=PASSWORD)["done"], True)
        self.assertFalse((box.root / storage.REKEY).exists())
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    def test_a_volume_without_its_record_is_not_copied(self):
        # What is mounted where the old volume should be is checked to be the profile's: an empty directory is not.
        with mock.patch.object(storage, "_listing", return_value={}), self.assertRaises(VaultError) as ctx:
            self.api(self.prof, "rekey", current=PASSWORD)
        self.assertEqual(ctx.exception.code, "copy-mismatch")
        self.assert_as_before()

    def test_an_unlock_that_waited_does_not_open_the_old_volume_under_a_new_key_about_to_take_its_place(self):
        # An unlock that read the key file, then waited for the state lock while a new key was made and killed
        # after its copy was whole: it mounted the old volume, and the next use of the profile "finished" the
        # new key under it, deleting the encrypted files of the profile that was open.
        box = profiles.container(self.prof)
        waiting = box.load_vault()
        waiting.unlock_password(PASSWORD)
        self.assertEqual(self.interrupt("kill-before-switch").returncode, -signal.SIGKILL)
        with self.assertRaises(VaultError) as ctx:
            box.mount(waiting)  # as that unlock, once it has the lock
        waiting.lock()
        self.assertEqual(ctx.exception.code, "changed")
        self.assertFalse(box.mounted())
        self.assertFalse((box.root / storage.REKEY).exists())  # finished first, under the same lock
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    def test_a_new_key_is_not_put_in_place_under_a_mounted_volume(self):
        box = profiles.container(self.prof)
        vault = box.load_vault()
        vault.unlock_password(PASSWORD)
        password = storage.storage_password(vault)
        vault.lock()
        self.assertEqual(self.interrupt("kill-before-switch").returncode, -signal.SIGKILL)
        # The old volume mounted by something that did not settle the new key first (an older launcher).
        os.chmod(self.prof.path, 0o700)
        box._gocryptfs(["-q", "-nosyslog", str(box.cipher), str(self.prof.path)], password)
        self.assertIsNone(storage.recover_rekey(self.prof.path))
        self.assertTrue((box.root / storage.REKEY / storage.REKEY_COMPLETE).exists())
        self.assertEqual((self.prof.path / "storage" / "default" / "site.txt").read_text(), MARKER)  # still there, still readable
        box.unmount()
        self.assertEqual(storage.recover_rekey(self.prof.path), "finished")
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    def test_a_switch_that_fails_says_the_new_key_was_made_and_is_finished_next_time(self):
        # After the copy is marked whole nothing is undone: the answer is not "nothing was changed".
        box = profiles.container(self.prof)
        failing = mock.patch.object(storage, "_rekey_finish", side_effect=OSError(5, "Input/output error"))
        with failing, self.assertRaises(VaultError) as ctx:
            self.api(self.prof, "rekey", current=PASSWORD)
        self.assertEqual(ctx.exception.code, "rekey-unfinished")
        self.assertTrue((box.root / storage.REKEY / storage.REKEY_COMPLETE).exists())
        self.assertEqual([m["method"] for m in profiles.status(self.prof)["methods"]], ["password"])  # finished by this use
        self.assertFalse((box.root / storage.REKEY).exists())
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    def test_what_an_undone_new_key_left_does_not_stop_the_profile(self):
        # Something in rekey/ that cannot be removed (here: a file where a mount point was) with no marker: the
        # profile is untouched by it and keeps working; it is removed once it can be.
        box = profiles.container(self.prof)
        left = box.root / storage.REKEY / "new"
        left.mkdir(parents=True)
        (left / "left-behind").write_text("x")
        self.assertIsNone(storage.recover_rekey(self.prof.path))
        self.assertEqual(sorted(m["method"] for m in profiles.status(self.prof)["methods"]), ["password", "recovery-code"])
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)
        (left / "left-behind").unlink()
        self.assertEqual(storage.recover_rekey(self.prof.path), "undone")
        self.assert_as_before()

    def test_the_method_that_was_typed_is_carried_or_nothing_changes(self):
        # With this computer's login also on the profile, a failure to wrap the typed password again used to
        # save a profile that the secret just typed no longer opened.
        keyring = MemoryKeyring()
        real = Vault.add_password

        def add_password(vault, password, *args, **kwargs):
            if "rekey" in str(vault.path):
                raise VaultError("damaged-envelope")
            return real(vault, password, *args, **kwargs)

        with mock.patch.object(vault_cli, "keyring", return_value=keyring):
            self.api(self.prof, "add-keyring", current=PASSWORD)
            before = dict(keyring.items)
            with mock.patch.object(Vault, "add_password", add_password), self.assertRaises(VaultError) as ctx:
                self.api(self.prof, "rekey", current=PASSWORD)
            self.assertEqual(ctx.exception.code, "failed")
            self.assertEqual(keyring.items, before)  # no new keyring key left behind
        methods = sorted(m["method"] for m in profiles.status(self.prof)["methods"])
        self.assertEqual(methods, ["os-keyring", "password", "recovery-code"])
        self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)

    def test_a_volume_detached_with_a_file_open_is_still_in_use(self):
        # Review of #275, round 2: a volume detached while a file in it is open is gone from the mount table and
        # still written to. The switch waits for the process that serves it, not only for the mount table.
        box = profiles.container(self.prof)
        profiles.unlock(self.prof, password=PASSWORD).lock()
        with open(self.prof.path / "places.sqlite", "rb"):
            tool = shutil.which("fusermount3") or "fusermount"
            subprocess.run([tool, "-u", "-z", str(self.prof.path)], check=True, capture_output=True)
            self.assertFalse(box.mounted())
            self.assertTrue(storage._volume_in_use(box))
        wait_for(lambda: not storage._volume_in_use(box))

    def test_with_the_new_key_in_place_what_is_left_to_clean_does_not_stop_the_profile(self):
        # Round 2: only the old volume's directory is left to delete, and that fails: the volume and the key file
        # match, so the profile is used; the clean-up is tried again each time.
        box = profiles.container(self.prof)
        real = shutil.rmtree

        def rmtree(target, *args, **kwargs):
            if str(target).endswith("cipher.old"):
                raise OSError(5, "Input/output error")
            return real(target, *args, **kwargs)

        with mock.patch.object(storage.shutil, "rmtree", rmtree):
            with self.assertRaises(VaultError) as ctx:
                self.api(self.prof, "rekey", current=PASSWORD)
            self.assertEqual(ctx.exception.code, "rekey-unfinished")
            self.assertEqual(self.files(self.prof, password=PASSWORD), self.before)  # used, with the clean-up still failing
            self.assertTrue((box.root / "cipher.old").exists())
        self.assertEqual([m["method"] for m in profiles.status(self.prof)["methods"]], ["password"])
        self.assertFalse((box.root / "cipher.old").exists() or (box.root / storage.REKEY).exists())

    def test_the_new_key_is_wiped_from_memory_when_it_fails(self):
        # Review of #275 (Codex): the new vault was locked only by the caller, which never got it when the new
        # key failed; the new DEK then stayed in memory, unwiped. Before the marker, after it, and at the switch.
        made = []
        real = Vault.create.__func__

        def create(cls, path, profile_id=None):
            made.append(real(cls, path, profile_id))
            return made[-1]

        failures = {
            "copy-mismatch": mock.patch.object(storage, "_listing", return_value={}),
            "storage-failed": mock.patch.object(storage, "_copy_checked", side_effect=OSError(5, "Input/output error")),
            "rekey-unfinished": mock.patch.object(storage, "_rekey_finish", side_effect=OSError(5, "Input/output error")),
        }
        for code, failing in failures.items():
            with self.subTest(code=code):
                made.clear()
                with mock.patch.object(Vault, "create", classmethod(create)), failing, self.assertRaises(VaultError) as ctx:
                    self.api(self.prof, "rekey", current=PASSWORD)
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(len(made), 1)
                self.assertIsNone(made[0].dek, "the new key stayed in memory")
                profiles.status(self.prof)  # whatever was left is settled before the next round

    def test_an_unfinished_switch_does_not_say_the_recovery_code_that_was_typed_stopped_working(self):
        # Review of #275 (Codex): authorized with the recovery code, and the switch fails after the marker. The
        # words said the recovery code no longer worked, when it was the one method carried.
        failing = mock.patch.object(storage, "_rekey_finish", side_effect=OSError(5, "Input/output error"))
        with failing, self.assertRaises(VaultError) as ctx:
            self.api(self.prof, "rekey", current=self.code)
        self.assertEqual(ctx.exception.code, "rekey-unfinished")
        self.assertNotIn("recovery code no longer", vault_cli.MESSAGES["rekey-unfinished"])
        self.assertEqual([m["method"] for m in profiles.status(self.prof)["methods"]], ["recovery-code"])  # finished by this use
        self.assertEqual(self.files(self.prof, recovery_code=self.code), self.before)


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
        # The mount point is read-only underneath the volume now, so such an end leaves it 0500
        # by itself; a volume mounted by an earlier version still leaves it 0700, which the next
        # launcher call on the profile puts right.
        prof, _ = self.encrypted_profile()
        profiles.unlock(prof, password=PASSWORD).lock()
        box = profiles.container(prof)
        subprocess.run(["fusermount3", "-u", "-z", str(box.mountpoint)], check=True, capture_output=True)  # not unmount()
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(box.mountpoint).st_mode & 0o777, 0o500)
        os.chmod(box.mountpoint, 0o700)  # as a volume mounted by an earlier version left it
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

        def check_state(self, vault, volume_fd=None, **kw):
            calls.append(volume_fd)
            if len(calls) == 2:  # the record after the save: the volume has gone
                raise OSError(107, "Transport endpoint is not connected")
            return real(self, vault, volume_fd, **kw)

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

        def check_state(self, vault, volume_fd=None, **kw):
            if vault.settled is not None:  # the settlement's record, after its save: the volume is gone
                raise OSError(107, "Transport endpoint is not connected")
            return real(self, vault, volume_fd, **kw)

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

    def test_autolock_follows_an_engine_that_takes_the_profile_while_it_locks(self):
        """An engine that takes the profile while the watcher is still unmounting (the last engine's helpers holding a
        file) is followed like the first one: the volume stays mounted and shown as unlocked while it runs, and is
        locked once it is gone."""
        path = self.tmp / "taken"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        box = storage.Container(path)
        prof = profile.Profile(name="taken", path=path)
        looks = []
        real_running_pid = prof.running_pid

        def running_pid():
            looks.append(1)
            return real_running_pid()

        prof.running_pid = running_pid
        unmounting = threading.Event()
        real_unmount = storage.Container.unmount

        def unmount(container, *args, **kwargs):
            unmounting.set()
            return real_unmount(container, *args, **kwargs)

        held = open(path / "closing-helper.txt", "w")  # noqa: SIM115 - the last engine's helper, still closing a file
        result: list = []
        with mock.patch.object(storage.Container, "unmount", unmount):
            thread = threading.Thread(target=lambda: result.append(profiles.autolock(prof, grace=0.3, poll=0.1)), daemon=True)
            thread.start()
            self.assertTrue(unmounting.wait(10), "the watcher never began to lock")
            env = self.fake_engine()
            engine = subprocess.Popen([env["NULAVIO_ENGINE"], "--profile", str(path)], env=env)
            self.addCleanup(lambda: engine.poll() is None and engine.kill())
            wait_for(lambda: real_running_pid())
            held.close()
            seen = len(looks)
            wait_for(lambda: len(looks) > seen + 5 or not box.mounted())
            self.assertTrue(box.mounted(), "the volume went while an engine was using it")
            self.assertTrue(profiles.status(prof)["running"])
            self.assertTrue(thread.is_alive())
            self.stop_file.touch()
            engine.wait(10)
            thread.join(30)
        self.assertEqual(result, ["closed"])
        self.assertFalse(box.mounted())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o500)

    def test_an_agents_engine_starts_under_the_profiles_state_lock(self):
        """ProfileTarget checks a protected profile and starts its engine under the profile's state lock, the one the
        auto-lock watcher locks under: while it is held elsewhere, the agent is refused and nothing is written."""
        from nulavio_launcher.ai import workspace

        path = self.tmp / "agent"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        box = storage.Container(path)
        target = workspace.ProfileTarget("ag-1", "Trabalho", path, downloads_dir=self.tmp / "dl")

        def starting(timeout=60.0):
            with self.assertRaises(storage.StorageError), box._state_lock(wait=0):
                pass  # held by the start itself
            return "bidi"

        with mock.patch.object(workspace.Workspace, "start", side_effect=starting) as started:
            with box._state_lock(), self.assertRaises(workspace.TargetError) as refused:
                target.start()
            self.assertEqual(refused.exception.code, "profile-busy")
            started.assert_not_called()
            self.assertFalse((path / "user.js").exists())
            self.assertEqual(target.start(), "bidi")
            started.assert_called_once()
        with box._state_lock(wait=0):
            pass  # and released once the engine runs

    def short_lived_engine(self, path: Path, *, killed: bool) -> None:
        """An engine that takes the lock and is gone again within a tenth of a second: killed (the lock
        stays behind) or quitting (it removes the lock), between two looks of the watcher (#277)."""
        script = f'ln -s "127.0.0.1:+$$" "{path}/lock"; sleep 0.1; ' + ("kill -9 $$" if killed else f'rm -f "{path}/lock"')
        subprocess.run(["/bin/sh", "-c", script], check=False, timeout=10)

    def watch(self, path: Path, name: str, grace: float = 30.0) -> tuple[list, threading.Thread]:
        """The watcher, started and past its first look before the engine comes. It looks every 5 s, so an
        engine that lives a tenth of a second is never running when it looks: polling alone cannot see it."""
        prof = profile.Profile(name=name, path=path)
        result: list = []
        first_look = threading.Event()
        real_running_pid = prof.running_pid

        def running_pid():
            pid = real_running_pid()
            first_look.set()
            return pid

        prof.running_pid = running_pid
        thread = threading.Thread(target=lambda: result.append(profiles.autolock(prof, grace=grace, poll=5.0)), daemon=True)
        thread.start()
        self.assertTrue(first_look.wait(10), "the watcher never looked")
        return result, thread

    def test_autolock_sees_an_engine_that_lived_under_half_a_second(self):
        for killed in (False, True):
            with self.subTest(killed=killed):
                path = self.tmp / f"short-{int(killed)}"
                path.mkdir()
                self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
                self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
                result, thread = self.watch(path, f"short-{int(killed)}")
                started = time.monotonic()
                self.short_lived_engine(path, killed=killed)
                thread.join(20)
                self.assertEqual(result, ["closed"], "the watcher waited out its grace")
                self.assertLess(time.monotonic() - started, 20)
                self.assertFalse(storage.Container(path).mounted())

    def test_autolock_without_inotify_still_sees_a_lock_a_killed_engine_left(self):
        path = self.tmp / "no-inotify"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        with mock.patch.object(profiles.ctypes, "CDLL", side_effect=OSError("no libc here")):
            result, thread = self.watch(path, "no-inotify")
            self.short_lived_engine(path, killed=True)
            thread.join(20)
        self.assertEqual(result, ["closed"])
        self.assertFalse(storage.Container(path).mounted())

    def test_a_lock_left_a_moment_before_the_watcher_started_is_not_an_engine_that_came(self):
        """A crash just before the profile was unlocked again leaves a lock younger than a second: still old."""
        path = self.tmp / "recent-stale"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        os.symlink("127.0.0.1:+999999", path / "lock")
        with mock.patch.object(profiles.ctypes, "CDLL", side_effect=OSError("no libc here")):  # the fallback alone
            self.assertEqual(profiles.autolock(profile.Profile(name="recent-stale", path=path), grace=2.0, poll=0.2), "unused")

    def test_a_lock_left_from_an_earlier_session_is_not_an_engine_that_came(self):
        path = self.tmp / "stale"
        path.mkdir()
        self.api({"op": "encrypt", "path": str(path), "password": PASSWORD})
        self.api({"op": "unlock", "path": str(path), "method": "password", "secret": PASSWORD, "autolock": False})
        os.symlink("127.0.0.1:+999999", path / "lock")
        an_hour_ago = time.time() - 3600
        os.utime(path / "lock", (an_hour_ago, an_hour_ago), follow_symlinks=False)
        prof = profile.Profile(name="stale", path=path)
        started = time.monotonic()
        self.assertEqual(profiles.autolock(prof, grace=2.0, poll=0.2), "unused")  # the grace, not the old lock, ended it
        self.assertGreaterEqual(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
