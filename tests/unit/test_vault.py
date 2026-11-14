"""Nulavio Vault and phone unlock (S3): the brief's mandatory tests, on artificial data.

Each class maps to one mandatory test of docs/product/briefs/2026-10-26-profile-unlock.md
and to the scenarios of docs/security/threat-model-unlock.md. The phone is the
reference implementation in tests/lib/phone_reference.py; the OS keyring is a
stub `secret-tool` in a temporary directory, never the real one.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from nulavio_launcher.vault import sodium

if not sodium.available():  # pragma: no cover - CI installs libsodium and sets NULAVIO_REQUIRE_SODIUM
    if os.environ.get("NULAVIO_REQUIRE_SODIUM"):
        raise RuntimeError("libsodium is required for the Vault tests")
    raise unittest.SkipTest("libsodium is not installed")

from nulavio_launcher.vault.coordinator import Coordinator, DeviceUnavailable, State, Transport
from nulavio_launcher.vault.core import Vault, VaultError, b64e, canonical, combined_kek
from nulavio_launcher.vault.phone import (
    DesktopIdentity,
    Pairing,
    PhoneUnlock,
    ProtocolError,
    add_password_and_phone,
    add_phone,
    remove_phone,
    request_signing_input,
    response_key,
    unseal,
)
from nulavio_launcher.vault.providers import Keyring, add_os_keyring, remove_os_keyring
from phone_reference import PhoneRejected, ReferencePhone, pair

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "vault-v1"
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}  # tests only; real defaults are tested once
PASSWORD = "artificial password 1"


class Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Loopback(Transport):
    def __init__(self, reachable: bool = True):
        self.reachable = reachable
        self.sent: list[dict] = []

    def send(self, request: dict) -> None:
        if not self.reachable:
            raise DeviceUnavailable
        self.sent.append(request)


FAKE_SECRET_TOOL = """\
#!{python} -I
import json, os, sys
store = os.environ["NV_FAKE_KEYRING"]
with open(os.environ["NV_FAKE_KEYRING_ARGV"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
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
fd = os.open(store, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, json.dumps(items).encode())
os.close(fd)
"""


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="nv-vault-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.clock = Clock()
        self.identity = DesktopIdentity.load_or_create(self.dir / "desktop.json")

    # helpers ------------------------------------------------------------------------

    def new_vault(
        self, name: str = "vault.json", password: bool = True, recovery: bool = False
    ) -> tuple[Vault, bytes, str | None]:
        vault = Vault.create(self.dir / name)
        if password:
            vault.add_password(PASSWORD, FAST, label="password")
        code = vault.add_recovery_code(FAST) if recovery else None
        return vault, bytes(vault.dek), code

    def pair_phone(self, name: str = "Phone A") -> ReferencePhone:
        phone = ReferencePhone(name, self.clock)
        self.paired = pair(Pairing(self.identity, "Test desktop", clock=self.clock), phone)
        return phone

    def reopen(self, vault: Vault) -> Vault:
        vault.save()
        vault.lock()
        return Vault.load(vault.path)

    def coordinator(self, vault: Vault, transport: Transport | None = None, **kw) -> Coordinator:
        self.transport = transport or Loopback()
        return Coordinator(
            vault, phone=PhoneUnlock(self.identity, "Test desktop", self.clock), transport=self.transport, clock=self.clock, **kw
        )

    def fake_keyring(self) -> Keyring:
        tool = self.dir / "bin" / "secret-tool"
        tool.parent.mkdir()
        tool.write_text(FAKE_SECRET_TOOL.format(python=sys.executable))
        tool.chmod(0o700)
        self.keyring_store = self.dir / "keyring.json"
        self.keyring_argv = self.dir / "keyring-argv.log"
        env = {"NV_FAKE_KEYRING": str(self.keyring_store), "NV_FAKE_KEYRING_ARGV": str(self.keyring_argv)}
        return Keyring(str(tool), env)

    def assert_locked(self, vault: Vault) -> None:
        self.assertFalse(vault.unlocked)
        self.assertIsNone(vault.dek)


# 1. Perfil não desbloqueia sem método válido.
class NoUnlockWithoutValidMethodTest(VaultTestCase):
    def test_wrong_secrets_are_refused(self):
        vault, _, _code = self.new_vault(recovery=True)
        vault = self.reopen(vault)
        for attempt in (
            lambda: vault.unlock_password("not the password"),
            lambda: vault.unlock_recovery_code("0000-0000-0000-0000-0000-0000-0000"),
            lambda: vault.unlock_kek(vault.envelopes("password")[0].id, sodium.random_bytes(32)),
        ):
            with self.assertRaises(VaultError) as ctx:
                attempt()
            self.assertEqual(ctx.exception.code, "wrong-secret")
            self.assert_locked(vault)
        with self.assertRaises(VaultError) as ctx:
            vault.unlock_recovery_code("too-short")
        self.assertEqual(ctx.exception.code, "recovery-code-malformed")

    def test_method_that_is_not_configured(self):
        vault = self.reopen(self.new_vault()[0])
        with self.assertRaises(VaultError) as ctx:
            vault.unlock_recovery_code("0000-0000-0000-0000-0000-0000-0000")
        self.assertEqual(ctx.exception.code, "no-such-method")
        c = self.coordinator(vault)
        self.assertEqual(c.unlock_keyring(), State.DEVICE_UNAVAILABLE)
        self.assert_locked(vault)

    def test_keyring_entry_missing(self):
        keyring = self.fake_keyring()
        vault, _, _ = self.new_vault()
        add_os_keyring(vault, keyring)
        vault = self.reopen(vault)
        self.keyring_store.unlink()  # e.g. another machine, or the keyring was reset
        c = Coordinator(vault, keyring=keyring)
        self.assertEqual(c.unlock_keyring(), State.DEVICE_UNAVAILABLE)
        self.assertEqual(c.error, "keyring-missing")
        self.assertEqual([m["method"] for m in c.alternatives], ["password"])
        self.assert_locked(vault)

    def test_cannot_save_without_a_method_or_remove_the_last(self):
        vault = Vault.create(self.dir / "empty.json")
        with self.assertRaises(VaultError):
            vault.save()
        vault.add_password(PASSWORD, FAST)
        with self.assertRaises(VaultError) as ctx:
            vault.remove(vault.envelopes()[0].id)
        self.assertEqual(ctx.exception.code, "last-method")
        with self.assertRaises(VaultError):
            vault.add_password("short", FAST)


# 2. O celular aprovado consegue liberar o material necessário.
class PhoneReleasesKeyTest(VaultTestCase):
    def test_paired_phone_unlocks(self):
        phone = self.pair_phone()
        vault, dek, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        vault = self.reopen(vault)
        self.assertIn("phone_key_release_verified", vault.protection_states())
        c = self.coordinator(vault)
        request = c.start_phone(env.id, "Work")
        self.assertEqual(c.state, State.WAITING_FOR_PHONE)
        self.assertEqual(self.transport.sent, [request])
        c.phone_acknowledged()
        self.assertEqual(c.state, State.WAITING_FOR_BIOMETRIC)
        self.assertEqual(c.receive(phone.handle(request)), State.UNLOCKED)
        self.assertEqual(bytes(vault.dek), dek)
        self.assertEqual(c.history[-4:], [State.WAITING_FOR_BIOMETRIC, State.AUTHORIZED, State.UNLOCKING, State.UNLOCKED])

    def test_request_shows_profile_and_desktop(self):
        self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        request = self.coordinator(vault).start_phone(env.id, "Banking")["r"]
        self.assertEqual(
            (request["profile_name"], request["desktop_name"], request["op"]), ("Banking", "Test desktop", "unlock-profile")
        )
        self.assertEqual(request["expiry"], int(self.clock.now) + 60)


# 3. A simples ausência de erro de autenticação não equivale a sucesso criptográfico.
class ApprovalIsNotUnlockTest(VaultTestCase):
    def test_signed_approval_without_the_key_does_not_unlock(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        vault = self.reopen(vault)
        c = self.coordinator(vault)
        request = c.start_phone(env.id, "Work")
        # A phone (or a tampered app) that approves and signs, but sends a random key.
        real = phone.handle(request)
        bogus_kek = bytes(sodium.random_bytes(32))
        with mock.patch("phone_reference.phone_kek", return_value=bytearray(bogus_kek)):
            phone.seen.clear()
            forged = phone.handle(request)
        self.assertNotEqual(real["box"], forged["box"])
        self.assertEqual(c.receive(forged), State.ERROR)
        self.assertEqual(c.error, "wrong-secret")
        self.assert_locked(vault)

    def test_approval_flag_alone_is_ignored(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        request = c.start_phone(env.id, "Work")
        approval_only = {
            "req_id": request["r"]["req_id"],
            "phone_id": phone.phone_id,
            "approved": True,
            "sig": phone.handle(request)["sig"],
        }
        self.assertEqual(c.receive(approval_only), State.WAITING_FOR_PHONE)  # bad signature: still waiting
        self.assert_locked(c.vault)

    def test_unlocked_state_only_with_the_dek(self):
        vault = self.reopen(self.new_vault()[0])
        c = Coordinator(vault)
        self.assertEqual(c.unlock_password("wrong password"), State.ERROR)
        self.assertNotIn(State.UNLOCKED, c.history)
        self.assertEqual(c.unlock_password(PASSWORD), State.UNLOCKED)
        self.assertTrue(vault.unlocked)


# 4. Não é possível recuperar a DEK copiando apenas os arquivos protegidos.
class CopiedFilesTest(VaultTestCase):
    def test_files_never_contain_the_dek(self):
        keyring = self.fake_keyring()
        self.pair_phone()
        vault, dek, _ = self.new_vault(recovery=True)
        add_phone(vault, self.paired)
        add_os_keyring(vault, keyring)
        vault.save()
        vault.save()  # also produces vault.json.bak
        encodings = [dek, dek.hex().encode(), base64.b64encode(dek), b64e(dek).encode(), base64.b32encode(dek)]
        for path in [*self.dir.rglob("*")]:
            if path.is_file():
                data = path.read_bytes()
                for form in encodings:
                    self.assertNotIn(form, data, f"DEK found in {path.name}")

    def test_copy_without_a_factor_stays_locked(self):
        vault, _, _code = self.new_vault(recovery=True)
        vault.save()
        copy = self.dir / "stolen"
        copy.mkdir()
        shutil.copy2(self.dir / "vault.json", copy / "vault.json")
        stolen = Vault.load(copy / "vault.json")
        for guess in ("password", "12345678", PASSWORD.upper(), ""):
            with self.assertRaises(VaultError):
                stolen.unlock_password(guess)
        self.assert_locked(stolen)
        stolen.unlock_password(PASSWORD)  # the copy is only as strong as the factors
        self.assertTrue(stolen.unlocked)

    def test_a_revoked_secret_opens_no_file_left_on_disk(self):
        # Audit V2 (2026-11-10): the .bak kept the previous file, so a replaced recovery
        # code or a removed password still opened the profile through it.
        vault, _, old_code = self.new_vault(recovery=True)
        weak = vault.add_password("weak-old-password", FAST, label="old")
        vault.save()
        vault.save()
        new_code = vault.replace_recovery_code(FAST)
        vault = self.reopen(vault)
        vault.unlock_recovery_code(new_code)  # typed back: the replacement is confirmed (#187)
        vault.confirm_recovery_code()
        vault.remove(weak.id)
        vault.save()
        for name in ("vault.json", "vault.json.bak"):
            copy = self.dir / f"check-{name}"
            copy.mkdir()
            shutil.copy2(self.dir / name, copy / "vault.json")
            left = Vault.load(copy / "vault.json")
            with self.subTest(file=name):
                with self.assertRaises(VaultError):
                    left.unlock_recovery_code(old_code)
                with self.assertRaises(VaultError):
                    left.unlock_password("weak-old-password")
                left.unlock_password(PASSWORD)
                self.assertTrue(left.unlocked)

    def test_a_backup_left_by_an_older_version_is_removed(self):
        # Up to 160.0-0.1 the .bak was the previous file, possibly with a revoked envelope.
        vault, _, _ = self.new_vault()
        vault.save()
        path = self.dir / "vault.json"
        shutil.copy2(path, self.dir / "previous.json")
        vault.save()
        shutil.copy2(self.dir / "previous.json", path.with_suffix(".json.bak"))
        self.assertFalse(Vault.load(path).from_backup)
        self.assertFalse(path.with_suffix(".json.bak").exists())
        vault.save()  # the next save writes the copy again
        self.assertTrue(path.with_suffix(".json.bak").exists())

    def test_envelope_cannot_be_moved_to_another_profile(self):
        a, _, _ = self.new_vault("a.json")
        b, _, _ = self.new_vault("b.json")
        b.meta["envelopes"].append(a.meta["envelopes"][0])  # attacker grafts A's envelope into B
        b.meta["envelopes"].pop(0)
        b.dek = None
        with self.assertRaises(VaultError):
            b.unlock_password(PASSWORD)


# 5. Desafio expirado falha.
class ExpiredChallengeTest(VaultTestCase):
    def setUp(self):
        super().setUp()
        self.phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        self.env = add_phone(vault, self.paired)
        self.vault = self.reopen(vault)

    def test_desktop_refuses_a_late_answer(self):
        c = self.coordinator(self.vault)
        request = c.start_phone(self.env.id, "Work")
        response = self.phone.handle(request)
        self.clock.now += 61
        self.assertEqual(c.receive(response), State.TIMEOUT)
        self.assert_locked(self.vault)

    def test_unanswered_request_times_out(self):
        c = self.coordinator(self.vault)
        c.start_phone(self.env.id, "Work")
        self.clock.now += 30
        self.assertEqual(c.tick(), State.WAITING_FOR_PHONE)
        self.clock.now += 31
        self.assertEqual(c.tick(), State.TIMEOUT)
        self.assertEqual([m["method"] for m in c.alternatives], ["password", "phone"])  # retry or switch

    def test_phone_refuses_an_old_request(self):
        request = self.coordinator(self.vault).start_phone(self.env.id, "Work")
        self.clock.now += 60 + 121
        with self.assertRaises(PhoneRejected) as ctx:
            self.phone.handle(request)
        self.assertEqual(ctx.exception.code, "expired")

    def test_pairing_invite_expires(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        hello = ReferencePhone("Late", self.clock).scan(pairing.invite())
        self.clock.now += 301
        with self.assertRaises(ProtocolError) as ctx:
            pairing.on_hello(hello)
        self.assertEqual(ctx.exception.code, "expired")


# 6. Resposta repetida falha.
class ReplayTest(VaultTestCase):
    def test_response_is_accepted_once(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        vault = self.reopen(vault)
        unlock = PhoneUnlock(self.identity, "Test desktop", self.clock)
        request = unlock.request(vault, env.id, "Work")
        response = phone.handle(request)
        _, kek = unlock.accept(response)
        vault.unlock_kek(env.id, kek)
        vault.lock()
        with self.assertRaises(ProtocolError) as ctx:
            unlock.accept(response)
        self.assertEqual(ctx.exception.code, "replay")
        self.assert_locked(vault)

    def test_old_response_does_not_answer_a_new_request(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        first = c.start_phone(env.id, "Work")
        old = phone.handle(first)
        second = c.start_phone(env.id, "Work")  # replaces the first request
        self.assertEqual(c.receive(old), State.WAITING_FOR_PHONE)
        forged = dict(old, req_id=second["r"]["req_id"])
        self.assertEqual(c.receive(forged), State.WAITING_FOR_PHONE)  # signature covers the request
        self.assert_locked(c.vault)

    def test_phone_refuses_the_same_request_twice(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        request = self.coordinator(vault).start_phone(env.id, "Work")
        phone.handle(request)
        with self.assertRaises(PhoneRejected) as ctx:
            phone.handle(request)
        self.assertEqual(ctx.exception.code, "replay")


# 7. Aparelho não pareado falha.
class UnpairedDeviceTest(VaultTestCase):
    def setUp(self):
        super().setUp()
        self.phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        self.env = add_phone(vault, self.paired)
        self.vault = self.reopen(vault)

    def test_unpaired_phone_cannot_answer(self):
        stranger = ReferencePhone("Stranger", self.clock)
        stranger.desktops = dict(self.phone.desktops)  # knows the desktop, but is not in the envelope
        c = self.coordinator(self.vault)
        request = c.start_phone(self.env.id, "Work")
        redirected = {"r": dict(request["r"], phone_id=stranger.phone_id), "sig": request["sig"]}
        with self.assertRaises(PhoneRejected) as ctx:
            stranger.handle(redirected)
        self.assertEqual(ctx.exception.code, "bad-signature")  # the desktop signed another phone id
        real = self.phone.handle(c.start_phone(self.env.id, "Work"))
        stranger_answer = dict(real, phone_id=stranger.phone_id)
        self.assertEqual(c.receive(stranger_answer), State.WAITING_FOR_PHONE)  # ignored, cannot cancel
        self.assert_locked(self.vault)
        self.assertEqual(c.receive(real), State.UNLOCKED)  # the paired phone still gets through

    def test_phone_ignores_unpaired_desktop(self):
        other = DesktopIdentity.generate()
        vault, _, _ = self.new_vault("other.json")
        env = add_phone(vault, replace(self.paired, dsig_pk=other.sig_pk))  # an envelope that desktop could make
        request = PhoneUnlock(other, "Unknown desktop", self.clock).request(vault, env.id, "Work")
        with self.assertRaises(PhoneRejected) as ctx:
            self.phone.handle(request)
        self.assertEqual(ctx.exception.code, "unpaired-desktop")

    def test_revoked_phone_cannot_unlock(self):
        self.vault.unlock_password(PASSWORD)
        self.assertEqual(remove_phone(self.vault, self.phone.phone_id), 1)
        vault = self.reopen(self.vault)
        c = self.coordinator(vault)
        self.assertIsNone(c.start_phone(self.env.id, "Work"))
        self.assertEqual(c.error, "unpaired")
        self.assertEqual(vault.envelopes("phone"), [])


# Audit V3 (2026-11-10): one phone paired with two desktops. Desktop A has a copy of desktop B's
# vault.json and asks the phone for B's profile under harmless names.
class DesktopBindingTest(VaultTestCase):
    def setUp(self):
        super().setUp()
        self.phone = self.pair_phone()  # paired with self.identity: desktop B, the victim
        self.attacker = DesktopIdentity.generate()
        pair(Pairing(self.attacker, "Desktop A", clock=self.clock), self.phone)
        vault, self.dek, _ = self.new_vault()
        self.env = add_phone(vault, self.paired)
        self.victim = self.reopen(vault)

    def forged_request(self, name: str = "Desktop B", expiry: int | None = None) -> dict:
        """What desktop A can sign: B's envelope fields from the copied vault.json, its own desktop id."""
        part = self.env.data
        request = {
            "v": 1,
            "req_id": b64e(os.urandom(16)),
            "op": "unlock-profile",
            "profile_id": self.victim.profile_id,
            "profile_name": "Banking",
            "desktop_id": self.attacker.desktop_id,
            "desktop_name": name,
            "envelope_id": self.env.id,
            "phone_id": part["phone_id"],
            "eph_pk": part["eph_pk"],
            "s_pk": b64e(self.session_pk),
            "expiry": int(self.clock()) + 60 if expiry is None else expiry,
        }
        return {"r": request, "sig": b64e(sodium.sign(self.attacker.sig_sk, request_signing_input(request)))}

    def test_another_desktops_request_yields_a_key_that_opens_nothing(self):
        session_sk, self.session_pk = sodium.x25519_keypair()
        forged = self.forged_request()
        response = self.phone.handle(forged)  # the phone answers its paired desktop A ...
        shared = sodium.x25519(session_sk, self.phone.kx_pk)
        rk = response_key(shared, sodium.hash32(canonical(forged["r"])))
        kek = unseal(rk, response["box"], forged["r"]["req_id"].encode())
        with self.assertRaises(VaultError):  # ... but with A's key in the derivation: B's envelope stays shut
            self.victim.unlock_kek(self.env.id, kek)
        self.assert_locked(self.victim)

    def test_the_phone_shows_the_name_it_paired_with(self):
        _, self.session_pk = sodium.x25519_keypair()
        shown = self.phone.check(self.forged_request(name="Desktop B"))
        self.assertEqual(shown["desktop_name"], "Desktop A")  # its own record, not the request's words

    def test_a_request_valid_for_too_long_is_refused(self):
        _, self.session_pk = sodium.x25519_keypair()
        with self.assertRaises(PhoneRejected) as ctx:
            self.phone.handle(self.forged_request(expiry=int(self.clock()) + 3600))
        self.assertEqual(ctx.exception.code, "bad-expiry")

    def test_the_desktop_will_not_ask_for_another_desktops_envelope(self):
        with self.assertRaises(ProtocolError) as ctx:
            PhoneUnlock(self.attacker, "Desktop A", self.clock).request(self.victim, self.env.id, "Banking")
        self.assertEqual(ctx.exception.code, "phone-needs-pairing")

    def test_the_rightful_desktop_still_unlocks(self):
        c = self.coordinator(self.victim)
        self.assertEqual(c.receive(self.phone.handle(c.start_phone(self.env.id, "Banking"))), State.UNLOCKED)
        self.assertEqual(bytes(self.victim.dek), self.dek)

    def test_an_envelope_for_a_phone_without_a_desktop_is_refused(self):
        with self.assertRaises(ProtocolError) as ctx:
            add_phone(self.victim, replace(self.paired, dsig_pk=b""))
        self.assertEqual(ctx.exception.code, "phone-needs-pairing")


# 8. Pareamento substituído falha.
class SubstitutedPairingTest(VaultTestCase):
    def test_substituted_desktop_key_in_the_qr(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        qr = pairing.invite()
        _, attacker_pk = sodium.ed25519_keypair()
        phone = ReferencePhone("Phone", self.clock)
        accept = pairing.on_hello(phone.scan(dict(qr, d=b64e(attacker_pk))))
        with self.assertRaises(PhoneRejected) as ctx:
            phone.on_accept(accept)
        self.assertEqual(ctx.exception.code, "bad-message")  # the desktop key is in the transcript
        self.assertEqual(phone.desktops, {})

    def test_substituted_exchange_key_in_the_qr(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        _, attacker_pk = sodium.x25519_keypair()
        hello = ReferencePhone("Phone", self.clock).scan(dict(pairing.invite(), k=b64e(attacker_pk)))
        with self.assertRaises(ProtocolError) as ctx:
            pairing.on_hello(hello)
        self.assertEqual(ctx.exception.code, "bad-message")
        self.assertEqual(pairing.state, "cancelled")

    def test_hello_without_the_qr_secret(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        guessed = dict(pairing.invite(), s=b64e(sodium.random_bytes(32)))
        with self.assertRaises(ProtocolError):
            pairing.on_hello(ReferencePhone("Guess", self.clock).scan(guessed))

    def test_copied_qr_raced_by_another_device(self):
        """Someone photographs the QR and answers first: the user's phone never shows the
        desktop's digits, the user says no, and nothing is stored."""
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        qr = pairing.invite()
        victim, attacker = ReferencePhone("Victim", self.clock), ReferencePhone("Attacker", self.clock)
        victim_hello = victim.scan(qr)
        attacker_digits = attacker.on_accept(pairing.on_hello(attacker.scan(qr)))
        self.assertEqual(attacker_digits, pairing.sas)  # only the attacker's screen matches
        with self.assertRaises(ProtocolError) as ctx:
            pairing.complete(attacker.confirm(), user_confirmed_sas=False)
        self.assertEqual(ctx.exception.code, "sas-mismatch")
        self.assertEqual(pairing.state, "cancelled")
        with self.assertRaises(ProtocolError):
            pairing.on_hello(victim_hello)

    def test_second_hello_on_the_same_invite(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        qr = pairing.invite()
        pairing.on_hello(ReferencePhone("One", self.clock).scan(qr))
        with self.assertRaises(ProtocolError) as ctx:
            pairing.on_hello(ReferencePhone("Two", self.clock).scan(qr))
        self.assertEqual(ctx.exception.code, "bad-state")

    def test_confirmation_signed_by_another_key(self):
        pairing = Pairing(self.identity, "Test desktop", clock=self.clock)
        phone = ReferencePhone("Phone", self.clock)
        phone.on_accept(pairing.on_hello(phone.scan(pairing.invite())))
        phone.sig_sk, _ = sodium.ed25519_keypair()  # a different key signs the confirmation
        with self.assertRaises(ProtocolError) as ctx:
            pairing.complete(phone.confirm(), True)
        self.assertEqual(ctx.exception.code, "bad-signature")


# 9. Cancelamento falha de modo seguro.
class CancelTest(VaultTestCase):
    def test_answer_after_cancel_is_useless(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        vault = self.reopen(vault)
        c = self.coordinator(vault)
        request = c.start_phone(env.id, "Work")
        session_key = c.phone.pending[request["r"]["req_id"]].session_sk
        self.assertEqual(c.cancel(), State.CANCELLED)
        self.assertEqual(bytes(session_key), bytes(32))  # wiped
        self.assertEqual(c.receive(phone.handle(request)), State.CANCELLED)
        with self.assertRaises(ProtocolError) as ctx:
            c.phone.accept({"req_id": request["r"]["req_id"]})
        self.assertEqual(ctx.exception.code, "replay")
        self.assert_locked(vault)

    def test_user_declines_on_the_phone(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        request = c.start_phone(env.id, "Work")
        self.assertEqual(c.receive(phone.handle(request, approve=False)), State.CANCELLED)
        self.assertEqual(c.error, "declined")
        self.assert_locked(c.vault)


# 10. Rede indisponível oferece método alternativo.
class NetworkUnavailableTest(VaultTestCase):
    def test_alternatives_are_offered_not_used(self):
        self.pair_phone()
        vault, _, _ = self.new_vault(recovery=True)
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault), Loopback(reachable=False))
        self.assertIsNone(c.start_phone(env.id, "Work"))
        self.assertEqual(c.state, State.DEVICE_UNAVAILABLE)
        self.assertEqual(sorted(m["method"] for m in c.alternatives), ["password", "recovery-code"])
        self.assert_locked(c.vault)  # nothing was tried on the user's behalf
        self.assertEqual(c.unlock_password(PASSWORD), State.UNLOCKED)

    def test_only_recovery_left(self):
        self.pair_phone()
        vault, _, _ = self.new_vault(password=False, recovery=True)
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault), Loopback(reachable=False))
        c.start_phone(env.id, "Work")
        self.assertEqual(c.state, State.RECOVERY_REQUIRED)
        self.assertEqual([m["method"] for m in c.alternatives], ["recovery-code"])


# 11. Segundo aparelho recupera perfil.
class SecondPhoneTest(VaultTestCase):
    def test_second_phone_after_losing_the_first(self):
        first = self.pair_phone("First")
        first_paired = self.paired
        second = self.pair_phone("Second")
        vault, dek, _ = self.new_vault()
        add_phone(vault, first_paired)
        env2 = add_phone(vault, self.paired)
        remove_phone(vault, first.phone_id)  # first phone lost
        vault = self.reopen(vault)
        c = self.coordinator(vault)
        self.assertEqual(c.receive(second.handle(c.start_phone(env2.id, "Work"))), State.UNLOCKED)
        self.assertEqual(bytes(vault.dek), dek)
        self.assertEqual([e.label for e in vault.envelopes("phone")], ["Second"])


# 12. Recovery code funciona.
class RecoveryCodeTest(VaultTestCase):
    def test_code_unlocks_in_any_reasonable_spelling(self):
        vault, dek, code = self.new_vault(recovery=True)
        vault = self.reopen(vault)
        self.assertRegex(code, r"^([0-9A-HJKMNP-TV-Z]{4}-){6}[0-9A-HJKMNP-TV-Z]{4}$")
        vault.unlock_recovery_code(code.lower().replace("-", " ").replace("0", "o"))
        self.assertEqual(bytes(vault.dek), dek)

    def test_replaced_code_no_longer_works(self):
        vault, _, old = self.new_vault(recovery=True)
        new = vault.replace_recovery_code(FAST)
        vault = self.reopen(vault)
        vault.unlock_recovery_code(new)  # the new code, typed back, confirms the replacement
        vault.confirm_recovery_code()
        vault = self.reopen(vault)
        with self.assertRaises(VaultError):
            vault.unlock_recovery_code(old)
        vault.unlock_recovery_code(new)
        self.assertEqual(len(vault.envelopes("recovery-code")), 1)
        self.assertIsNone(vault.pending_recovery_code())

    # #187: the new code exists only on the screen that shows it. Until it is typed back, the old
    # code still opens the profile, so a replacement cut short never leaves only an unseen code.

    def test_the_old_code_works_until_the_new_one_is_confirmed(self):
        vault, dek, old = self.new_vault(recovery=True)
        new = vault.replace_recovery_code(FAST)
        for code in (old, new):
            vault = self.reopen(vault)
            with self.subTest(code="old" if code == old else "new"):
                vault.unlock_recovery_code(code)
                self.assertEqual(bytes(vault.dek), dek)

    def test_only_the_new_code_confirms_a_replacement(self):
        vault, _, old = self.new_vault(recovery=True)
        vault.replace_recovery_code(FAST)
        for unlock in (lambda v: v.unlock_recovery_code(old), lambda v: v.unlock_password(PASSWORD)):
            vault = self.reopen(vault)
            unlock(vault)
            with self.assertRaises(VaultError) as ctx:
                vault.confirm_recovery_code()
            self.assertEqual(ctx.exception.code, "wrong-secret")
            self.assertEqual(len(vault.envelopes("recovery-code")), 2)

    def test_an_unconfirmed_replacement_is_finished_by_an_unlock_with_the_new_code(self):
        vault, _, old = self.new_vault(recovery=True)
        new = vault.replace_recovery_code(FAST)
        vault = self.reopen(vault)
        vault.unlock_recovery_code(new)
        self.assertEqual(vault.settle_recovery_code(), "finished")
        vault = self.reopen(vault)
        with self.assertRaises(VaultError):
            vault.unlock_recovery_code(old)
        vault.unlock_recovery_code(new)

    def test_an_unconfirmed_replacement_is_undone_by_any_other_unlock(self):
        for unlock in ("old", "password"):
            with self.subTest(unlock=unlock):
                vault, _, old = self.new_vault(name=f"{unlock}.json", recovery=True)
                new = vault.replace_recovery_code(FAST)
                vault = self.reopen(vault)
                vault.unlock_recovery_code(old) if unlock == "old" else vault.unlock_password(PASSWORD)
                self.assertEqual(vault.settle_recovery_code(), "undone")
                vault = self.reopen(vault)
                with self.assertRaises(VaultError):
                    vault.unlock_recovery_code(new)
                vault.unlock_recovery_code(old)
                self.assertIsNone(vault.settle_recovery_code())  # nothing left to settle

    def test_a_second_replacement_drops_the_unconfirmed_code_and_keeps_the_confirmed_one(self):
        vault, _, old = self.new_vault(recovery=True)
        first = vault.replace_recovery_code(FAST)
        second = vault.replace_recovery_code(FAST)
        self.assertEqual(len(vault.envelopes("recovery-code")), 2)
        vault = self.reopen(vault)
        with self.assertRaises(VaultError):
            vault.unlock_recovery_code(first)
        vault.unlock_recovery_code(old)
        vault = self.reopen(vault)
        vault.unlock_recovery_code(second)
        vault.confirm_recovery_code()
        vault = self.reopen(vault)
        with self.assertRaises(VaultError):
            vault.unlock_recovery_code(old)

    def test_removing_a_code_of_a_replacement_ends_it(self):
        vault, _, old = self.new_vault(recovery=True)
        old_id = vault.envelopes("recovery-code")[0].id
        vault.replace_recovery_code(FAST)
        new_id = vault.pending_recovery_code()["new"]
        vault.remove(new_id)
        self.assertIsNone(vault.pending_recovery_code())
        self.assertEqual([e.id for e in vault.envelopes("recovery-code")], [old_id])
        vault.replace_recovery_code(FAST)
        vault.remove(old_id)  # the new code is then the only one: nothing is left to replace
        self.assertNotIn("pending_recovery", vault.meta)
        vault = self.reopen(vault)
        with self.assertRaises(VaultError):
            vault.unlock_recovery_code(old)

    def test_codes_are_unique_and_high_entropy(self):
        from nulavio_launcher.vault.core import RECOVERY_GROUP_LEN, RECOVERY_GROUPS, new_recovery_code

        self.assertGreaterEqual(RECOVERY_GROUPS * RECOVERY_GROUP_LEN * 5, 128)
        self.assertEqual(len({new_recovery_code() for _ in range(200)}), 200)


# 13. PIN/biometria indisponíveis têm tratamento claro.
class BiometricUnavailableTest(VaultTestCase):
    def check(self, biometric: str, expected_state: State, expected_error: str):
        phone = self.pair_phone()
        phone.biometric = biometric
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        self.assertEqual(c.receive(phone.handle(c.start_phone(env.id, "Work"))), expected_state)
        self.assertEqual(c.error, expected_error)
        self.assertEqual([m["method"] for m in c.alternatives], ["password", "phone"])
        self.assert_locked(c.vault)

    def test_biometrics_not_set_up(self):
        self.check("unavailable", State.DEVICE_UNAVAILABLE, "biometric-unavailable")

    def test_biometrics_locked_out(self):
        self.check("locked", State.DEVICE_UNAVAILABLE, "device-locked")

    def test_unknown_phone_error_is_not_trusted(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        request = c.start_phone(env.id, "Work")
        response = phone._signed(request["r"], sodium.hash32(canonical(request["r"])), {"error": "<script>"}, error=True)
        self.assertEqual(c.receive(response), State.ERROR)
        self.assertEqual(c.error, "phone-error")


# 14. Dados permanecem recuperáveis após atualização.
class UpgradeTest(VaultTestCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(FIXTURE, self.dir / "fixture")
        self.secrets = json.loads((FIXTURE / "test-secrets.json").read_text())

    def test_v1_fixture_unlocks_with_every_method(self):
        path = self.dir / "fixture" / "vault.json"
        vault = Vault.load(path)
        vault.unlock_password(self.secrets["password"])
        self.assertEqual(b64e(sodium.hash32(bytes(vault.dek))), self.secrets["dek_hash"])
        self.assertFalse(vault.tampered)
        vault.lock()
        vault.unlock_recovery_code(self.secrets["recovery_code"])
        self.assertEqual(b64e(sodium.hash32(bytes(vault.dek))), self.secrets["dek_hash"])
        vault.lock()
        # Its phone envelope predates desktop binding (audit V3): the phone could no longer open it, so the
        # desktop asks to pair the phone again instead of sending a request.
        identity = DesktopIdentity.load_or_create(self.dir / "fixture" / "desktop.json")
        c = Coordinator(vault, phone=PhoneUnlock(identity, "Fixture desktop", self.clock), transport=Loopback(), clock=self.clock)
        env = vault.envelopes("phone")[0]
        self.assertIsNone(c.start_phone(env.id, "Fixture"))
        self.assertEqual(c.error, "phone-needs-pairing")
        self.assert_locked(vault)

    def test_newer_format_is_refused_not_downgraded(self):
        path = self.dir / "fixture" / "vault.json"
        shutil.copy2(path, path.with_suffix(".json.bak"))
        meta = json.loads(path.read_text())
        meta["version"] = 2
        path.write_text(json.dumps(meta))
        with self.assertRaises(VaultError) as ctx:
            Vault.load(path)
        self.assertEqual(ctx.exception.code, "unsupported-version")

    def test_damaged_file_falls_back_to_backup(self):
        path = self.dir / "fixture" / "vault.json"
        shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text('{"format": "nulavio-vault", "version": 1, "suite": "nv1", "profile_id": "x"')  # cut short
        vault = Vault.load(path)
        self.assertTrue(vault.from_backup)
        vault.unlock_password(self.secrets["password"])
        self.assertTrue(vault.unlocked)

    def test_real_password_parameters(self):
        vault = Vault.create(self.dir / "defaults.json")
        env = vault.add_password(PASSWORD)
        self.assertEqual((env.data["ops"], env.data["mem"]), (3, 256 * 1024 * 1024))
        vault = self.reopen(vault)
        vault.unlock_password(PASSWORD)
        self.assertTrue(vault.unlocked)


# 15. Bloqueio encerra corretamente acesso sensível.
class LockTest(VaultTestCase):
    def test_lock_wipes_the_key(self):
        vault = self.reopen(self.new_vault()[0])
        c = Coordinator(vault)
        c.unlock_password(PASSWORD)
        buffer = vault.dek
        self.assertNotEqual(bytes(buffer), bytes(32))
        self.assertEqual(c.lock(), State.IDLE)
        self.assertEqual(bytes(buffer), bytes(32))
        self.assert_locked(vault)
        for change in (vault.save, lambda: vault.add_password(PASSWORD, FAST), lambda: vault.add_recovery_code(FAST)):
            with self.assertRaises(VaultError) as ctx:
                change()
            self.assertEqual(ctx.exception.code, "locked")

    def test_lock_while_waiting_cancels_the_request(self):
        phone = self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        c = self.coordinator(self.reopen(vault))
        request = c.start_phone(env.id, "Work")
        c.lock()
        self.assertEqual(c.receive(phone.handle(request)), State.IDLE)
        self.assert_locked(c.vault)


# 16. Falha de processo não grava segredos em texto claro.
class CrashTest(VaultTestCase):
    def test_crash_during_save_leaves_no_secret(self):
        vault, dek, _ = self.new_vault()
        vault.save()
        self.pair_phone()
        add_phone(vault, self.paired)
        power_loss = mock.patch("nulavio_launcher.vault.core.os.replace", side_effect=OSError("power loss"))
        with power_loss, self.assertRaises(OSError):
            vault.save()
        leftovers = [p for p in self.dir.iterdir() if p.is_file()]
        for path in leftovers:
            self.assertNotIn(dek, path.read_bytes())
            self.assertNotIn(b64e(dek).encode(), path.read_bytes())
        reloaded = Vault.load(self.dir / "vault.json")
        reloaded.unlock_password(PASSWORD)
        self.assertEqual(bytes(reloaded.dek), dek)

    def test_crash_between_writes_keeps_a_valid_file(self):
        # save() writes the .bak copy, then vault.json: a crash at either step leaves
        # a vault.json that opens (the previous one: the change did not happen).
        for crash_at in (1, 2):
            with self.subTest(crash_at=crash_at):
                for name in ("vault.json", "vault.json.bak"):
                    (self.dir / name).unlink(missing_ok=True)
                vault, dek, _ = self.new_vault()
                vault.save()
                real_replace = os.replace
                calls = []

                def replace(src, dst, calls=calls, crash_at=crash_at, real_replace=real_replace):
                    calls.append(dst)
                    if len(calls) == crash_at:
                        raise OSError("killed")
                    real_replace(src, dst)

                with mock.patch("nulavio_launcher.vault.core.os.replace", side_effect=replace), self.assertRaises(OSError):
                    vault.save()
                reloaded = Vault.load(self.dir / "vault.json")
                self.assertFalse(reloaded.from_backup)
                self.assertEqual(reloaded.meta["generation"], 1)
                reloaded.unlock_password(PASSWORD)
                self.assertEqual(bytes(reloaded.dek), dek)
                # And when vault.json is damaged, the copy opens too.
                (self.dir / "vault.json").write_text("{")
                self.assertTrue(Vault.load(self.dir / "vault.json").from_backup)

    def test_killed_process_while_unlocked(self):
        vault, dek, _ = self.new_vault()
        vault.save()
        script = textwrap.dedent(f"""
            import os, signal, sys
            sys.path.insert(0, {str(ROOT / "launcher")!r})
            from nulavio_launcher.vault.core import Vault
            v = Vault.load(__import__("pathlib").Path({str(self.dir / "vault.json")!r}))
            v.unlock_password({PASSWORD!r})
            v.add_recovery_code({{"ops": 1, "mem": 8388608}})
            v.save()
            os.kill(os.getpid(), signal.SIGKILL)
        """)
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            capture_output=True,
            timeout=60,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(self.dir)},
        )
        self.assertLess(result.returncode, 0)
        for path in self.dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(dek, path.read_bytes())
                self.assertNotIn(b64e(dek).encode(), path.read_bytes())


# Threat model U-T18: tampering and downgrade.
class TamperTest(VaultTestCase):
    def test_metadata_change_is_detected_and_blocks_unlock(self):
        vault, _, _ = self.new_vault(recovery=True)
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["policy"] = {"auto_lock_minutes": 0, "note": "weakened"}
        vault.path.write_text(json.dumps(meta))
        vault.lock()
        tampered = Vault.load(vault.path)
        c = Coordinator(tampered)
        self.assertEqual(c.unlock_password(PASSWORD), State.ERROR)
        self.assertEqual(c.error, "metadata-tampered")
        self.assert_locked(tampered)
        repaired = Coordinator(tampered, repair_metadata=True)
        self.assertEqual(repaired.unlock_password(PASSWORD), State.UNLOCKED)
        tampered.lock()
        self.assertEqual(Coordinator(Vault.load(vault.path)).unlock_password(PASSWORD), State.UNLOCKED)

    def test_a_method_change_does_not_sign_a_tampered_file_again(self):
        # Audit V4: re-inserting a revoked envelope, then any method change, made it valid again.
        vault, _, _ = self.new_vault(recovery=True)
        weak = vault.add_password("weak-old-password", FAST, label="old")
        vault.save()
        injected = json.loads(vault.path.read_text())["envelopes"]
        vault.remove(weak.id)
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["envelopes"] = injected
        vault.path.write_text(json.dumps(meta))
        vault.lock()
        tampered = Vault.load(vault.path)
        tampered.unlock_password(PASSWORD)  # the CLI and the Settings page unlock like this before a change
        self.assertTrue(tampered.tampered)
        tampered.add_password("another-password", FAST)
        with self.assertRaises(VaultError) as ctx:
            tampered.save()
        self.assertEqual(ctx.exception.code, "metadata-tampered")
        tampered.lock()
        self.assertTrue(Vault.load(vault.path).meta["envelopes"] == injected)  # nothing was written
        again = Vault.load(vault.path)
        again.unlock_password("weak-old-password")
        self.assertTrue(again.tampered)  # still flagged: the injected envelope never became valid

    def test_a_tampered_vault_is_refused_before_the_keyring_is_touched(self):
        # Review of #44: remove-method on an os-keyring envelope cleared the system keyring
        # before save() refused the tampered file, so that method was lost for good.
        from nulavio_launcher.vault import cli as vault_cli

        vault, _, _ = self.new_vault(recovery=True)
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["policy"] = {"note": "changed outside Nulavio"}
        vault.path.write_text(json.dumps(meta))
        vault.lock()
        box = mock.Mock(load_vault=lambda: Vault.load(vault.path))
        request = {"op": "remove-method", "path": str(self.dir / "profile"), "current": PASSWORD, "envelope": "any"}
        with (
            mock.patch.object(vault_cli.profiles, "container", return_value=box),
            mock.patch.object(vault_cli, "remove_os_keyring", side_effect=AssertionError("keyring touched")),
            mock.patch.object(vault_cli, "keyring", side_effect=AssertionError("keyring touched")),
            self.assertRaises(VaultError) as ctx,
        ):
            vault_cli.api_request(request)
        self.assertEqual(ctx.exception.code, "metadata-tampered")

    def test_removed_envelope_is_detected(self):
        vault, _, _ = self.new_vault(recovery=True)
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["envelopes"] = [e for e in meta["envelopes"] if e["method"] != "recovery-code"]
        vault.path.write_text(json.dumps(meta))
        c = Coordinator(Vault.load(vault.path))
        self.assertEqual(c.unlock_password(PASSWORD), State.ERROR)
        self.assertEqual(c.error, "metadata-tampered")

    def test_weaker_kdf_parameters_do_not_open(self):
        vault, _, _ = self.new_vault()
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["envelopes"][0]["data"]["ops"] = 2
        vault.path.write_text(json.dumps(meta))
        with self.assertRaises(VaultError) as ctx:
            Vault.load(vault.path).unlock_password(PASSWORD)
        self.assertEqual(ctx.exception.code, "wrong-secret")

    def test_damaged_envelopes_fail_cleanly_and_fast(self):
        self.pair_phone()
        vault, _, _ = self.new_vault()
        env = add_phone(vault, self.paired)
        vault.save()
        meta = json.loads(vault.path.read_text())
        meta["envelopes"][0]["data"]["mem"] = 4 * 1024**4  # 4 TiB: must be refused before any allocation
        meta["envelopes"][1]["data"]["psig_pk"] = "not base64!"
        vault.path.write_text(json.dumps(meta))
        damaged = Vault.load(vault.path)
        c = self.coordinator(damaged)
        self.assertEqual(c.unlock_password(PASSWORD), State.ERROR)
        self.assertEqual(c.error, "damaged-envelope")
        self.assertIsNone(c.start_phone(env.id, "Work"))
        self.assertEqual(c.error, "damaged-envelope")
        del meta["envelopes"][0]["data"]["salt"]
        vault.path.write_text(json.dumps(meta))
        with self.assertRaises(VaultError) as ctx:
            Vault.load(vault.path).unlock_password(PASSWORD)
        self.assertEqual(ctx.exception.code, "damaged-envelope")
        self.assert_locked(damaged)

    def test_generation_counts_saves(self):
        vault, _, _ = self.new_vault()
        vault.save()
        vault.save()
        self.assertEqual(json.loads(vault.path.read_text())["generation"], 2)


# Combined policy (password + phone) is cryptographic, not a UI rule.
class CombinedPolicyTest(VaultTestCase):
    def setUp(self):
        super().setUp()
        self.phone = self.pair_phone()
        vault = Vault.create(self.dir / "vault.json")
        self.dek = bytes(vault.dek)
        self.env = add_password_and_phone(vault, PASSWORD, self.paired, FAST)
        self.vault = self.reopen(vault)

    def test_needs_both(self):
        c = self.coordinator(self.vault)
        request = c.start_phone(self.env.id, "Banking", password=PASSWORD)
        self.assertEqual(c.receive(self.phone.handle(request)), State.UNLOCKED)
        self.assertEqual(bytes(self.vault.dek), self.dek)
        self.assertEqual(self.vault.protection_states(), ["password_protected", "phone_key_release_verified"])

    def test_wrong_password_with_the_phone(self):
        c = self.coordinator(self.vault)
        request = c.start_phone(self.env.id, "Banking", password="wrong password")
        self.assertEqual(c.receive(self.phone.handle(request)), State.ERROR)
        self.assert_locked(self.vault)

    def test_one_factor_alone_fails(self):
        with self.assertRaises(VaultError):
            self.vault.unlock_password(PASSWORD)  # no password-only envelope
        c = self.coordinator(self.vault)
        self.assertIsNone(c.start_phone(self.env.id, "Banking"))
        self.assertEqual(c.error, "password-required")
        unlock = PhoneUnlock(self.identity, "Test desktop", self.clock)
        _, phone_kek = unlock.accept(self.phone.handle(unlock.request(self.vault, self.env.id, "Banking")))
        with self.assertRaises(VaultError):
            self.vault.unlock_kek(self.env.id, phone_kek)  # the phone's key alone
        with self.assertRaises(VaultError):
            self.vault.unlock_kek(self.env.id, combined_kek(sodium.random_bytes(32), phone_kek))
        self.assert_locked(self.vault)


# OS keyring provider (secret-tool), threat model U-T2 and UB3.
class KeyringTest(VaultTestCase):
    def test_store_unlock_remove(self):
        keyring = self.fake_keyring()
        vault, dek, _ = self.new_vault()
        env = add_os_keyring(vault, keyring)
        self.assertIn("os_user_protected", vault.protection_states())
        vault = self.reopen(vault)
        c = Coordinator(vault, keyring=keyring)
        self.assertEqual(c.unlock_keyring(), State.UNLOCKED)
        self.assertEqual(bytes(vault.dek), dek)
        remove_os_keyring(vault, keyring, env.id)
        self.assertEqual(json.loads(self.keyring_store.read_text()), [])

    def test_secret_never_on_the_command_line(self):
        keyring = self.fake_keyring()
        vault, _, _ = self.new_vault()
        add_os_keyring(vault, keyring)
        stored = json.loads(self.keyring_store.read_text())[0]["secret"]
        argv = self.keyring_argv.read_text()
        self.assertIn('"store"', argv)
        self.assertNotIn(stored, argv)
        self.assertNotIn(base64.b64decode(stored).hex(), argv)

    def test_missing_secret_tool(self):
        vault, _, _ = self.new_vault()
        with self.assertRaises(VaultError) as ctx:
            add_os_keyring(vault, Keyring(str(self.dir / "absent")))
        self.assertEqual(ctx.exception.code, "keyring-unavailable")


# Threat model U-T15: logs and errors never carry secrets.
class NoSecretsInLogsTest(VaultTestCase):
    def test_full_flow_logs(self):
        phone = self.pair_phone()
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("nulavio.vault")
        handler = Capture(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)
        vault, dek, code = self.new_vault(recovery=True)
        env = add_phone(vault, self.paired)
        vault = self.reopen(vault)
        c = self.coordinator(vault)
        errors = []
        c.unlock_password("wrong guess 123")
        c.unlock_recovery_code(code)
        c.lock()
        c.receive(phone.handle(c.start_phone(env.id, "Work")))
        c.lock()
        for attempt in (lambda: vault.unlock_password("wrong guess 123"), lambda: vault.unlock_recovery_code("nope")):
            try:
                attempt()
            except VaultError as exc:
                errors.append(str(exc))
        text = "\n".join(records + errors)
        self.assertIn("state=unlocked", text)
        for secret in (PASSWORD, "wrong guess 123", code, code.replace("-", ""), dek.hex(), b64e(dek)):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
