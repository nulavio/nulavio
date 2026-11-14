#!/usr/bin/env bash
# Build Nulavio Companion's release APK twice, from two fresh copies of android/ in
# different folders, and require the same bytes (ADR 0005: the APK is reproducible;
# ADR 0014: what is signed is what anyone can rebuild). Writes, for the release:
#
#   <out>/nulavio-companion-<version>-unsigned.apk
#   <out>/nulavio-companion-<version>.apk.cdx.json    (CycloneDX SBOM, sbom.py --companion)
#
#   JAVA_HOME=<jdk 21> scripts/release/build_companion.sh <out>
#
# <version> is the app's versionName in android/app/build.gradle.kts. Gradle and every
# dependency are checked against gradle/verification-metadata.xml by the build itself.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=$(mkdir -p "${1:?usage: build_companion.sh <out>}" && realpath "$1")
[[ -n ${JAVA_HOME:-} ]] || { echo "build_companion: set JAVA_HOME to a JDK 21" >&2; exit 2; }
version=$(sed -n 's/^ *versionName = "\([0-9][0-9.]*\)".*/\1/p' "$repo/android/app/build.gradle.kts")
[[ $version =~ ^[0-9]+(\.[0-9]+)+$ ]] || { echo "build_companion: no versionName in android/app/build.gradle.kts" >&2; exit 1; }
# Another APK under the same name and versionCode as the last release's is refused (#286).
python3 -I "$repo/scripts/release/companion_version.py" --repo "$repo" >&2
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

for copy in first second; do
    mkdir -p "$work/$copy"
    # A clean copy of what git tracks under android/, nothing a local build left behind.
    git -C "$repo" archive --format=tar HEAD android | tar -x -C "$work/$copy"
    "$work/$copy/android/gradlew" -p "$work/$copy/android" --no-daemon -q :app:assembleRelease
done
first=$work/first/android/app/build/outputs/apk/release/app-release-unsigned.apk
second=$work/second/android/app/build/outputs/apk/release/app-release-unsigned.apk
cmp -s "$first" "$second" || { echo "build_companion: the two builds differ: the APK is not reproducible" >&2; exit 1; }

cp "$first" "$out/nulavio-companion-$version-unsigned.apk"
python3 -I "$repo/scripts/release/sbom.py" --companion >"$out/nulavio-companion-$version.apk.cdx.json"
echo "build_companion: nulavio-companion-$version-unsigned.apk, the same bytes from two builds ($(sha256sum "$first" | cut -c1-16)…)"
