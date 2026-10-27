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
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=${NULAVIO_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build}
install="$work/install/nulavio"
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
step integration-tests env NULAVIO_ENGINE="$install/nulavio" python3 -I "$repo/tests/run.py" integration
step rpm "$repo/scripts/release/make_rpm.sh" "$out/packages"
# shellcheck disable=SC2016 # the inner bash expands $0 and $1 (the checker and the package directory)
step check-rpm bash -c '"$0" "$1"/x86_64/nulavio-*.rpm' "$repo/scripts/release/check_rpm.sh" "$out/packages"
step deb "$repo/scripts/release/make_deb.sh" "$out/packages"
# shellcheck disable=SC2016 # as above
step check-deb bash -c '"$0" "$1"/nulavio_*.deb' "$repo/scripts/release/check_deb.sh" "$out/packages"
step signed-repository "$repo/scripts/release/test_signed_repo.sh" "$out/packages"
step sbom sbom

total=$(( $(date +%s) - start ))
printf '\nTotal: %d h %02d min, against the 72-hour target from Mozilla'"'"'s release (stretch: 24 h).\nNot rehearsed: signing with the release key and publishing (they need the key and the host).\n' \
    $((total / 3600)) $(( (total % 3600) / 60 )) >> "$report"
cat "$report"
