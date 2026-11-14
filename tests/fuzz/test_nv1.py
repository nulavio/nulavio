"""Fuzzing the desktop's side of nv1: what a phone (or anyone on the network) sends (#149).

A message the desktop reads is answered with a ProtocolError (or a VaultError), whatever it holds
(the transport, link.Channel.recv, hands on JSON objects only):
never another exception, which would end the pairing or the unlock without a reason the pages know.
The seeds are real messages from the reference phone (tests/lib/phone_reference.py) and the shapes
of the cross-language vectors; Hypothesis then mutates their fields and tries arbitrary JSON.

    python3 -I tests/run.py fuzz test_nv1.py      # needs requirements/fuzz.txt
"""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from nulavio_launcher.vault import sodium
from nulavio_launcher.vault.core import Vault, VaultError
from nulavio_launcher.vault.core import b64d, b64e
from nulavio_launcher.vault.phone import DesktopIdentity, Pairing, PhoneUnlock, add_phone, nkdf, seal_json
from phone_reference import ReferencePhone, pair

if not sodium.available() and os.environ.get("NULAVIO_REQUIRE_SODIUM"):  # the weekly job: a skip is not a run
    raise RuntimeError("libsodium is required (NULAVIO_REQUIRE_SODIUM) but not installed")
EXAMPLES = int(os.environ.get("NULAVIO_FUZZ_EXAMPLES", "300"))
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}  # tests only
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=80),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
B64ISH = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=+/", max_size=120)


class Clock:
    now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def mutate(message: dict, path: list, value) -> dict:
    """The message with the value at `path` (a list of keys into nested dicts) replaced, or the key removed."""
    out = copy.deepcopy(message)
    node = out
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return out
    if isinstance(node, dict):
        if value is ...:
            node.pop(path[-1], None)
        else:
            node[path[-1]] = value
    return out


def expected(call) -> None:
    try:
        call()
    except VaultError:  # ProtocolError is one
        pass


@unittest.skipUnless(sodium.available(), "libsodium is not installed")
class Nv1FuzzTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.identity = DesktopIdentity.generate()

    def hello(self) -> tuple[Pairing, dict]:
        pairing = Pairing(self.identity, "Fuzz desktop", clock=self.clock)
        return pairing, ReferencePhone("Fuzz phone", self.clock).scan(pairing.invite())

    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(path=st.sampled_from([["i"], ["pe"], ["box"], ["box", "n"], ["box", "c"]]), value=JSON | B64ISH | st.just(...))
    def test_a_changed_hello_is_a_protocol_error(self, path, value):
        pairing, hello = self.hello()
        expected(lambda: pairing.on_hello(mutate(hello, path, value)))

    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(message=st.dictionaries(st.text(max_size=8), JSON, max_size=6))
    def test_any_json_object_as_a_hello_is_a_protocol_error(self, message):
        pairing, _ = self.hello()
        expected(lambda: pairing.on_hello(message))

    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(body=JSON | st.fixed_dictionaries({}, optional={"psig": JSON | B64ISH, "pkx": JSON | B64ISH, "name": JSON}))
    @example(body={"psig": "AAAA", "pkx": "AAAA"})
    def test_a_hello_sealed_with_the_right_secret_but_any_body_is_a_protocol_error(self, body):
        """Only someone who scanned the QR code can seal a hello; what they seal is still not trusted."""
        pairing = Pairing(self.identity, "Fuzz desktop", clock=self.clock)
        invite = pairing.invite()
        pe_sk, pe_pk = sodium.x25519_keypair()
        de_pk, secret = b64d(invite["k"]), b64d(invite["s"])
        shared = sodium.x25519(pe_sk, de_pk)
        k1 = nkdf(secret, "pair/k1", shared, invite["i"], de_pk, pe_pk)
        try:
            box = seal_json(k1, body, invite["i"].encode())
        except (TypeError, ValueError):
            return  # not something JSON can carry
        # Not the phone's two 32-byte keys, so it must be refused, not taken (a 3-byte key once went through).
        with self.assertRaises(VaultError):
            pairing.on_hello({"i": invite["i"], "pe": b64e(pe_pk), "box": box})

    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(path=st.sampled_from([["i"], ["box"], ["box", "n"], ["box", "c"]]), value=JSON | B64ISH | st.just(...))
    def test_a_changed_confirmation_is_a_protocol_error(self, path, value):
        pairing = Pairing(self.identity, "Fuzz desktop", clock=self.clock)
        phone = ReferencePhone("Fuzz phone", self.clock)
        hello = phone.scan(pairing.invite())
        phone.on_accept(pairing.on_hello(hello))
        confirm = phone.confirm()
        expected(lambda: pairing.complete(mutate(confirm, path, value), True))

    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        path=st.sampled_from([["req_id"], ["phone_id"], ["sig"], ["box"], ["box", "n"], ["box", "c"], ["error"]]),
        value=JSON | B64ISH | st.just(...),
    )
    def test_a_changed_unlock_answer_is_a_protocol_error(self, path, value):
        phone = ReferencePhone("Fuzz phone", self.clock)
        paired = pair(Pairing(self.identity, "Fuzz desktop", clock=self.clock), phone)
        vault = Vault.create(self.tmp_vault())
        vault.add_password("fuzz password", FAST)
        envelope = add_phone(vault, paired)
        unlock = PhoneUnlock(self.identity, "Fuzz desktop", self.clock)
        answer = phone.handle(unlock.request(vault, envelope.id, "Fuzz"))
        expected(lambda: unlock.accept(mutate(answer, path, value)))

    @settings(max_examples=EXAMPLES, deadline=None)
    @given(message=st.dictionaries(st.text(max_size=8), JSON, max_size=6))
    def test_any_json_object_as_an_unlock_answer_is_a_protocol_error(self, message):
        unlock = PhoneUnlock(self.identity, "Fuzz desktop", self.clock)
        expected(lambda: unlock.accept(message))

    def tmp_vault(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="nulavio-fuzz-"))
        self.addCleanup(shutil.rmtree, folder, True)
        return folder / "vault.json"


if __name__ == "__main__":
    unittest.main()
