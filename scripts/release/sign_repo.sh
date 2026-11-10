#!/usr/bin/env bash
# Sign Nulavio RPMs and build a signed dnf repository, in a disposable Fedora
# container. The private key never enters the repository or an image: the
# container reads it from GNUPGHOME (mounted read-only into a private copy).
#
#   GNUPGHOME=~/.gnupg scripts/release/sign_repo.sh <packages-dir> <repo-out> <key-id>
#
# Output: <repo-out>/x86_64/*.rpm (signed), repodata/ (createrepo_c),
# repodata/repomd.xml.asc (detached signature), nulavio-packages.asc (public
# key) and nulavio.repo for users. Upload <repo-out> as it is, to the
# directory NULAVIO_REPO_BASEURL names (repodata/ sits at its top).
#
# With NULAVIO_RELEASE_MANIFEST=<rehearsal-out>/manifest.json (publish_release.sh
# sets it), every package in <packages-dir> must be listed there with the same
# SHA-256, or nothing is signed.
#
# The maintainer's release key is required for real releases. Tests run this
# with a throwaway key made for the test (tests/release/test_sign_repo.sh).
set -euo pipefail

packages=$(realpath "${1:?usage: sign_repo.sh <packages-dir> <repo-out> <key-id>}")
out=$(mkdir -p "${2:?repo-out}" && realpath "$2")
key=${3:?key id or fingerprint}
gnupg=$(realpath "${GNUPGHOME:-$HOME/.gnupg}")
baseurl=${NULAVIO_REPO_BASEURL:-https://packages.nulavio.net/rpm}
keyurl=${NULAVIO_REPO_KEYURL:-https://nulavio.net/keys/nulavio-packages.asc}
image=$("$(dirname "$0")/base_image.sh" fedora-build)

if [[ -n ${NULAVIO_RELEASE_MANIFEST:-} ]]; then
    python3 -I "$(dirname "$0")/release_manifest.py" packages "$NULAVIO_RELEASE_MANIFEST" "$packages" >/dev/null
fi

podman run --rm --security-opt label=disable \
    -v "$packages:/packages:ro" -v "$gnupg:/gnupg-ro:ro" -v "$out:/repo" "$image" bash -euc '
    dnf -y -q install rpm-sign createrepo_c gnupg2 >/dev/null 2>&1 || { echo "sign_repo: dnf failed" >&2; exit 1; }
    export GNUPGHOME=$(mktemp -d); cp -a /gnupg-ro/. "$GNUPGHOME"/; chmod 700 "$GNUPGHOME"
    mkdir -p /repo/x86_64
    find /packages -name "nulavio-*.rpm" -exec cp {} /repo/x86_64/ \;
    rpmsign --define "_gpg_name '"$key"'" --addsign /repo/x86_64/*.rpm >/dev/null
    createrepo_c --quiet /repo
    gpg --batch --yes --local-user "'"$key"'" --detach-sign --armor /repo/repodata/repomd.xml
    gpg --batch --yes --armor --export "'"$key"'" > /repo/nulavio-packages.asc
    printf "%s\n" "[nulavio]" "name=Nulavio" "baseurl='"$baseurl"'" "enabled=1" \
        "gpgcheck=1" "repo_gpgcheck=1" "gpgkey='"$keyurl"'" > /repo/nulavio.repo
    rm -rf "$GNUPGHOME"
'
echo "signed repository in $out"
