#!/usr/bin/env bash
# Record the site's scenes from a Nulavio build and compose them, in one command (#173, #176).
#
#   scripts/site/record_site.sh <install-dir> [out-dir]
#
# <install-dir> holds the `nulavio` executable (a release package or a development package of this tree).
# 1. capture: tests/integration/record_site_scenes.py in the release test container
#    (ci/containers/fedora-release-itest.Containerfile, through scripts/release/run_integration.sh),
#    frames and timelines into <work>/recordings/;
# 2. compose: scripts/site/record_site.py compose on this host (Pillow and ffmpeg; no engine), into
#    [out-dir] (default docs/design/recordings/2026-11).
# The capture runs the engine: on a machine whose test slot is shared, queue it as an integration module
# instead, and run step 2 by hand on the artifacts directory.
# When a step fails, the captures are kept and their directory is printed: the scenes that were recorded
# can be composed again without running the browser.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
install=$(realpath "${1:?usage: record_site.sh <install-dir> [out-dir]}")
out=${2:-$repo/docs/design/recordings/2026-11}
cache=${XDG_CACHE_HOME:-$HOME/.cache}
mkdir -p "$cache"
work=$(mktemp -d "$cache/nulavio-record.XXXXXX")
finish() {
    local status=$?
    if [[ $status -eq 0 ]]; then
        rm -rf "$work"
    else
        echo "record_site: failed (status $status); the captures are kept in $work/recordings" >&2
        echo "record_site: compose them again with: python3 -I scripts/site/record_site.py compose $work/recordings" >&2
    fi
}
trap finish EXIT

NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS="$work" \
    "$repo/scripts/release/run_integration.sh" "$install" record_site_scenes.py
python3 -I "$repo/scripts/site/record_site.py" compose "$work/recordings" --out "$out"
