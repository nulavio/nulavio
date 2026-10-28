#!/usr/bin/env python3
"""Review a regenerated android/gradle/verification-metadata.xml before committing it.

The file is the Companion build's trust anchor. Dependabot cannot update it (dependabot-core
#1996) and CI must never write it, so after a Gradle dependency bump a maintainer regenerates it
locally, from an empty Gradle cache so nothing cached earlier gets recorded, together with the
lockfiles of the APK's classpath (docs/security/dependency-updates.md):

    export JAVA_HOME=~/.local/share/nulavio-dev/jdk-21 ANDROID_HOME=~/Android/Sdk
    export GRADLE_USER_HOME=$(mktemp -d)
    android/gradlew -p android --no-daemon --write-verification-metadata sha256 --write-locks \\
        :app:dependencies --configuration releaseRuntimeClasspath \\
        :nv1:dependencies --configuration runtimeClasspath \\
        :nv1:test :app:lintDebug :app:assembleRelease
    python3 -I scripts/upstream/review_gradle_verification.py [--base origin/main]

Lists the components added and removed against the base revision and the change in what the APK
ships (android/app/gradle.lockfile). For every added artifact it checks the recorded SHA-256
against the file in the Gradle cache and against the checksum the repository publishes next to it
(.sha256, else .sha1), and says whether a PGP signature (.asc) is published. Exit 1 on any
mismatch or missing checksum, on a changed hash or a new "also-trust" for a version that was
already pinned, on a change to the <configuration> block, or on a locked module the metadata does
not pin. Old versions of an updated component are listed for removal (Gradle never removes
entries). Nothing is written.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METADATA = "android/gradle/verification-metadata.xml"
LOCKFILES = ("android/app/gradle.lockfile", "android/nv1/gradle.lockfile")
REPOSITORIES = (  # android/settings.gradle.kts, in order
    "https://dl.google.com/dl/android/maven2/",
    "https://repo.maven.apache.org/maven2/",
    "https://plugins.gradle.org/m2/",
)

Key = tuple[str, str, str]


def parse(xml: str) -> tuple[str, dict[Key, dict[str, set[str]]]]:
    """(the <configuration> block, {(group, name, version): {artifact: {trusted sha256 values}}})."""
    root = ET.fromstring(xml)  # noqa: S314 - our committed file or its local regeneration
    ns = root.tag.split("}")[0] + "}"
    configuration = root.find(f"{ns}configuration")
    config = ET.tostring(configuration, encoding="unicode") if configuration is not None else ""
    found: dict[Key, dict[str, set[str]]] = {}
    for component in root.iter(f"{ns}component"):
        artifacts = found.setdefault((component.get("group"), component.get("name"), component.get("version")), {})
        for artifact in component.iter(f"{ns}artifact"):
            values = artifacts.setdefault(artifact.get("name"), set())
            for sha in artifact.iter(f"{ns}sha256"):
                values.add(sha.get("value"))
                values.update(also.get("value") for also in sha.iter(f"{ns}also-trust"))
    return " ".join(config.split()), found


def fetch_checksum(url: str) -> str | None:
    """The first word of a published checksum file, or None when there is none."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # fixed https repositories (S310 is off for scripts/upstream)
            words = response.read(4096).decode("ascii", "replace").split()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return words[0].lower() if words else None


def published(key: Key, artifact: str, fetch: Callable[[str], str | None]) -> tuple[str, str, str, bool] | None:
    """(repository, algorithm, checksum, signed) from the first repository that has the artifact."""
    group, name, version = key
    path = f"{group.replace('.', '/')}/{name}/{version}/{artifact}"
    for repository in REPOSITORIES:
        for algorithm in ("sha256", "sha1"):
            value = fetch(f"{repository}{path}.{algorithm}")
            if value:
                return repository, algorithm, value, fetch(f"{repository}{path}.asc") is not None
    return None


