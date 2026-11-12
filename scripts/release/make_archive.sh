#!/usr/bin/env bash
# The installed tree as the portable archive (GitHub release asset; the Flatpak is built
# from it): nulavio/ with the licenses, without bytecode caches. The same tree gives the
# same bytes: entries sorted, owner 0, modes without the umask, one time for every file (the
# commit's), and xz on
# one thread.
#
#   scripts/release/make_archive.sh <install-dir> <out.tar.xz>
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
install=$(realpath "${1:?usage: make_archive.sh <install-dir> <out.tar.xz>}")
out=${2:?out file}
[[ -x $install/nulavio && -f $install/application.ini ]] || { echo "make_archive: $install is not an installed Nulavio tree" >&2; exit 2; }
stamp=$(git -C "$repo" log -1 --format=%ct)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp -a "$install" "$tmp/nulavio"
cp "$repo/LICENSE" "$repo/LICENSES.md" "$tmp/nulavio/"
find "$tmp" -name __pycache__ -prune -exec rm -rf {} +
tar -C "$tmp" --sort=name --owner=0 --group=0 --numeric-owner --mode='u+rwX,go+rX,go-w' --mtime="@$stamp" -cf - nulavio | xz -T1 -6 > "$out"
