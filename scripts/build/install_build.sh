#!/usr/bin/env bash
# Install the engine build_nulavio.sh made into <dest>/nulavio: the packaged tree, the
# distribution policies and the Nulavio tools, as rehearse_release.sh's install step does.
#
#   scripts/build/install_build.sh <firefox-version> <dest>
set -euo pipefail

version=${1:?usage: install_build.sh <firefox-version> <dest>}
dest=${2:?dest}
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=${NULAVIO_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build}
tarball=$(find "$work/firefox-$version/obj-nulavio/dist" -maxdepth 1 -name 'nulavio-*.tar.xz' -printf '%T@ %p\n' | sort -rn | head -1 | cut -d' ' -f2-)
[[ -n $tarball ]] || { echo "install_build: no packaged build of Firefox $version in $work" >&2; exit 2; }
rm -rf "$dest/nulavio"
mkdir -p "$dest"
tar -xJf "$tarball" -C "$dest"
python3 -I "$repo/scripts/build/make_distribution.py" --out "$dest/nulavio/distribution"
python3 -I "$repo/scripts/build/make_tools.py" --out "$dest/nulavio/nulavio-tools"
echo "install_build: $dest/nulavio"
