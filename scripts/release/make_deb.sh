#!/usr/bin/env bash
# Build the Nulavio .deb (Debian/Ubuntu) from the installed Track B tree, in a
# disposable rootless Ubuntu container. Same engine build as the RPM: the
# engine picks the system Mozilla directory the distribution has (patch 0006),
# so native-messaging hosts in /usr/lib/mozilla are read.
#
#   scripts/release/make_deb.sh [out-dir]      (default: dist/packages)
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
install_dir=${NULAVIO_INSTALL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build/install/nulavio}
out=$(mkdir -p "${1:-$repo/dist/packages}" && cd "${1:-$repo/dist/packages}" && pwd)
release=${NULAVIO_RELEASE:-0.1}
image=${NULAVIO_DEB_IMAGE:-docker.io/library/ubuntu:26.10}

[[ -x $install_dir/nulavio && -d $install_dir/nulavio-tools && -f $install_dir/distribution/policies.json ]] || {
    echo "make_deb: $install_dir is not a complete Nulavio tree" >&2
    exit 2
}
version=$(sed -n 's/^Version=//p' "$install_dir/application.ini")
work=$(mktemp -d "${TMPDIR:-/tmp}/nulavio-deb-XXXXXX")
trap 'rm -rf "$work"' EXIT

pkg="$work/pkg"
mkdir -p "$pkg/usr/lib" "$pkg/usr/bin" "$pkg/usr/share/applications" "$pkg/usr/share/doc/nulavio" "$pkg/DEBIAN"
cp -a "$install_dir" "$pkg/usr/lib/nulavio"
find "$pkg" -name __pycache__ -prune -exec rm -rf {} +
printf '#!/bin/sh\nexec /usr/lib/nulavio/nulavio "$@"\n' > "$pkg/usr/bin/nulavio"
chmod 0755 "$pkg/usr/bin/nulavio"
cp "$repo/packaging/linux/nulavio.desktop" "$pkg/usr/share/applications/"
for size in 16 32 48 64 128; do
    install -Dm0644 "$install_dir/browser/chrome/icons/default/default$size.png" \
        "$pkg/usr/share/icons/hicolor/${size}x${size}/apps/nulavio.png"
done
cp "$repo/LICENSE" "$pkg/usr/share/doc/nulavio/copyright"
# Ubuntu 24.04+: without a profile the engine may not create the user namespaces its content sandbox uses.
install -Dm0644 "$repo/packaging/linux/apparmor-nulavio" "$pkg/etc/apparmor.d/nulavio"
printf '/etc/apparmor.d/nulavio\n' > "$pkg/DEBIAN/conffiles"
cat > "$pkg/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
# Load the AppArmor profile now when AppArmor is active (as dh_apparmor does); a reboot loads it otherwise.
if [ "$1" = configure ] && [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null 2>&1; then
    apparmor_parser -r -T -W /etc/apparmor.d/nulavio || true
fi
POSTINST
cat > "$pkg/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = remove ] && [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null 2>&1; then
    apparmor_parser -R /etc/apparmor.d/nulavio 2>/dev/null || true
fi
POSTRM
chmod 0755 "$pkg/DEBIAN/postinst" "$pkg/DEBIAN/postrm"
cat > "$pkg/DEBIAN/control.in" <<CONTROL
Package: nulavio
Version: $version-$release
Architecture: amd64
Maintainer: Nulavio maintainers <security@nulavio.net>
Section: web
Priority: optional
Homepage: https://nulavio.net
Depends: @SHLIBS@, python3 (>= 3.12), util-linux
Recommends: libsodium23, gocryptfs, fuse3
Provides: www-browser
Description: Private, calm web browser built on the Gecko engine
 Nulavio keeps your data with you: strict tracking protection, uBlock Origin
 from the start, HTTPS-Only, no telemetry to Nulavio (there is no Nulavio
 server), separate profiles, encrypted profiles at rest, and an AI Bridge
 whose permissions you decide.
CONTROL

podman run --rm --security-opt label=disable -v "$work:/work" -v "$out:/out" "$image" bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    { apt-get -qq update && apt-get -qq install -y binutils apt-file && apt-file update; } >/dev/null 2>&1 \
        || { echo "make_deb: apt failed" >&2; exit 1; }
    cd /work
    tree=pkg/usr/lib/nulavio
    # Libraries the engine needs that it does not ship itself, mapped to the Ubuntu packages providing them.
    needed=$(find "$tree" -type f \( -name "*.so" -o -name nulavio-bin -o -name pingsender \) -exec readelf -d {} + 2>/dev/null \
        | sed -n "s/.*Shared library: \[\(.*\)\]/\1/p" | sort -u)
    deps=""
    for lib in $needed; do
        [ -e "$tree/$lib" ] && continue
        package=$(apt-file search -l -F "/usr/lib/x86_64-linux-gnu/$lib" | head -1)
        [ -n "$package" ] || { echo "make_deb: no package provides $lib" >&2; exit 1; }
        deps="$deps $package"
    done
    shlibs=$(printf "%s\n" $deps | sort -u | paste -sd, | sed "s/,/, /g")
    sed "s|@SHLIBS@|$shlibs|" pkg/DEBIAN/control.in > pkg/DEBIAN/control && rm pkg/DEBIAN/control.in
    dpkg-deb --root-owner-group -Zxz --build pkg "/out/nulavio_'"$version-$release"'_amd64.deb" >/dev/null
    grep "^Depends" pkg/DEBIAN/control
'
ls "$out/nulavio_$version-${release}_amd64.deb"
