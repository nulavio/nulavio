#!/usr/bin/env python3
"""Check a rehearsal's manifest.json before anything is signed or published.

    python3 -I scripts/release/release_manifest.py verify <rehearsal-out> [--repo DIR] [--on REF]
    python3 -I scripts/release/release_manifest.py packages <manifest.json> <packages-dir>
    python3 -I scripts/release/release_manifest.py next-release <firefox-version> [--repo DIR] [--also TAG ...]
    python3 -I scripts/release/release_manifest.py not-older <tag> [--repo DIR] [--also TAG ...]
    python3 -I scripts/release/release_manifest.py dnf-primary <repomd.xml>
    python3 -I scripts/release/release_manifest.py dnf-compressed <repomd.xml> <primary.xml.zst>
    python3 -I scripts/release/release_manifest.py dnf-served <repomd.xml> <primary.xml>
    python3 -I scripts/release/release_manifest.py verify-signed <file> <signature> --fingerprint FPR [--key FILE]
    python3 -I scripts/release/release_manifest.py verify-clearsigned <InRelease> <out> --fingerprint FPR [--key FILE]
    python3 -I scripts/release/release_manifest.py apt-packages <Release>
    python3 -I scripts/release/release_manifest.py apt-served <Release> <Packages>

``verify`` refuses a rehearsal that is not fit to publish: not finished, built
from a tree with uncommitted or untracked changes, an engine pin that differs
from the source it built, a listed file missing or with another SHA-256, a base
commit that is not on ``--on`` (default origin/main), a .deb whose version is not
the RPM's, or a release the networking check's record does not cover: at the base
commit, browser/build/networking-check.json is missing, names another Firefox
release or source digest, was read with another mozconfig, variant or patch stack,
or says neither "passed" nor "accepted" with an issue number (#430). On success it
prints JSON: the release tag (``v<version>-<release>`` from
the RPM), the RPMs, the .debs, the portable archives, the SBOMs.

``networking-claim`` prints, as bytes, the claim that the rehearsal's Firefox release
passed the Rust networking reading with the base commit's mozconfig, variant and patch
stack, and with the Rust compiler the manifest says built the release (#472). The
signing job asks for an attestation of exactly those bytes by networking-check.yml on
main before it signs (#455); the record in the repository is not part of it.

``packages`` refuses a packages directory holding any Nulavio RPM or .deb that
the manifest does not list with the same SHA-256. sign_repo.sh and sign_apt_repo.sh
run it when NULAVIO_RELEASE_MANIFEST is set, so only what the rehearsal checked is
signed.

``next-release`` prints the package release to build: one above every revision of
that Firefox version that is tagged, recorded in packaging/release.json or named
with ``--also``. The build job names the versions the bucket's APT and dnf indexes
serve, so a run that uploaded and stopped before its draft (no tag, no draft) does
not hand its revision to the next run (#656), even when only its dnf upload finished
(#723); upload_repo.sh refuses to overwrite a package with other bytes in any case.

``dnf-primary`` prints where the bucket's repomd.xml says the primary metadata is
(``repodata/<sha256>-primary.xml.zst``, nothing else). ``dnf-compressed`` refuses
that file, as downloaded, unless its SHA-256 is the checksum repomd.xml gives: it is
checked before zstd reads it. ``dnf-served`` prints the
highest ``<version>-<release>`` of nulavio that this primary file lists, without the
distribution (``0.3.fc44`` is ``0.3``), once its SHA-256 is the one repomd.xml gives.
They read only UTF-8 XML (whatever it declares) without a DTD or an entity, as
createrepo_c writes it.
Anything else stops it: the build job then fails closed.

``verify-signed`` refuses a file unless its detached signature is good and made by
the release key (site/keys/nulavio-packages.asc, by default) or one of its subkeys:
a throwaway GNUPGHOME holds that key alone, the key file must be the fingerprint given,
and gpg's status lines must show one signature, valid, by that key. The build job runs
it on repomd.xml (repomd.xml.asc, sign_repo.sh) before it reads it (#729).
``verify-clearsigned`` does the same for a cleartext-signed file, the APT InRelease
(sign_apt_repo.sh), and only then writes its text, the Release file, to <out>: one
object, so an upload stopped between Release and Release.gpg cannot pair one run's
text with another run's signature. ``apt-packages`` prints where the Packages file
that Release names is, by its SHA-256 (``by-hash/``: never replaced, while the plain
Packages object is replaced before InRelease). ``apt-served`` prints the
highest ``<version>-<release>`` of nulavio in a Packages file, once its SHA-256 and
size are the ones that Release file gives.

``not-older`` refuses a release when a newer one is tagged, recorded in
packaging/release.json or named with ``--also``. The publish job runs it before
the upload with every GitHub release (drafts included) and the version the
bucket's APT index serves: a re-run of an older run's publish job would otherwise
put that run's signed metadata back in the bucket.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.parsers import expat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EMPTY_DIFF = hashlib.sha256(b"").hexdigest()
# The portable archive of the same tree (GitHub release asset; the Flatpak is built from it).
ARCHIVE_SUFFIX = ".linux-x86_64.tar.xz"
RPM = re.compile(r"^nulavio-(?P<version>\d+(?:\.\d+)+)-(?P<release>[0-9.]+)\.[a-z0-9_]+\.x86_64\.rpm$")
DEB = re.compile(r"^nulavio_(?P<version>\d+(?:\.\d+)+)-(?P<release>[0-9.]+)_amd64\.deb$")
COMMIT = re.compile(r"[0-9a-f]{40}")
RELEASE_TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)+)-([0-9]+(?:\.[0-9]+)*)")
# The dnf repository's metadata (createrepo_c in sign_repo.sh): repomd.xml names the primary file by its hash.
REPOMD_NS = "{http://linux.duke.edu/metadata/repo}"
PRIMARY_NS = "{http://linux.duke.edu/metadata/common}"
PRIMARY_HREF = re.compile(r"repodata/[0-9a-f]{64}-primary\.xml\.zst")
# rpm adds the distribution after the release (0.3.fc44), as check_published.sh allows; a .deb's is exact.
RPM_RELEASE = re.compile(r"([0-9]+(?:\.[0-9]+)*)(?:\.fc[0-9]+)?")
# The key that signs both repositories' metadata (sign_repo.sh, sign_apt_repo.sh), as the site publishes it.
RELEASE_KEY = ROOT / "site/keys/nulavio-packages.asc"
FINGERPRINT = re.compile(r"[0-9A-F]{40}")
# gpg status lines that mean the signature is not one good detached signature of the file: a bad, unchecked,
# expired or revoked one, or a signed message (PLAINTEXT) in place of a detached signature.
REFUSED_STATUS = ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "NO_PUBKEY", "NODATA", "PLAINTEXT")
# A cleartext-signed message's framing lines (RFC 9580, section 7), as openpgp_sign.py --clearsign and gpg write them.
CLEARTEXT_BEGIN = b"-----BEGIN PGP SIGNED MESSAGE-----"
CLEARTEXT_SIGNATURE = b"-----BEGIN PGP SIGNATURE-----"
CLEARTEXT_END = b"-----END PGP SIGNATURE-----"
APT_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+)+-[0-9]+(?:\.[0-9]+)*")
# The Firefox release whose Rust code passed the engine's networking check (scripts/build/networking_check.py, #430).
NETWORKING_RECORD = "browser/build/networking-check.json"


class ManifestError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def load(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ManifestError(f"{path}: cannot read the manifest ({e})") from None
    for key in ("firefox", "source_sha256", "engine_json", "nulavio_base_commit", "worktree_diff_sha256",
                "untracked", "packages", "sboms", "rehearsal"):  # fmt: skip
        if key not in manifest:
            raise ManifestError(f"{path}: no {key!r}: not a complete rehearsal manifest")
    # The manifest comes from the build machine. Its base commit is handed to git as a revision: only a full
    # commit hash, never something git could read as an option or as another kind of revision.
    if not isinstance(manifest["nulavio_base_commit"], str) or not COMMIT.fullmatch(manifest["nulavio_base_commit"]):
        raise ManifestError(f"{path}: the base commit is not a full commit hash")
    return manifest


def check_tree(manifest: dict) -> None:
    if manifest["rehearsal"] != "ok":
        raise ManifestError("the rehearsal did not finish")
    if manifest["worktree_diff_sha256"] != EMPTY_DIFF:
        raise ManifestError("built from a tree with uncommitted changes: commit them and rehearse again")
    if manifest["untracked"]:
        raise ManifestError(f"built with untracked files: {manifest['untracked'][:3]}")
    engine = manifest["engine_json"]
    if engine.get("firefox") != manifest["firefox"] or engine.get("source_sha256") != manifest["source_sha256"]:
        raise ManifestError("engine.json does not pin the Firefox source this rehearsal built")


def check_files(manifest: dict, out: Path) -> None:
    for entry in [*manifest["packages"], *manifest["sboms"]]:
        path = out / entry["file"]
        if not path.is_file():
            raise ManifestError(f"{entry['file']} is listed but missing")
        if sha256(path) != entry["sha256"]:
            raise ManifestError(f"{entry['file']} changed since the rehearsal (SHA-256 differs)")


def check_base(commit: str, repo: Path, ref: str) -> None:
    result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, ref], capture_output=True)
    if result.returncode != 0:
        raise ManifestError(f"base commit {commit[:12]} is not on {ref}: publish only from reviewed history")
    # The release notes give the SHA-256 of the APT source file at the base commit, and the site
    # serves it from the reviewed branch: a release whose base and branch disagree on it waits for
    # a new build, rather than telling Ubuntu users to reject the file they are served.
    sources = "site/apt/nulavio.sources"
    at = [subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{sources}"], capture_output=True) for rev in (commit, ref)]
    if at[0].returncode == 0 and (at[1].returncode != 0 or at[0].stdout != at[1].stdout):
        raise ManifestError(f"{sources} changed on {ref} since the base commit {commit[:12]}: build the release again")


def _networking_module():
    # Imported here, not at the top: next-release and the other commands of this file run in places that
    # have only scripts/release/ (the metadata workflow's checkout of one directory, tests). Signing does
    # not: without the module nothing can be compared, and nothing is published.
    sys.path.insert(0, str(ROOT / "scripts" / "build"))
    try:
        import networking_check
    except ImportError:
        raise ManifestError("scripts/build/networking_check.py is missing: the networking record cannot be compared") from None
    return networking_check


def inputs_at(repo: Path, commit: str) -> dict:
    """The digests of the release mozconfig, the variant and the patch stack as they are at a commit."""

    def at_commit(path: str) -> bytes:
        return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True, check=True).stdout

    try:
        return _networking_module().inputs(at_commit)
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        raise ManifestError(f"the mozconfig, its variant or the patch stack cannot be read at {commit[:12]}") from None


def networking_claim(out: Path, repo: Path) -> bytes:
    """The claim an attestation must exist for before this rehearsal is signed (#455).

    Made from the manifest (the Firefox release and source digest that were built, and the Rust compiler
    that built them) and from the base commit (its mozconfig, variant and patch stack, and what makes the
    reading). The record in the repository is not read: a record is a
    statement, and "accepted" is one too. The signing job asks GitHub for an attestation of these bytes by
    networking-check.yml on main; that workflow wrote the same bytes after building and reading for itself."""
    manifest = load(out / "manifest.json")
    commit = manifest["nulavio_base_commit"]
    current = inputs_at(repo, commit)

    def at_commit(path: str) -> bytes:
        return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True, check=True).stdout

    module = _networking_module()
    try:
        read_with = module.reader(at_commit)
    except subprocess.CalledProcessError:
        raise ManifestError(f"the reader, the build script or the workflow cannot be read at {commit[:12]}") from None
    # Which Rust compiler built the release (#472): the manifest step read it from the release build's own
    # configuration. The reading's claim names the compiler of the build that was read, so a release built
    # with another one finds no attestation.
    try:
        compiled_with = module.checked_compiler(manifest.get("compiled_with"))
    except ValueError as error:
        raise ManifestError(
            f"the manifest: {error} (a rehearsal made before #472 has no compiler in it: rehearse again)"
        ) from None
    return module.claim(manifest["firefox"], manifest["source_sha256"], current, read_with, compiled_with)


def check_networking(manifest: dict, repo: Path) -> None:
    """Publish only a Firefox release whose Rust code passed the engine's networking check (#430).

    The release build is cross-language (#364) and cannot be read for that check, so it is made on another build of
    the same source and recorded in the repository. The record is read at the manifest's base commit, which
    check_base() has shown to be reviewed history: never from a working tree, where anyone could write it.
    It must also have been read with that commit's mozconfig, variant and patch stack: a patch or a configure
    option changed since asks for a new reading, or a new acceptance. The record is a statement all the same
    (residual risk R79), and "accepted" is the maintainer's word only by the review of the pull request that
    wrote it."""
    commit = manifest["nulavio_base_commit"]
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{NETWORKING_RECORD}"], capture_output=True)
    try:
        record = json.loads(shown.stdout) if shown.returncode == 0 else None
    except ValueError:
        record = None
    how_to = f"run scripts/release/rehearse_release.sh --precheck {manifest['firefox']} and land its record by pull request"
    if not isinstance(record, dict):
        raise ManifestError(f"{NETWORKING_RECORD} cannot be read at the base commit {commit[:12]}: {how_to}")
    if (record.get("firefox"), record.get("source_sha256")) != (manifest["firefox"], manifest["source_sha256"]):
        raise ManifestError(
            f"the networking check's record is about Firefox {record.get('firefox')}, not the {manifest['firefox']} "
            f"this rehearsal built: nobody checked its Rust code; {how_to}"
        )
    result = record.get("result")
    accepted = result == "accepted" and re.fullmatch(r"#\d+", str(record.get("accepted_in", "")))
    if result != "passed" and not accepted:
        raise ManifestError(f"the networking check's record says {result!r}: only a pass, or the maintainer's word, publishes")

    # Also for a record accepted without a reading: it was accepted for one mozconfig, variant and patch
    # stack, and a change to any of them asks for a new acceptance or a reading.
    current = inputs_at(repo, commit)
    if record.get("built_with") != current:
        raise ManifestError(
            "the networking check's record is for another mozconfig or patch stack than the base commit's: "
            f"a patch or a configure option changed since; {how_to}"
        )


def tag(manifest: dict) -> tuple[str, list[str]]:
    rpms = [e["file"] for e in manifest["packages"] if e["file"].endswith(".rpm")]
    if not rpms:
        raise ManifestError("the manifest lists no RPM")
    versions = set()
    for name in rpms:
        match = RPM.match(Path(name).name)
        if not match:
            raise ManifestError(f"{name}: not a Nulavio RPM file name")
        if match["version"] != manifest["firefox"]:
            raise ManifestError(f"{name}: version {match['version']} is not Firefox {manifest['firefox']}")
        versions.add(f"v{match['version']}-{match['release']}")
    if len(versions) != 1:
        raise ManifestError(f"the RPMs carry different versions: {sorted(versions)}")
    return versions.pop(), rpms


def _numbers(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def published(repo: Path) -> tuple[str, str] | None:
    """The (Firefox version, package release) of the published release, if any."""
    try:
        data = json.loads((repo / "packaging" / "release.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ManifestError(f"cannot read packaging/release.json ({e})") from None
    version = data.get("version")
    if not version:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)+)-([0-9]+(?:\.[0-9]+)*)", version)
    if not match:
        raise ManifestError(f"packaging/release.json: version {version!r} is not <firefox>-<release>")
    return match[1], match[2]


def check_newer(release_tag: str, repo: Path) -> None:
    exists = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{release_tag}"],
                            capture_output=True)  # fmt: skip
    if exists.returncode == 0:
        raise ManifestError(f"the tag {release_tag} already exists")
    version, _, release = release_tag[1:].partition("-")
    known = release_versions(repo)
    current = max(known, key=lambda v: (_numbers(v[0]), _numbers(v[1]))) if known else None
    if current and (_numbers(version), _numbers(release)) <= (_numbers(current[0]), _numbers(current[1])):
        raise ManifestError(
            f"{release_tag} is not newer than the published {current[0]}-{current[1]}: dnf would not upgrade "
            "to it; rebuild with a higher NULAVIO_RELEASE"
        )


def check_not_older(release_tag: str, repo: Path, others: list[str] | tuple[str, ...] = ()) -> None:
    """Nothing newer than `release_tag` is tagged, recorded as published, or among `others` (the GitHub releases,
    drafts included), so uploading its signed repositories cannot roll them back. The release itself may be
    uploaded again: a re-run after a later step failed."""
    match = RELEASE_TAG.fullmatch(release_tag)
    if not match:
        raise ManifestError(f"{release_tag!r} is not a release tag")

    def key(version: tuple[str, str]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return _numbers(version[0]), _numbers(version[1])

    known = release_versions(repo) + [(m[1], m[2]) for tag in others if (m := RELEASE_TAG.fullmatch(tag))]
    newer = [version for version in known if key(version) > key((match[1], match[2]))]
    if newer:
        top = max(newer, key=key)
        raise ManifestError(
            f"{release_tag} is older than {top[0]}-{top[1]}: uploading it would roll the dnf and APT repositories back"
        )


def release_versions(repo: Path) -> list[tuple[str, str]]:
    """Reserve existing tags as well as the published site version (which can lag)."""
    tags = subprocess.run(["git", "-C", str(repo), "tag", "--list", "v*"],
                          capture_output=True, text=True, check=True).stdout.splitlines()  # fmt: skip
    versions = [(m[1], m[2]) for tag in tags if (m := RELEASE_TAG.fullmatch(tag))]
    current = published(repo)
    if current:
        versions.append(current)
    return versions


def next_release(firefox: str, repo: Path, others: list[str] | tuple[str, ...] = ()) -> str:
    """One above every revision of `firefox` that is tagged, recorded as published or among `others` (the version
    the bucket serves: a run that uploaded and stopped before its draft left neither a tag nor a draft, #656)."""
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", firefox):
        raise ManifestError("invalid Firefox version")
    known = release_versions(repo) + [(m[1], m[2]) for tag in others if (m := RELEASE_TAG.fullmatch(tag))]
    revisions = [release for version, release in known if version == firefox]
    if not revisions:
        return "0.1"
    parts = list(_numbers(max(revisions, key=_numbers)))
    parts[-1] += 1
    return ".".join(map(str, parts))


def _xml(data: bytes, what: str) -> ET.Element:
    # Downloaded from the bucket: createrepo_c writes UTF-8 and no DTD, and without one no entity can expand (S314).
    # Checked on what expat reads, not on the bytes, which another encoding (UTF-16) hides from a byte search. expat
    # takes a document whose first bytes look like UTF-16 as UTF-16, even when told UTF-8; without a byte order mark
    # such a document is valid UTF-8 bytes (ASCII with NULs), and XML allows no NUL character, so a NUL refuses it.
    # A declaration of another encoding is refused too.
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestError(f"{what} is not UTF-8, which createrepo_c always writes") from None
    if b"\0" in data:
        raise ManifestError(f"{what} holds a NUL byte: not UTF-8 XML, which createrepo_c always writes")

    def refuse(*_args: object) -> None:
        raise ManifestError(f"{what} declares a DTD or an entity, which createrepo_c never writes")

    def declared(_version: str | None, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.lower() not in ("utf-8", "utf8"):
            raise ManifestError(f"{what} declares the encoding {encoding!r}, not UTF-8")

    scan = expat.ParserCreate()
    scan.XmlDeclHandler = declared
    scan.StartDoctypeDeclHandler = refuse
    scan.EntityDeclHandler = refuse
    try:
        scan.Parse(data, True)
        return ET.fromstring(data)  # noqa: S314 - no DTD or entity (above); the bucket's index, written by sign_repo.sh
    except (expat.ExpatError, ET.ParseError) as e:
        raise ManifestError(f"{what} is not readable XML: {e}") from None


def _primary_entry(repomd: bytes) -> ET.Element:
    entries = [d for d in _xml(repomd, "repomd.xml").iter(f"{REPOMD_NS}data") if d.get("type") == "primary"]
    if len(entries) != 1:
        raise ManifestError(f"repomd.xml names {len(entries)} primary files, not one")
    return entries[0]


def dnf_primary(repomd: bytes) -> str:
    """Where repomd.xml says the primary metadata is, relative to the repository; only createrepo_c's form, since
    it becomes part of a URL."""
    location = _primary_entry(repomd).find(f"{REPOMD_NS}location")
    href = location.get("href", "") if location is not None else ""
    if not PRIMARY_HREF.fullmatch(href):
        raise ManifestError(f"repomd.xml names the primary file {href!r}, not repodata/<sha256>-primary.xml.zst")
    return href


def dnf_compressed(repomd: bytes, compressed: bytes) -> None:
    """Refuse the compressed primary file unless its SHA-256 is the checksum repomd.xml gives, before anything
    decompresses it (#729)."""
    checksum = _primary_entry(repomd).find(f"{REPOMD_NS}checksum")
    if checksum is None or checksum.get("type") != "sha256" or checksum.text != hashlib.sha256(compressed).hexdigest():
        raise ManifestError("the compressed primary file is not the one repomd.xml names (checksum)")


def dnf_served(repomd: bytes, primary: bytes) -> str:
    """The highest <version>-<release> of nulavio in the primary metadata that repomd.xml names (#723): a run whose
    dnf upload finished and whose APT upload failed left this version in the dnf index only."""
    checksum = _primary_entry(repomd).find(f"{REPOMD_NS}open-checksum")
    if checksum is None or checksum.get("type") != "sha256" or checksum.text != hashlib.sha256(primary).hexdigest():
        raise ManifestError("the primary file is not the one repomd.xml names (open-checksum)")
    served = []
    for package in _xml(primary, "the primary file").iter(f"{PRIMARY_NS}package"):
        if package.findtext(f"{PRIMARY_NS}name") != "nulavio":
            continue
        version = package.find(f"{PRIMARY_NS}version")
        ver, rel = (version.get("ver", ""), version.get("rel", "")) if version is not None else ("", "")
        release = RPM_RELEASE.fullmatch(rel)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", ver) or not release:
            raise ManifestError(f"the primary file lists nulavio {ver!r}-{rel!r}, not <version>-<release>")
        served.append((ver, release[1]))
    if not served:
        raise ManifestError("the primary file lists no nulavio package")
    ver, rel = max(served, key=lambda v: (_numbers(v[0]), _numbers(v[1])))
    return f"{ver}-{rel}"


def _gpg(home: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gpg", "--homedir", home, "--batch", "--no-tty", "--no-auto-key-retrieve", *args],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def verify_signature(data: Path, signature: Path, key: Path, fingerprint: str) -> None:
    """Refuse data unless signature is one good detached signature of it by the key whose fingerprint is given, or
    by one of that key's subkeys (#729). Only that key is in the throwaway GNUPGHOME gpg checks against."""
    if not signature.is_file():
        raise ManifestError(f"{data.name} has no signature ({signature} is missing)")
    _verify(key, fingerprint, signature, data)


def verify_clearsigned(message: Path, out: Path, key: Path, fingerprint: str) -> None:
    """Write to out the text of message, a cleartext-signed file such as InRelease, once it is one good signature
    by the key whose fingerprint is given (or a subkey), framed as openpgp_sign.py --clearsign and gpg write it:
    one signed message, nothing before or after (#729). InRelease is one object in the bucket, so it never pairs
    one run's text with another run's signature, as Release and Release.gpg do while an upload is between them."""
    lines = message.read_bytes().split(b"\n")
    if (
        lines[0] != CLEARTEXT_BEGIN
        or lines[-2:] != [CLEARTEXT_END, b""]
        or [lines.count(marker) for marker in (CLEARTEXT_BEGIN, CLEARTEXT_SIGNATURE, CLEARTEXT_END)] != [1, 1, 1]
    ):
        raise ManifestError(f"{message.name} is not one cleartext-signed message and nothing else")
    _verify(key, fingerprint, message, out=out)


def _verify(key: Path, fingerprint: str, *files: Path, out: Path | None = None) -> None:
    # A detached signature and its data (out None), or a cleartext-signed message whose text goes to out. gpg
    # writes that text before it judges the signature, so it stays in the throwaway home until the checks pass.
    fingerprint = fingerprint.upper()
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ManifestError(f"{fingerprint!r} is not a full key fingerprint (40 hex digits)")
    name = files[-1].name
    with tempfile.TemporaryDirectory(prefix="nulavio-verify-") as home:
        try:
            if _gpg(home, "--quiet", "--import", str(key)).returncode != 0:
                raise ManifestError(f"{key} is not an OpenPGP key gpg can import")
            listed = _gpg(home, "--with-colons", "--fixed-list-mode", "--list-keys").stdout.splitlines()
            primaries, signers, kind = [], set(), ""
            for line in listed:
                fields = line.split(":")
                if fields[0] in ("pub", "sub"):
                    kind = fields[0]
                elif fields[0] == "fpr" and kind:
                    if kind == "pub":
                        primaries.append(fields[9])
                    signers.add(fields[9])
                    kind = ""
            if primaries != [fingerprint]:
                raise ManifestError(f"{key} holds {primaries}, not the key {fingerprint} alone")
            signed = Path(home) / "signed"
            output = ("--output", str(signed)) if out else ()
            checked = _gpg(home, "--status-fd", "1", *output, "--verify", *map(str, files))
        finally:
            subprocess.run(["gpgconf", "--homedir", home, "--kill", "all"], capture_output=True, check=False)
        status = [line.split()[1:] for line in checked.stdout.splitlines() if line.startswith("[GNUPG:] ")]
        names = [fields[0] for fields in status if fields]
        valid = [fields[1:] for fields in status if fields and fields[0] == "VALIDSIG"]
        # A cleartext-signed message gives one PLAINTEXT line; a detached signature none (REFUSED_STATUS).
        refused = sorted(set(names) & set(REFUSED_STATUS) - ({"PLAINTEXT"} if out else set()))
        if (
            checked.returncode != 0
            or refused
            or names.count("NEWSIG") != 1
            or names.count("GOODSIG") != 1
            or names.count("PLAINTEXT") != (1 if out else 0)
            or len(valid) != 1
            or valid[0][0] not in signers
            or valid[0][-1] != fingerprint
        ):
            why = ", ".join(refused) or f"gpg exit {checked.returncode}, {names.count('VALIDSIG')} valid signatures"
            what = f"{files[0].name} is not a good signature" + ("" if out else f" of {name}")
            raise ManifestError(f"{what} by {fingerprint} ({why})")
        if out:
            out.write_bytes(signed.read_bytes())


def _apt_named(release: bytes) -> list[str]:
    # The SHA-256 and size that the Release file gives main/binary-amd64/Packages.
    try:
        text = release.decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestError("the Release file is not UTF-8") from None
    named, section = [], ""
    for line in text.splitlines():
        if not line.startswith(" "):
            section = line.split(":", 1)[0]
            continue
        fields = line.split()
        if section == "SHA256" and len(fields) == 3 and fields[2] == "main/binary-amd64/Packages":
            named.append(fields[:2])
    if len(named) != 1:
        raise ManifestError(f"the Release file names {len(named)} SHA-256 sums of main/binary-amd64/Packages, not one")
    if not re.fullmatch(r"[0-9a-f]{64}", named[0][0]) or not named[0][1].isdigit():
        raise ManifestError(f"the Release file gives main/binary-amd64/Packages {named[0]}, not a SHA-256 and a size")
    return named[0]


def apt_packages(release: bytes) -> str:
    """Where the Packages file that the Release file names is, by its SHA-256 (Acquire-By-Hash, sign_apt_repo.sh):
    the plain Packages object is replaced before InRelease during an upload, the hash-named one never (#729)."""
    return f"main/binary-amd64/by-hash/SHA256/{_apt_named(release)[0]}"


def apt_served(release: bytes, packages: bytes) -> str:
    """The highest <version>-<release> of nulavio in the APT Packages file, once the signed Release file names its
    SHA-256 and size (#729)."""
    if _apt_named(release) != [hashlib.sha256(packages).hexdigest(), str(len(packages))]:
        raise ManifestError("the Packages file is not the one the Release file names (SHA256)")
    try:
        stanzas = packages.decode("utf-8").split("\n\n")
    except UnicodeDecodeError:
        raise ManifestError("the Packages file is not UTF-8") from None
    served = []
    for stanza in stanzas:
        fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and not line.startswith(" "))
        if fields.get("Package") != "nulavio":
            continue
        version = fields.get("Version", "")
        if not APT_VERSION.fullmatch(version):
            raise ManifestError(f"the Packages file lists nulavio {version!r}, not <version>-<release>")
        served.append(version)
    if not served:
        raise ManifestError("the Packages file lists no nulavio package")
    return max(served, key=lambda v: tuple(_numbers(part) for part in v.split("-", 1)))


def debs(manifest: dict, release_tag: str) -> list[str]:
    """The .deb packages, which carry the RPM's version and release (one engine build, two formats)."""
    found = [e["file"] for e in manifest["packages"] if e["file"].endswith(".deb")]
    for name in found:
        match = DEB.match(Path(name).name)
        if not match:
            raise ManifestError(f"{name}: not a Nulavio .deb file name")
        if f"v{match['version']}-{match['release']}" != release_tag:
            raise ManifestError(f"{name}: not the version of the RPM ({release_tag})")
    return found


def verify(out: Path, repo: Path, ref: str) -> dict:
    manifest = load(out / "manifest.json")
    check_tree(manifest)
    check_files(manifest, out)
    check_base(manifest["nulavio_base_commit"], repo, ref)
    check_networking(manifest, repo)
    release_tag, rpms = tag(manifest)
    deb_files = debs(manifest, release_tag)
    check_newer(release_tag, repo)
    if manifest.get("whats_new") != release_tag.removeprefix("v"):
        # #198: the browser shows the notes packed with it; a pre-build made before they were written has none.
        raise ManifestError(
            f"the packages carry no notes for {release_tag.removeprefix('v')} (whats_new: {manifest.get('whats_new')!r}):"
            f" add packaging/whats-new/{release_tag.removeprefix('v')}.json and rehearse again"
        )
    return {
        "tag": release_tag,
        "firefox": manifest["firefox"],
        "commit": manifest["nulavio_base_commit"],
        "rpms": rpms,
        "debs": deb_files,
        "archives": [e["file"] for e in manifest["packages"] if e["file"].endswith(ARCHIVE_SUFFIX)],
        "sboms": [e["file"] for e in manifest["sboms"]],
    }


def check_packages(manifest_path: Path, packages: Path) -> list[str]:
    manifest = load(manifest_path)
    listed = {e["sha256"] for e in manifest["packages"]}
    found = sorted(
        [*packages.rglob("nulavio-*.rpm"), *packages.rglob("nulavio_*.deb"), *packages.rglob(f"nulavio-*{ARCHIVE_SUFFIX}")]
    )
    if not found:
        raise ManifestError(f"{packages}: no Nulavio packages")
    extra = [str(p.relative_to(packages)) for p in found if sha256(p) not in listed]
    if extra:
        raise ManifestError(f"not in the manifest (or changed since): {extra}")
    return [str(p.relative_to(packages)) for p in found]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="a rehearsal output directory is fit to sign and publish")
    v.add_argument("out", type=Path)
    v.add_argument("--repo", type=Path, default=ROOT)
    v.add_argument("--on", default="origin/main", help="the base commit must be an ancestor of this ref")
    p = sub.add_parser("packages", help="every package in a directory is listed in the manifest")
    p.add_argument("manifest", type=Path)
    p.add_argument("packages", type=Path)
    n = sub.add_parser("next-release", help="the package release to build for a Firefox version")
    n.add_argument("firefox")
    n.add_argument("--repo", type=Path, default=ROOT)
    n.add_argument("--also", action="append", default=[], help="a release's tag to count as taken, such as the served one")
    c = sub.add_parser("networking-claim", help="the claim whose attestation the signing job requires (bytes on stdout)")
    c.add_argument("out", type=Path)
    c.add_argument("--repo", type=Path, default=ROOT)
    o = sub.add_parser("not-older", help="uploading a release's repositories would not roll them back")
    o.add_argument("tag")
    o.add_argument("--repo", type=Path, default=ROOT)
    o.add_argument("--also", action="append", default=[], help="another release's tag, such as a draft's")
    d = sub.add_parser("dnf-primary", help="where the dnf repository's repomd.xml says its primary metadata is")
    d.add_argument("repomd", type=Path)
    dc = sub.add_parser("dnf-compressed", help="refuse the compressed primary file unless repomd.xml gives its SHA-256")
    dc.add_argument("repomd", type=Path)
    dc.add_argument("compressed", type=Path, help="the primary file dnf-primary named, as downloaded")
    ds = sub.add_parser("dnf-served", help="the highest nulavio version the dnf repository's primary metadata lists")
    ds.add_argument("repomd", type=Path)
    ds.add_argument("primary", type=Path, help="the primary file dnf-primary named, decompressed")
    vs = sub.add_parser("verify-signed", help="refuse a file unless the release key signed it (detached signature)")
    vs.add_argument("file", type=Path)
    vs.add_argument("signature", type=Path)
    vs.add_argument("--fingerprint", required=True, help="the release key's full fingerprint")
    vs.add_argument("--key", type=Path, default=RELEASE_KEY, help="the release key's public key file")
    vc = sub.add_parser("verify-clearsigned", help="the text of a cleartext-signed file (InRelease) the release key signed")
    vc.add_argument("message", type=Path)
    vc.add_argument("out", type=Path, help="where the signed text goes, once it verifies")
    vc.add_argument("--fingerprint", required=True, help="the release key's full fingerprint")
    vc.add_argument("--key", type=Path, default=RELEASE_KEY, help="the release key's public key file")
    pk = sub.add_parser("apt-packages", help="where the Packages file a Release file names is, by its SHA-256")
    pk.add_argument("release", type=Path, help="the Release file, its signature checked (verify-clearsigned)")
    ap = sub.add_parser("apt-served", help="the highest nulavio version a Packages file that Release names lists")
    ap.add_argument("release", type=Path, help="the Release file, its signature checked (verify-clearsigned)")
    ap.add_argument("packages", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(json.dumps(verify(args.out, args.repo, args.on), indent=2))
        elif args.command == "networking-claim":
            sys.stdout.buffer.write(networking_claim(args.out, args.repo))
        elif args.command == "not-older":
            check_not_older(args.tag, args.repo, args.also)
        elif args.command == "next-release":
            print(next_release(args.firefox, args.repo, args.also))
        elif args.command == "dnf-primary":
            print(dnf_primary(args.repomd.read_bytes()))
        elif args.command == "dnf-compressed":
            dnf_compressed(args.repomd.read_bytes(), args.compressed.read_bytes())
        elif args.command == "dnf-served":
            print(dnf_served(args.repomd.read_bytes(), args.primary.read_bytes()))
        elif args.command == "verify-signed":
            verify_signature(args.file, args.signature, args.key, args.fingerprint)
        elif args.command == "verify-clearsigned":
            verify_clearsigned(args.message, args.out, args.key, args.fingerprint)
        elif args.command == "apt-packages":
            print(apt_packages(args.release.read_bytes()))
        elif args.command == "apt-served":
            print(apt_served(args.release.read_bytes(), args.packages.read_bytes()))
        else:
            print("\n".join(check_packages(args.manifest, args.packages)))
    except (ManifestError, OSError) as e:  # OSError: an input file that is missing or cannot be read
        print(f"release_manifest: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
