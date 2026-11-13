#!/usr/bin/env bash
# After an upload, install nulavio from what was published, the way a user does,
# and require <version>-<release>:
# - dnf, in a clean Fedora container, from the site's repository file
#   (https://nulavio.net/rpm/nulavio.repo), which must keep both signature checks on;
# - APT, in a clean Ubuntu container, from the site's source file
#   (https://nulavio.net/apt/nulavio.sources), which must be byte for byte the
#   reviewed site/apt/nulavio.sources (one stanza, the release key in Signed-By).
# Each retries for up to ten minutes, while caches still serve the previous metadata.
#
#   scripts/release/check_published.sh 160.0-0.4
set -euo pipefail

expected=${1:?usage: check_published.sh <version>-<release>}
here=$(dirname "$0")
repo=$(cd "$here/../.." && pwd)
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
    # The file that decides what apt trusts is checked here, whole, against the reviewed one, and
    # that exact copy is what the container uses.
    local sources
    sources=$(mktemp)
    curl -fsSL --proto '=https' --retry 3 "$sources_file" -o "$sources" || { echo "the source file could not be fetched"; rm -f "$sources"; return 0; }
    if ! cmp -s "$sources" "$repo/site/apt/nulavio.sources"; then
        echo "the published source file is not site/apt/nulavio.sources"
        rm -f "$sources"
        return 0
    fi
    chmod 0644 "$sources"
    podman run --rm --security-opt label=disable -v "$sources:/nulavio.sources:ro" "$ubuntu" bash -euc '
        export DEBIAN_FRONTEND=noninteractive
        { apt-get -qq update && apt-get -qq install -y ca-certificates; } >/dev/null 2>&1 || { echo "apt failed (Ubuntu archive)"; exit 5; }
        cp /nulavio.sources /etc/apt/sources.list.d/nulavio.sources
        # Any failed fetch or signature problem is an error, not a warning apt carries on past.
        apt-get -q -o APT::Update::Error-Mode=any update >/tmp/update.log 2>&1 || { echo "apt update refused or failed: $(tail -3 /tmp/update.log)"; exit 4; }
        apt-get -qq install -y nulavio >/dev/null 2>&1 || { echo "apt install failed"; exit 4; }
        dpkg-query -W -f="\${Version}\n" nulavio
    ' 2>&1 || true
    rm -f "$sources"
}

# rpm prints the distribution after the release (160.0-0.4.fc44); a .deb's version is exact.
matches() {
    case $1 in
        dnf*) [[ $2 == "$expected" || $2 == "$expected".fc* ]] ;;
        *) [[ $2 == "$expected" ]] ;;
    esac
}

check() {
    local name=$1 install=$2 got
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        got=$($install)
        if matches "$name" "$got"; then
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
