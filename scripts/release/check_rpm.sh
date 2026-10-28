#!/usr/bin/env bash
# Install a Nulavio RPM in a clean, disposable Fedora container and check it:
# dependencies resolve from Fedora's repositories, files are root-owned and not
# writable by users, the browser starts headless and renders a page, and the
# Nulavio tools answer. Nothing touches the host.
#
#   scripts/release/check_rpm.sh dist/packages/x86_64/nulavio-<v>.rpm
set -euo pipefail

rpm=$(realpath "${1:?usage: check_rpm.sh <nulavio.rpm>}")
here=$(cd "$(dirname "$0")" && pwd)
lib=$(cd "$here/../../tests/lib" && pwd)
image=${NULAVIO_CHECK_IMAGE:-$("$here/base_image.sh" fedora-build)}

podman run --rm --security-opt label=disable -v "$here/sysdir_probe.py:/checks/sysdir_probe.py:ro" -v "$lib:/checks/lib:ro" -v "$rpm:/pkg/nulavio.rpm:ro" "$image" bash -euc '
    dnf -y -q install /pkg/nulavio.rpm >/dev/null
    echo "installed: $(rpm -q nulavio)"
    rpm -V nulavio && echo "rpm -V: files as packaged"
    bad=$(find /usr/lib64/nulavio \( ! -user root -o -perm -o+w -o -perm -g+w \) -print | head -5)
    [ -z "$bad" ] || { echo "not root-owned or writable: $bad"; exit 1; }
    echo "ownership: root, not writable by users"
    useradd -m tester
    su tester -c "printf \"<title>ok</title><p>Nulavio package check</p>\" > /tmp/page.html"
    su tester -c "nulavio --version"
    su tester -c "timeout 120 nulavio --headless --screenshot /tmp/shot.png file:///tmp/page.html" >/dev/null 2>&1 || true
    [ -s /tmp/shot.png ] && echo "headless start: rendered a page ($(stat -c %s /tmp/shot.png) bytes)" || { echo "headless start failed"; exit 1; }
    mkdir -p /usr/lib64/mozilla/native-messaging-hosts   # as a password manager package would
    sysdir=$(su tester -c "python3 -I /checks/sysdir_probe.py /checks/lib")
    [ "$sysdir" = "/usr/lib64/mozilla" ] && echo "system Mozilla directory read: $sysdir" || { echo "reads $sysdir, expected /usr/lib64/mozilla"; exit 1; }
    answer=$(su tester -c "printf %s \"{}\" | /usr/lib64/nulavio/nulavio-tools/bin/nulavio temporary api")
    [ "$answer" = "{\"error\": \"bad-request\"}" ] && echo "nulavio-tools: answer" || { echo "nulavio-tools: $answer"; exit 1; }
    test -f /usr/share/applications/nulavio.desktop && test -f /usr/share/icons/hicolor/128x128/apps/nulavio.png && echo "desktop entry and icons: present"
'
