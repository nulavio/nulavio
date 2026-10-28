#!/usr/bin/env bash
# End-to-end check of the signed repository tooling with a THROWAWAY key made
# for this run (no passphrase, expires in a day, deleted afterwards): sign the
# package and the metadata, install from the repository in a clean container
# with gpgcheck and repo_gpgcheck on, then confirm a tampered repository is
# refused. Real releases use the maintainer's key.
#
#   scripts/release/test_signed_repo.sh <packages-dir>
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
image=$("$repo_root/scripts/release/base_image.sh" fedora-build)
packages=$(realpath "${1:?usage: test_signed_repo.sh <packages-dir>}")
work=$(mktemp -d "${TMPDIR:-/tmp}/nulavio-signtest-XXXXXX")
trap 'rm -rf "$work"' EXIT
export GNUPGHOME="$work/gnupg"
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
    --quick-gen-key "Nulavio throwaway test key <test@nulavio.invalid>" rsa3072 sign 1d
fpr=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr/ {print $10; exit}')

NULAVIO_REPO_BASEURL=file:///repo NULAVIO_REPO_KEYURL=file:///repo/nulavio-packages.asc \
    "$repo_root/scripts/release/sign_repo.sh" "$packages" "$work/repo" "$fpr" >/dev/null
echo "signed with throwaway key ${fpr: -16}"

install_from() {
    podman run --rm --security-opt label=disable -v "$1:/repo:ro" "$image" bash -euc '
        cp /repo/nulavio.repo /etc/yum.repos.d/
        dnf -y -q install nulavio >/dev/null 2>&1 || { echo "refused"; exit 3; }
        rpm -K /repo/x86_64/nulavio-*.rpm | grep -q "signatures OK" && echo "installed with verified signatures"
    '
}
install_from "$work/repo"

cp -a "$work/repo" "$work/tampered"
sed -i 's|</repomd>| </repomd>|' "$work/tampered/repodata/repomd.xml"
if install_from "$work/tampered"; then
    echo "FAIL: a tampered repository was accepted" >&2
    exit 1
fi
echo "tampered metadata: refused"
