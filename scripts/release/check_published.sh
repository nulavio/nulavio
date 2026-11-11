#!/usr/bin/env bash
# After an upload: in a clean Fedora container, add the published repository file
# (the site's, https://nulavio.net/rpm/nulavio.repo), check that it keeps both
# signature checks on, install nulavio and require <version>-<release>. Retries for
# up to ten minutes, while caches still serve the previous metadata.
#
#   scripts/release/check_published.sh 160.0-0.3
set -euo pipefail

expected=${1:?usage: check_published.sh <version>-<release>}
image=$("$(dirname "$0")/base_image.sh" fedora-build)
repo_file=${NULAVIO_REPO_FILE:-https://nulavio.net/rpm/nulavio.repo}
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    got=$(podman run --rm --security-opt label=disable -e REPO_FILE="$repo_file" "$image" bash -euc '
        curl -fsSL --retry 3 "$REPO_FILE" -o /etc/yum.repos.d/nulavio.repo
        grep -qx "gpgcheck=1" /etc/yum.repos.d/nulavio.repo && grep -qx "repo_gpgcheck=1" /etc/yum.repos.d/nulavio.repo ||
            { echo "the repository file turns a signature check off"; exit 3; }
        dnf -y -q --refresh install nulavio >/dev/null 2>&1 || { echo "dnf refused or failed"; exit 4; }
        rpm -q --qf "%{VERSION}-%{RELEASE}\n" nulavio
    ' 2>&1 || true)
    if [[ $got == "$expected".* ]]; then
        echo "check_published: dnf installed nulavio $got from $repo_file with both signature checks on"
        exit 0
    fi
    echo "check_published: attempt $attempt: $got" >&2
    sleep 60
done
echo "check_published: the published repository does not install $expected" >&2
exit 1
