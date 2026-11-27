#!/usr/bin/env bash
# Record the site's scenes from a Nulavio build and compose them, in one command (#173, #176).
#
#   scripts/site/record_site.sh <install-dir>
#
# <install-dir> is the directory that holds the `nulavio` executable (a release package unpacked, or a
# development package of this tree). It is the only argument: the scenes, the languages and the output
# directory (docs/design/recordings/2026-11) are fixed in scripts/site/record_site.py.
# 1. capture: tests/integration/record_site_scenes.py in the release test container
#    (ci/containers/fedora-release-itest.Containerfile, through scripts/release/run_integration.sh),
#    frames and timelines into <work>/recordings/;
# 2. compose: scripts/site/record_site.py compose on this host (Pillow and ffmpeg; no engine), which
#    replaces the output directory with the whole set, or leaves it as it was.
# The capture runs the engine: on a machine whose test slot is shared, queue it as an integration module
# instead, and run step 2 by hand on the artifacts directory.
# When a step fails, its files are kept and their directory is printed. A capture in which a scene
# failed is not composed: the set is made whole or not at all. When it is compose that failed, the
# command that runs it again on the same captures is printed.
set -euo pipefail
unset CDPATH

[[ $# -eq 1 ]] || { echo "usage: record_site.sh <install-dir>" >&2; exit 2; }
install=$(realpath -- "$1")
repo=$(cd -- "$(dirname -- "$0")/../.." && pwd)
cache=${XDG_CACHE_HOME:-$HOME/.cache}
mkdir -p -- "$cache"
work=$(mktemp -d -- "$cache/nulavio-record.XXXXXX")
step=capture
finish() {
    local status=$?
    if [[ $status -eq 0 ]]; then
        rm -rf -- "$work"
        return
    fi
    printf 'record_site: the %s failed (status %d); its files are kept in %s\n' "$step" "$status" "$work/recordings" >&2
    if [[ $step == compose ]]; then
        printf 'record_site: compose them again with: python3 -I %q compose %q\n' \
            "$repo/scripts/site/record_site.py" "$work/recordings" >&2
    fi
}
trap finish EXIT

NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS="$work" \
    "$repo/scripts/release/run_integration.sh" "$install" record_site_scenes.py
step=compose
python3 -I "$repo/scripts/site/record_site.py" compose "$work/recordings"
