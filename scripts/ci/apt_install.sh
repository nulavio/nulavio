#!/usr/bin/env bash
# Install Ubuntu packages on a CI runner, with a second mirror when the runner's own one
# cannot be reached (GitHub's runners could not resolve azure.archive.ubuntu.com for hours
# on 2026-11-11, failing every job that installs a package). The packages and their
# signatures are the same on every Ubuntu mirror: apt checks them against the runner's
# Ubuntu archive keys either way.
#
#   scripts/ci/apt_install.sh <package>...
set -euo pipefail
(( $# )) || { echo "usage: apt_install.sh <package>..." >&2; exit 2; }

install() { sudo apt-get update -q && sudo apt-get install -y -q --no-install-recommends "$@"; }
install "$@" && exit 0
echo "::warning title=apt::the runner's Ubuntu mirror failed; trying mirrors.edge.kernel.org"
if [[ -f /etc/apt/apt-mirrors.txt ]]; then
    printf '%s\n' http://mirrors.edge.kernel.org/ubuntu/ | sudo tee /etc/apt/apt-mirrors.txt >/dev/null
else
    sudo sed -i -E 's#https?://[a-z0-9.]*archive\.ubuntu\.com/ubuntu/?#http://mirrors.edge.kernel.org/ubuntu/#g' \
        /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true
fi
install "$@"
