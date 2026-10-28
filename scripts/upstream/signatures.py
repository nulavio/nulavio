"""Check a detached OpenPGP signature against a pinned key, one signature at a time.

Used for Mozilla's Firefox releases (verify_firefox_release.py) and Anthropic's
Claude Code releases (verify_claude_code_release.py). The key comes from a
reviewed file in keys/, never from the server that serves the signed file: a
server that can swap the signed file could also swap the key file, for example
to drop a revocation. Every signature in the file must be good, made by one of
the allowed signing keys of the pinned primary key, and neither expired nor
revoked; one bad, unverifiable, expired or revoked signature fails the whole
check, so a valid signature cannot vouch for an invalid one next to it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

KEYS = Path(__file__).resolve().parent / "keys"
# gpg status keywords that reject a signature (doc/DETAILS in GnuPG).
REJECT = frozenset({"BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY", "FAILURE"})


class SignatureError(Exception):
    pass


def check_status(status: str, primary: str, signers: Iterable[str]) -> str:
    """The signing key of a gpg --status-fd output in which every signature is acceptable."""
    allowed = {signer.upper() for signer in signers}
    blocks: list[list[list[str]]] = []
    for line in status.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] != "[GNUPG:]":
            continue
        if fields[1] == "NEWSIG" or not blocks:
            blocks.append([])
        if fields[1] != "NEWSIG":
            blocks[-1].append(fields[1:])
    blocks = [block for block in blocks if block]
    if not blocks:
        raise SignatureError("no signature")
    signer = ""
    for block in blocks:
        rejected = REJECT & {fields[0] for fields in block}
        if rejected:
            raise SignatureError(f"gpg rejected a signature ({', '.join(sorted(rejected))})")
        goods = [fields for fields in block if fields[0] == "GOODSIG"]
        valids = [fields for fields in block if fields[0] == "VALIDSIG"]
        if len(goods) != 1 or len(valids) != 1 or len(goods[0]) < 2 or len(valids[0]) < 2:
            raise SignatureError("a signature is not both good and valid")
        signer = valids[0][1].upper()
        key_primary = valids[0][10].upper() if len(valids[0]) > 10 else signer
        if not signer.endswith(goods[0][1].upper()):
            raise SignatureError("gpg's GOODSIG and VALIDSIG name different keys")
        if key_primary != primary.upper():
            raise SignatureError(f"signed by unexpected primary key {key_primary}")
        if signer not in allowed:
            raise SignatureError(f"signed by {signer}, which is not a pinned signing key (scripts/upstream/keys/README.md)")
    return signer


def verify(data: Path, signature: Path, key: Path, primary: str, signers: Iterable[str]) -> str:
    """Verify `signature` over `data` with only `key` imported; return the signing key's fingerprint."""
    with tempfile.TemporaryDirectory(prefix="nulavio-gpg-") as tmp:
        home = Path(tmp) / "gnupg"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(home), "LC_ALL": "C"}
        imported = subprocess.run(["gpg", "--batch", "--quiet", "--import", str(key)], env=env, capture_output=True, check=False)
        if imported.returncode != 0:
            raise SignatureError(f"gpg could not import {key.name}")
        result = subprocess.run(
            ["gpg", "--batch", "--status-fd", "1", "--verify", str(signature), str(data)],
            env=env, capture_output=True, text=True, check=False,
        )  # fmt: skip
    signer = check_status(result.stdout, primary, signers)
    if result.returncode != 0:
        raise SignatureError(f"gpg --verify exited with {result.returncode}")
    return signer
