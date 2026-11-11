#!/usr/bin/env bash
# Build the Nulavio RPM from the installed Track B tree, in a disposable rootless
# Fedora container. Nothing is installed on the host; rpm-build lives only in
# the container. Signing is a separate step (scripts/release/sign_repo.sh) that
# needs the maintainer's key.
#
#   scripts/release/make_rpm.sh [out-dir]      (default: dist/packages)
#
# NULAVIO_INSTALL_DIR  the built tree (default ~/.cache/nulavio-build/install/nulavio)
# NULAVIO_RELEASE      package release (default 0.1; rehearse_release.sh sets the next one)
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
install_dir=${NULAVIO_INSTALL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build/install/nulavio}
out=$(mkdir -p "${1:-$repo/dist/packages}" && cd "${1:-$repo/dist/packages}" && pwd)
release=${NULAVIO_RELEASE:-0.1}
image=$("$repo/scripts/release/base_image.sh" fedora-build)

[[ -x $install_dir/nulavio && -d $install_dir/nulavio-tools && -f $install_dir/distribution/policies.json ]] || {
    echo "make_rpm: $install_dir is not a complete Nulavio tree (engine, nulavio-tools, distribution)" >&2
    exit 2
}
version=$(sed -n 's/^Version=//p' "$install_dir/application.ini")
work=$(mktemp -d "${TMPDIR:-/tmp}/nulavio-rpm-XXXXXX")
trap 'rm -rf "$work"' EXIT

mkdir "$work/tree"
cp -a "$install_dir" "$work/tree/nulavio"
cp "$repo/LICENSE" "$repo/LICENSES.md" "$work/tree/nulavio/"
find "$work/tree" -name __pycache__ -prune -exec rm -rf {} +
tar -C "$work/tree" --owner=0 --group=0 --sort=name -cf "$work/nulavio-tree.tar" nulavio
cp "$repo/packaging/rpm/nulavio.spec" "$repo/packaging/linux/nulavio.desktop" "$work/"

podman run --rm --security-opt label=disable -v "$work:/work:ro" -v "$out:/out" "$image" bash -euc '
    dnf -y -q install rpm-build >/dev/null 2>&1 || { echo "make_rpm: dnf failed" >&2; exit 1; }
    rpmbuild -bb /work/nulavio.spec --quiet \
        --define "_topdir /tmp/rpmbuild" --define "_sourcedir /work" --define "_rpmdir /out" \
        --define "nulavio_version '"$version"'" --define "nulavio_release '"$release"'"
'
find "$out" -name "nulavio-$version-$release*.rpm" -newer "$work/nulavio.spec" -print
