"""Reference phone for protocol nv1: the Companion app's side, in Python, for tests.

It follows docs/architecture/vault-and-unlock.md and is the executable spec the
Android app (S11) must match. Keys stay in memory here; on a phone they sit
under a hardware key released by biometrics, which `biometric` simulates.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from nulavio_launcher.vault import sodium
from nulavio_launcher.vault.core import b64d, b64e, canonical
from nulavio_launcher.vault.phone import (
    CLOCK_SKEW,
    PairedPhone,
    ProtocolError,
    desktop_id_for,
    nkdf,
    phone_id_for,
    phone_kek,
    request_signing_input,
    response_key,
    response_signing_input,
    sas_digits,
    seal,
    seal_json,
    transcript,
    unseal_json,
)


class PhoneRejected(Exception):
    """The phone refused a message and sends nothing back."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReferencePhone:
    def __init__(self, name: str = "Test phone", clock: Callable[[], float] = time.time):
        self.name = name
        self.clock = clock
        self.sig_sk, self.sig_pk = sodium.ed25519_keypair()
        self.kx_sk, self.kx_pk = sodium.x25519_keypair()
        self.phone_id = phone_id_for(self.sig_pk)
        self.desktops: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.biometric = "ok"  # "ok", "unavailable", "locked"
        self._pairing: dict | None = None

    def export_state(self) -> dict:
        """Artificial test keys only (fixtures); a real phone never exports them."""
        return {
            "name": self.name,
            "sig_sk": b64e(self.sig_sk),
            "sig_pk": b64e(self.sig_pk),
            "kx_sk": b64e(self.kx_sk),
            "kx_pk": b64e(self.kx_pk),
            "desktops": {k: {"dsig_pk": b64e(v["dsig_pk"]), "name": v["name"]} for k, v in self.desktops.items()},
        }

    @classmethod
    def from_state(cls, state: dict, clock: Callable[[], float] = time.time) -> ReferencePhone:
        phone = cls(state["name"], clock)
        phone.sig_sk, phone.sig_pk = bytearray(b64d(state["sig_sk"])), b64d(state["sig_pk"])
        phone.kx_sk, phone.kx_pk = bytearray(b64d(state["kx_sk"])), b64d(state["kx_pk"])
        phone.phone_id = phone_id_for(phone.sig_pk)
        phone.desktops = {k: {"dsig_pk": b64d(v["dsig_pk"]), "name": v["name"]} for k, v in state["desktops"].items()}
        return phone

    def as_paired(self) -> PairedPhone:
        return PairedPhone(self.phone_id, self.sig_pk, self.kx_pk, self.name)

    # -- pairing -------------------------------------------------------------------

    def scan(self, qr: dict) -> dict:
        if qr.get("v") != 1 or self.clock() > qr["e"]:
            raise PhoneRejected("expired")
        pe_sk, pe_pk = sodium.x25519_keypair()
        de_pk, secret, invite = b64d(qr["k"]), b64d(qr["s"]), qr["i"]
        shared = sodium.x25519(pe_sk, de_pk)
        sodium.memzero(pe_sk)
        k1 = nkdf(secret, "pair/k1", shared, invite, de_pk, pe_pk)
        box = seal_json(k1, {"psig": b64e(self.sig_pk), "pkx": b64e(self.kx_pk), "name": self.name}, invite.encode())
        self._pairing = {"qr": qr, "pe_pk": pe_pk, "shared": shared, "secret": secret}
        return {"i": invite, "pe": b64e(pe_pk), "box": box}

    def on_accept(self, msg: dict) -> str:
        """Check the desktop's signature against the key in the QR; return the 6 digits to show."""
        p = self._pairing
        qr = p["qr"]
        dsig_pk = b64d(qr["d"])
        t = transcript(qr["i"], b64d(qr["k"]), p["pe_pk"], dsig_pk, self.sig_pk, self.kx_pk, self.name)
        try:
            body = unseal_json(nkdf(p["secret"], "pair/k2", p["shared"], t), msg["box"], qr["i"].encode())
        except ProtocolError:
            self._pairing = None
            raise PhoneRejected("bad-message") from None  # the transcript differs: keys were swapped
        if not sodium.verify(dsig_pk, b"nv1/pair/desktop" + t, b64d(body["sig"])):
            self._pairing = None
            raise PhoneRejected("bad-signature")
        p.update(t=t, dkx=b64d(body["dkx"]), desktop_name=body["name"], dsig_pk=dsig_pk)
        return sas_digits(p["shared"], t)

    def confirm(self) -> dict:
        """The user said the digits match: remember the desktop and send the confirmation."""
        p, self._pairing = self._pairing, None
        sig = sodium.sign(self.sig_sk, b"nv1/pair/phone" + p["t"])
        self.desktops[desktop_id_for(p["dsig_pk"])] = {"dsig_pk": p["dsig_pk"], "name": p["desktop_name"]}
        k3 = nkdf(p["secret"], "pair/k3", p["shared"], p["t"])
        return {"i": p["qr"]["i"], "box": seal_json(k3, {"sig": b64e(sig)}, p["qr"]["i"].encode())}

    # -- unlock --------------------------------------------------------------------

    def handle(self, signed: dict, approve: bool = True) -> dict:
        r = signed["r"]
        desktop = self.desktops.get(r.get("desktop_id"))
        if desktop is None:
            raise PhoneRejected("unpaired-desktop")
        if not sodium.verify(desktop["dsig_pk"], request_signing_input(r), b64d(signed["sig"])):
            raise PhoneRejected("bad-signature")
        if self.clock() > r["expiry"] + CLOCK_SKEW:
            raise PhoneRejected("expired")
        if r["req_id"] in self.seen:
            raise PhoneRejected("replay")
        if r.get("phone_id") != self.phone_id or r.get("op") != "unlock-profile":
            raise PhoneRejected("not-for-this-phone")
        self.seen.add(r["req_id"])
        request_hash = sodium.hash32(canonical(r))
        if self.biometric != "ok" or not approve:
            code = (
                "declined"
                if self.biometric == "ok"
                else {"unavailable": "biometric-unavailable"}.get(self.biometric, "device-locked")
            )
            return self._signed(r, request_hash, {"error": code}, error=True)
        z = sodium.x25519(self.kx_sk, b64d(r["eph_pk"]))
        kek = phone_kek(z, r["profile_id"], r["envelope_id"], self.phone_id, b64d(r["eph_pk"]))
        shared = sodium.x25519(self.kx_sk, b64d(r["s_pk"]))
        rk = response_key(shared, request_hash)
        box = seal(rk, kek, r["req_id"].encode())
        for buf in (z, kek, shared, rk):
            sodium.memzero(buf)
        return self._signed(r, request_hash, box)

    def _signed(self, r: dict, request_hash: bytes, payload: dict, error: bool = False) -> dict:
        sig = b64e(sodium.sign(self.sig_sk, response_signing_input(request_hash, payload)))
        body = {"error": payload["error"]} if error else {"box": payload}
        return {"req_id": r["req_id"], "phone_id": self.phone_id, "sig": sig, **body}


def pair(desktop_pairing, phone: ReferencePhone, desktop_confirms: bool = True) -> PairedPhone:
    """Run the whole pairing; both sides compare the 6 digits."""
    accept = desktop_pairing.on_hello(phone.scan(desktop_pairing.invite()))
    phone_sas = phone.on_accept(accept)
    assert phone_sas == desktop_pairing.sas, "the 6 digits must match on both screens"
    return desktop_pairing.complete(phone.confirm(), user_confirmed_sas=desktop_confirms)
