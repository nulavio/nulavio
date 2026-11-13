#!/usr/bin/env bash
# After an upload, install nulavio from what was published, the way a user does,
# and require <version>-<release>:
# - dnf, in a clean Fedora container, from the site's repository file
#   (https://nulavio.net/rpm/nulavio.repo), which must keep both signature checks on;
# - APT, in a clean Ubuntu container, from the site's source file
#   (https://nulavio.net/apt/nulavio.sources), which must name the key apt checks
#   InRelease with and never mark the repository trusted.
# Each retries for up to ten minutes, while caches still serve the previous metadata.
#
#   scripts/release/check_published.sh 160.0-0.4
set -euo pipefail

expected=${1:?usage: check_published.sh <version>-<release>}
here=$(dirname "$0")
fedora=$("$here/base_image.sh" fedora-build)
ubuntu=$("$here/base_image.sh" ubuntu-itest)
repo_file=${NULAVIO_REPO_FILE:-https://nulavio.net/rpm/nulavio.repo}
sources_file=${NULAVIO_SOURCES_FILE:-https://nulavio.net/apt/nulavio.sources}

dnf_install() {
    podman run --rm --security-opt label=disable -e REPO_FILE="$repo_file" "$fedora" bash -euc '
        curl -fsSL --retry 3 "$REPO_FILE" -o /etc/yum.repos.d/nulavio.repo
        grep -qx "gpgcheck=1" /etc/yum.repos.d/nulavio.repo && grep -qx "repo_gpgcheck=1" /etc/yum.repos.d/nulavio.repo ||
            { echo "the repository file turns a signature check off"; exit 3; }
        dnf -y -q --refresh install nulavio >/dev/null 2>&1 || { echo "dnf refused or failed"; exit 4; }
        rpm -q --qf "%{VERSION}-%{RELEASE}\n" nulavio
    ' 2>&1 || true
}

apt_install() {
    podman run --rm --security-opt label=disable -e SOURCES_FILE="$sources_file" "$ubuntu" bash -euc '
        export DEBIAN_FRONTEND=noninteractive
        { apt-get -qq update && apt-get -qq install -y ca-certificates curl; } >/dev/null 2>&1 || { echo "apt failed (Ubuntu archive)"; exit 5; }
        list=/etc/apt/sources.list.d/nulavio.sources
        curl -fsSL --retry 3 "$SOURCES_FILE" -o "$list"
        grep -qx "Signed-By:" "$list" && grep -qx " -----BEGIN PGP PUBLIC KEY BLOCK-----" "$list" ||
            { echo "the source file names no key"; exit 3; }
        ! grep -qiE "^(Trusted|Allow-Insecure|Allow-Weak|Allow-Downgrade-To-Insecure):" "$list" ||
            { echo "the source file turns a check off"; exit 3; }
        # Any failed fetch or signature problem is an error, not a warning apt carries on past.
        apt-get -q -o APT::Update::Error-Mode=any update >/tmp/update.log 2>&1 || { echo "apt update refused or failed: $(tail -3 /tmp/update.log)"; exit 4; }
        apt-get -qq install -y nulavio >/dev/null 2>&1 || { echo "apt install failed"; exit 4; }
        dpkg-query -W -f="\${Version}\n" nulavio
    ' 2>&1 || true
}

check() {
    local name=$1 install=$2 got
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        got=$($install)
        if [[ $got == "$expected" || $got == "$expected".* ]]; then
            echo "check_published: $name installed nulavio $got with the signature checks on"
            return 0
        fi
        echo "check_published: $name, attempt $attempt: $got" >&2
        sleep 60
    done
    echo "check_published: the published $name repository does not install $expected" >&2
    return 1
}

check "dnf ($repo_file)" dnf_install
check "APT ($sources_file)" apt_install
