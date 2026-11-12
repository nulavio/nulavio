#!/usr/bin/env bash
# Rehearse a security release end to end and time each step (update SLA).
#
#   scripts/release/rehearse_release.sh <firefox-version> [out-dir]
#
# Steps: verify Mozilla's signed checksums, build (scripts/build/build_nulavio.sh,
# incremental when the tree is already there), install the tree, unit and
# integration tests, RPM and .deb with their clean-container checks, the
# signed-repository check (throwaway key), SBOMs. Writes <out>/rehearsal.md.
# Publishing is not rehearsed: it needs the release key and the host.
set -euo pipefail

version=${1:?usage: rehearse_release.sh <firefox-version> [out-dir]}
[[ -z ${NULAVIO_MOZCONFIG_EXTRA:-} ]] || { echo "rehearse_release: unset NULAVIO_MOZCONFIG_EXTRA: a variant build is never a release" >&2; exit 2; }
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=${NULAVIO_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build}
install="$work/install/nulavio"
# Package exactly the tree installed below, including with a private build cache.
export NULAVIO_INSTALL_DIR="$install"
# The package release: one above the published one for the same Firefox, so that
# dnf upgrades the people who installed it (release_manifest.py verify refuses less).
NULAVIO_RELEASE=${NULAVIO_RELEASE:-$(python3 -I "$repo/scripts/release/release_manifest.py" next-release "$version")}
export NULAVIO_RELEASE
out=$(mkdir -p "${2:-$repo/dist/rehearsal-$version}" && cd "${2:-$repo/dist/rehearsal-$version}" && pwd)
mkdir -p "$out/logs" "$out/packages"
report="$out/rehearsal.md"
start=$(date +%s)
printf '# Release rehearsal: Firefox %s\n\nStarted %s.\n\n| Step | Time | Result |\n|---|---|---|\n' "$version" "$(date -u +%FT%TZ)" > "$report"

step() {
    local name=$1 t0 status
    shift
    t0=$(date +%s)
    set +e
    "$@" > "$out/logs/$name.log" 2>&1
    status=$?
    set -e
    local took=$(( $(date +%s) - t0 ))
    if (( status != 0 )); then
        printf '| %s | %d min %02d s | failed (logs/%s.log) |\n' "$name" $((took / 60)) $((took % 60)) "$name" >> "$report"
        echo "rehearsal: $name failed, see $out/logs/$name.log" >&2
        exit 1
    fi
    printf '| %s | %d min %02d s | ok |\n' "$name" $((took / 60)) $((took % 60)) >> "$report"
    echo "rehearsal: $name ok (${took}s)"
}

install_tree() {
    local tarball
    # shellcheck disable=SC2012 # the newest by time; the build names these files (nulavio-<version>.<locale>.linux-x86_64.tar.xz)
    tarball=$(ls -t "$work/firefox-$version"/obj-nulavio/dist/nulavio-*.tar.xz | head -1)
    rm -rf "$install"
    mkdir -p "$work/install"
    tar -xJf "$tarball" -C "$work/install"
    # policies.json carries uBlock Origin's list registry from the repository. make_distribution.py compares that
    # copy with a checksum kept beside it; this compares it with the pinned package itself (from the cache or from
    # AMO, checked against the lock), and stops the release when it differs or the package cannot be had.
    python3 -I "$repo/scripts/upstream/refresh_extensions_lock.py" --check-registry
    python3 -I "$repo/scripts/build/make_distribution.py" --out "$install/distribution"
    python3 -I "$repo/scripts/build/make_tools.py" --out "$install/nulavio-tools"
}

sbom() {
    local file
    for file in "$out"/packages/x86_64/nulavio-*.rpm "$out"/packages/nulavio_*.deb; do
        python3 -I "$repo/scripts/release/sbom.py" --package "$file" --engine-version "$version" > "$file.cdx.json"
    done
}

