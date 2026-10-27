#!/usr/bin/env python3
"""Move browser/build/engine.json to a newer Firefox release, with its verified source digest.

    python3 -I scripts/release/bump_engine.py <version> [--allow-staged] [--json] [--engine FILE]
    python3 -I scripts/release/bump_engine.py --check [--json] [--engine FILE]

The digest always comes from Mozilla's SHA256SUMS after its signature verifies
against the pinned release key (scripts/upstream/verify_firefox_release.py);
nothing here can skip that check. Release channel only (158.0, 158.0.1; no ESR).
Without --allow-staged the version must already be published (product-details).
--check verifies again that engine.json's digest is the one Mozilla signed.

Only engine.json changes: reviewing, committing and the security changelog stay
manual (the script prints the changelog entry to fill in).

Exit status: 0 done; 2 bad arguments or engine.json; 3 not newer than the pinned
release; 4 not published yet, or publication could not be confirmed;
5 signature verification failed; 6 (--check) the pinned digest is missing or differs;
7 the signature could not be checked (network, or the files are not on the archive).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_upstream  # noqa: E402

ENGINE = watch_upstream.ENGINE
CHANGELOG_ENTRY = """\
Security changelog entry (docs/security/changelog.md), to complete when the build is published:

**Upstream**: Firefox {version}, released by Mozilla on <date, time UTC> ([advisory](https://www.mozilla.org/security/advisories/)).
Urgency: <urgent or standard, and why>. Ready to sign <time UTC>, <hours> h after Mozilla's release;
published <time UTC>, <hours> h after (target <24 or 72> h, deadline 72 h). Source SHA-256 {digest}."""


class BumpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def read_engine(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BumpError(2, f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("firefox"), str):
        raise BumpError(2, f"{path}: no 'firefox' version")
    return data


def write_engine(path: Path, data: dict) -> None:
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    partial.replace(path)


def verified_digest(version: str, verify) -> tuple[str, str]:
    try:
        digest, subkey = verify(version)
    except watch_upstream.VerificationFailed as exc:
        raise BumpError(5, f"Firefox {version}: signature verification FAILED: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise BumpError(
            7, f"Firefox {version}: signature could not be checked (network, or files not on the archive): {exc}"
        ) from exc
    if not isinstance(digest, str) or not watch_upstream.SHA256_RE.match(digest):
        raise BumpError(5, f"Firefox {version}: unexpected digest {digest!r}")
    return digest, subkey


def bump(version: str, *, engine: Path, allow_staged: bool, published, verify) -> dict:
    """Pin `version` and its signed digest in engine.json. `published(version)` and `verify(version)` reach Mozilla."""
    if not watch_upstream.RELEASE_RE.match(version):
        raise BumpError(2, f"{version!r} is not a Release-channel version such as 159.0 or 159.0.1 (ESR is not built)")
    data = read_engine(engine)
    previous = data["firefox"]
    if watch_upstream.RELEASE_RE.match(previous) and watch_upstream.version_key(version) <= watch_upstream.version_key(previous):
        raise BumpError(3, f"engine.json already pins Firefox {previous}; {version} is not newer (no downgrades)")
    if not allow_staged:
        try:
            shipped = published(version)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise BumpError(4, f"cannot confirm that Mozilla published Firefox {version}: {exc}") from exc
        if not shipped:
            raise BumpError(4, f"Mozilla has not published Firefox {version} yet (use --allow-staged for a pre-build)")
    digest, subkey = verified_digest(version, verify)
    data["firefox"] = version
    data["source_sha256"] = digest
    write_engine(engine, data)
    return {
        "version": version,
        "previous": previous,
        "source_sha256": digest,
        "signing_primary": watch_upstream.pinned_primary(),
        "signing_subkey": subkey,
    }


def check(*, engine: Path, verify) -> dict:
    """engine.json's digest must still be the one in Mozilla's signed SHA256SUMS."""
    data = read_engine(engine)
    version, pinned = data["firefox"], data.get("source_sha256")
    if not watch_upstream.RELEASE_RE.match(version):
        raise BumpError(2, f"engine.json pins {version!r}, not a Release-channel version")
    if not isinstance(pinned, str) or not watch_upstream.SHA256_RE.match(pinned):
        raise BumpError(6, "engine.json has no source_sha256 (64 lowercase hex digits): pin it with bump_engine.py")
    digest, subkey = verified_digest(version, verify)
    if digest != pinned:
        raise BumpError(6, f"engine.json pins {pinned} for Firefox {version}, Mozilla's signed SHA256SUMS lists {digest}")
    return {
        "version": version,
        "source_sha256": digest,
        "signing_primary": watch_upstream.pinned_primary(),
        "signing_subkey": subkey,
    }


def published_on(network) -> Callable[[str], bool]:
    def published(version: str) -> bool:
        history: dict = {}
        for name in watch_upstream.SOURCES:
            history.update(network.product(name))
        if version in watch_upstream.release_history(history):
            return True
        latest = network.product(watch_upstream.VERSIONS)
        return isinstance(latest, dict) and latest.get("LATEST_FIREFOX_VERSION") == version

    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", nargs="?", help="Firefox release to move to, such as 159.0.1")
    parser.add_argument("--check", action="store_true", help="re-verify the pinned digest instead of moving")
    parser.add_argument("--allow-staged", action="store_true", help="accept a release Mozilla has staged but not published")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--engine", type=Path, default=ENGINE, help="engine.json to change (default: the repository's)")
    args = parser.parse_args(argv)
    if args.check == bool(args.version):
        parser.error("give a version, or --check")
    network = watch_upstream.Network()
    try:
        if args.check:
            result = check(engine=args.engine, verify=network.verify)
        else:
            result = bump(
                args.version,
                engine=args.engine,
                allow_staged=args.allow_staged,
                published=published_on(network),
                verify=network.verify,
            )
    except BumpError as exc:
        print(f"bump_engine: {exc}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": exc.code}))
        return exc.code
    if args.json:
        print(json.dumps(result))
    elif args.check:
        print(f"OK  engine.json pins Firefox {result['version']} = Mozilla's signed digest {result['source_sha256']}")
    else:
        print(f"engine.json: Firefox {result['previous']} -> {result['version']}")
        print(f"OK  signature by {result['signing_primary']} (subkey {result['signing_subkey']})")
        print(f"{result['source_sha256']}  source/firefox-{result['version']}.source.tar.xz")
        print()
        print(CHANGELOG_ENTRY.format(version=result["version"], digest=result["source_sha256"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
