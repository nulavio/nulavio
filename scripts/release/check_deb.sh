#!/usr/bin/env bash
# Install a Nulavio .deb in a clean, disposable Ubuntu container and check it, as
# check_rpm.sh does for Fedora: dependencies resolve from Ubuntu's archive, files
# are root-owned and not writable by users, the browser starts headless and
# renders a page, the Nulavio tools answer, the AppArmor profile parses.
#
#   scripts/release/check_deb.sh dist/packages/nulavio_<v>_amd64.deb
set -euo pipefail

deb=$(realpath "${1:?usage: check_deb.sh <nulavio.deb>}")
image=${NULAVIO_CHECK_DEB_IMAGE:-docker.io/library/ubuntu:26.10}

here=$(cd "$(dirname "$0")" && pwd)
lib=$(cd "$here/../../tests/lib" && pwd)

podman run --rm --security-opt label=disable -v "$here/sysdir_probe.py:/checks/sysdir_probe.py:ro" -v "$lib:/checks/lib:ro" -v "$deb:/pkg/nulavio.deb:ro" "$image" bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    { apt-get -qq update && apt-get -qq install -y /pkg/nulavio.deb; } >/dev/null 2>&1 || { echo "apt install failed"; exit 1; }
    echo "installed: $(dpkg-query -W -f="\${Package} \${Version}" nulavio)"
    dpkg --verify nulavio && echo "dpkg --verify: files as packaged"
    bad=$(find /usr/lib/nulavio \( ! -user root -o -perm -o+w -o -perm -g+w \) -print | head -5)
    [ -z "$bad" ] || { echo "not root-owned or writable: $bad"; exit 1; }
    echo "ownership: root, not writable by users"
    useradd -m tester
    su tester -c "printf \"<title>ok</title><p>Nulavio package check</p>\" > /tmp/page.html"
    su tester -c "nulavio --version"
    su tester -c "timeout 120 nulavio --headless --screenshot /tmp/shot.png file:///tmp/page.html" >/dev/null 2>&1 || true
    [ -s /tmp/shot.png ] && echo "headless start: rendered a page ($(stat -c %s /tmp/shot.png) bytes)" || { echo "headless start failed"; exit 1; }
    # The AppArmor profile (Ubuntu 24.04+ user-namespace restriction): installed, and valid for the parser.
    { apt-get -qq install -y apparmor; } >/dev/null 2>&1 || { echo "apt install apparmor failed"; exit 1; }
    [ -f /etc/apparmor.d/nulavio ] || { echo "AppArmor profile missing"; exit 1; }
    apparmor_parser -Q -K /etc/apparmor.d/nulavio && echo "AppArmor profile: parses (userns for /usr/lib/nulavio/nulavio)"
    mkdir -p /usr/lib/mozilla/native-messaging-hosts   # as a password manager package would
    sysdir=$(su tester -c "python3 -I /checks/sysdir_probe.py /checks/lib")
    [ "$sysdir" = "/usr/lib/mozilla" ] && echo "system Mozilla directory read: $sysdir" || { echo "reads $sysdir, expected /usr/lib/mozilla"; exit 1; }
    answer=$(su tester -c "printf %s \"{}\" | /usr/lib/nulavio/nulavio-tools/bin/nulavio temporary api")
    [ "$answer" = "{\"error\": \"bad-request\"}" ] && echo "nulavio-tools: answer" || { echo "nulavio-tools: $answer"; exit 1; }
'