step verify-source python3 -I "$repo/scripts/upstream/verify_firefox_release.py" "$version"
step build "$repo/scripts/build/build_nulavio.sh" "$version"
step install install_tree
step unit-tests python3 -I "$repo/tests/run.py" unit
step integration-tests "$repo/scripts/release/run_integration.sh" "$install"
step rpm "$repo/scripts/release/make_rpm.sh" "$out/packages"
# shellcheck disable=SC2016 # the inner bash expands $0 and $1 (the checker and the package directory)
step check-rpm bash -c '"$0" "$1"/x86_64/nulavio-*.rpm' "$repo/scripts/release/check_rpm.sh" "$out/packages"
step deb "$repo/scripts/release/make_deb.sh" "$out/packages"
# shellcheck disable=SC2016 # as above
step check-deb bash -c '"$0" "$1"/nulavio_*.deb' "$repo/scripts/release/check_deb.sh" "$out/packages"
step signed-repository "$repo/scripts/release/test_signed_repo.sh" "$out/packages"
step kms-signing "$repo/scripts/release/test_kms_signing.sh"
step archive "$repo/scripts/release/make_archive.sh" "$install" "$out/packages/nulavio-$version-$NULAVIO_RELEASE.linux-x86_64.tar.xz"
step sbom sbom

# <out>/manifest.json: what this rehearsal verified, built and checked. Signing
# takes only the files listed there, with these digests (autobuild.py checks it).
# source_sha256 is the digest the built source tree was extracted from
# (fetch_firefox_source.py's marker); it must be the one Mozilla signed above.
manifest() {
    python3 -I - "$out" "$version" "$repo" "$work/firefox-$version" <<'EOF'
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

out, version, repo, tree = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
log = (out / "logs" / "verify-source.log").read_text(encoding="utf-8")
subkey = re.search(r"\(subkey ([0-9A-F]{16,40})\)", log)
digest = re.search(r"^([0-9a-f]{64})  source/firefox-" + re.escape(version) + r"\.source\.tar\.xz$", log, re.M)
if not (subkey and digest):
    sys.exit("manifest: verify-source.log has no verified source digest")
try:
    built = (tree / ".nulavio-source-sha256").read_text(encoding="ascii").strip()
except (OSError, UnicodeDecodeError):
    built = ""
if not re.fullmatch(r"[0-9a-f]{64}", built):
    sys.exit(f"manifest: {tree} has no verified digest (.nulavio-source-sha256): refusing")
if built != digest.group(1):
    sys.exit(f"manifest: {tree} was extracted from {built}, Mozilla signed {digest.group(1)}: refusing")


def sha256(path):
    hashed = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def git(*args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


packages = sorted(
    [*out.glob("packages/x86_64/nulavio-*.rpm"), *out.glob("packages/nulavio_*.deb"), *out.glob("packages/nulavio-*.linux-x86_64.tar.xz")]
)
sboms = sorted(out.glob("packages/**/*.cdx.json"))
if not packages:
    sys.exit("manifest: no packages to list")
engine = json.loads((Path(repo) / "browser" / "build" / "engine.json").read_text(encoding="utf-8"))
manifest = {
    "firefox": version,
    "source_sha256": built,
    "signing_subkey": subkey.group(1),
    "engine_json": {"firefox": engine.get("firefox"), "source_sha256": engine.get("source_sha256")},
    "nulavio_base_commit": git("rev-parse", "HEAD").decode().strip(),
    "worktree_diff_sha256": hashlib.sha256(git("diff", "HEAD", "--binary")).hexdigest(),
    "untracked": sorted(git("ls-files", "--others", "--exclude-standard").decode().splitlines()),
    "packages": [{"file": str(path.relative_to(out)), "sha256": sha256(path)} for path in packages],
    "sboms": [{"file": str(path.relative_to(out)), "sha256": sha256(path)} for path in sboms],
    "rehearsal": "ok",
    "finished_at": datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"manifest: {len(packages)} packages, {len(sboms)} SBOMs")
EOF
}
step manifest manifest

total=$(( $(date +%s) - start ))
printf '\nTotal: %d h %02d min, against the 72-hour target from Mozilla'"'"'s release (stretch: 24 h).\nNot rehearsed: signing with the release key and publishing (they need the key and the host).\n' \
    $((total / 3600)) $(( (total % 3600) / 60 )) >> "$report"
cat "$report"