def cache_dirs() -> list[Path]:
    """Gradle's dependency caches: GRADLE_USER_HOME's, then a read-only one (GRADLE_RO_DEP_CACHE) if set."""
    dirs = [Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle")) / "caches"]
    if os.environ.get("GRADLE_RO_DEP_CACHE"):
        dirs.append(Path(os.environ["GRADLE_RO_DEP_CACHE"]))
    return dirs


def cached(caches: list[Path], key: Key, artifact: str) -> Path | None:
    group, name, version = key
    for cache in caches:
        found = sorted((cache / "modules-2" / "files-2.1" / group / name / version).glob(f"*/{artifact}"))
        if found:
            return found[0]
    return None


def digest(path: Path, algorithm: str) -> str:
    return hashlib.new(algorithm, path.read_bytes()).hexdigest()


def check_artifact(key: Key, artifact: str, recorded: set[str], caches: list[Path], fetch) -> tuple[bool, str]:
    notes, bad = [], False
    if len(recorded) != 1:
        notes.append(f"{len(recorded)} trusted hashes recorded, expected 1")
        bad = True
    sha256 = next(iter(sorted(recorded)), "")
    local = cached(caches, key, artifact)
    if local is None:
        notes.append("not in the Gradle cache (run the regeneration with this GRADLE_USER_HOME)")
        bad = True
    elif digest(local, "sha256") != sha256:
        notes.append("MISMATCH with the cached file")
        bad = True
    remote = published(key, artifact, fetch)
    if remote is None:
        notes.append("no published checksum")
        bad = True
    else:
        repository, algorithm, value, signed = remote
        if algorithm == "sha1" and local is None:
            notes.append(f"sha1 published by {repository}, not compared (no cached file)")
        else:
            # A published SHA-1 is compared with the cached file, whose SHA-256 was compared with the pin above.
            matches = value == (sha256 if algorithm == "sha256" else digest(local, "sha1"))
            bad = bad or not matches
            notes.append(f"{algorithm} {'matches' if matches else 'MISMATCH'} {repository}")
        notes.append("signed (.asc)" if signed else "unsigned")
    return bad, f"    {'!' if bad else ' '} {artifact}: {'; '.join(notes)}"


def locked(text: str) -> set[str]:
    return {line for line in text.splitlines() if line and not line.startswith("#") and line != "empty="}


def review(old_xml: str, new_xml: str, old_locks: dict[str, str], new_locks: dict[str, str], caches: list[Path], fetch):
    """Return (report lines, number of problems)."""
    old_config, old = parse(old_xml)
    new_config, new = parse(new_xml)
    lines, problems = [], 0
    if old_config != new_config:
        lines.append("! the <configuration> block changed: this review covers a sha256 regeneration only")
        problems += 1
    for key in sorted(new.keys() & old.keys()):
        for artifact, values in sorted(new[key].items()):
            before = old[key].get(artifact)
            if before is not None and values != before:
                lines.append(f"! {':'.join(key)} {artifact}: the trusted hashes changed for a version already pinned")
                problems += 1
    for key in sorted(new.keys() - old.keys()):
        lines.append(f"+ {':'.join(key)}")
        for artifact, values in sorted(new[key].items()):
            bad, line = check_artifact(key, artifact, values, caches, fetch)
            problems += bad
            lines.append(line)
    for key in sorted(new.keys() & old.keys()):
        added = sorted(new[key].keys() - old[key].keys())
        if added:
            lines.append(f"~ {':'.join(key)} (new artifacts)")
            for artifact in added:
                bad, line = check_artifact(key, artifact, new[key][artifact], caches, fetch)
                problems += bad
                lines.append(line)
    lines += [f"- {':'.join(key)}" for key in sorted(old.keys() - new.keys())]
    updated = {(g, n) for g, n, _ in new.keys() - old.keys()}
    stale = [":".join(k) for k in sorted(new.keys() & old.keys()) if k[:2] in updated]
    if stale:
        lines.append("Older versions of updated components are still listed (remove them if the build no longer uses them):")
        lines += [f"    {s}" for s in stale]
    for path in sorted(new_locks):
        before, after = locked(old_locks.get(path, "")), locked(new_locks[path])
        if before != after:
            lines.append(f"{path}:")
            lines += [f"    - {line}" for line in sorted(before - after)] + [f"    + {line}" for line in sorted(after - before)]
        for line in sorted(after):
            group, name, version = line.partition("=")[0].split(":")
            if (group, name, version) not in new:
                lines.append(f"! {path}: {group}:{name}:{version} is locked but not pinned in the verification metadata")
                problems += 1
    added_count, removed_count = len(new.keys() - old.keys()), len(old.keys() - new.keys())
    lines.append(f"{added_count} added, {removed_count} removed, {problems} problem(s) need attention")
    return lines, problems


def at_revision(revision: str, path: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "show", f"{revision}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD", help="git revision to compare with (default HEAD)")
    args = parser.parse_args()
    old_xml = at_revision(args.base, METADATA)
    if not old_xml:
        print(f"review_gradle_verification: {METADATA} not found at {args.base}", file=sys.stderr)
        return 2
    new_xml = (ROOT / METADATA).read_text(encoding="utf-8")
    old_locks = {path: at_revision(args.base, path) for path in LOCKFILES}
    new_locks = {path: (ROOT / path).read_text(encoding="utf-8") for path in LOCKFILES}
    lines, problems = review(old_xml, new_xml, old_locks, new_locks, cache_dirs(), fetch_checksum)
    print("\n".join(lines))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
