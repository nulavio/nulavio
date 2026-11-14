#!/usr/bin/env bash
# Sign Nulavio RPMs and build a signed dnf repository, in a disposable Fedora
# container. The private key never enters the container. Two signers:
#
# - The release key in AWS KMS (NULAVIO_KMS_KEY_ID set: key ID, ARN or alias).
#   scripts/release/openpgp_sign.py makes the OpenPGP signatures and KMS does the
#   RSA operation; rpm 6 calls it as its signer. AWS credentials reach the
#   container as environment variables: the ones already set (CI, after
#   aws-actions/configure-aws-credentials), or exported from AWS_PROFILE (the
#   maintainer's SSO session). The public key is NULAVIO_PUBLIC_KEY (default
#   site/keys/nulavio-packages.asc), and its full fingerprint must be the one given.
#
#       NULAVIO_KMS_KEY_ID=alias/nulavio-release AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 \
#           scripts/release/sign_repo.sh <packages-dir> <repo-out> <fingerprint>
#
# - The gpg-agent of GNUPGHOME on the host (otherwise), through its "extra"
#   socket (GnuPG's socket for use from another machine), mounted into the
#   container. A key with a passphrase is asked for there, with the host's
#   pinentry, or taken from that agent's cache. Only the public key is copied in.
#
#       GNUPGHOME=~/.gnupg scripts/release/sign_repo.sh <packages-dir> <repo-out> <fingerprint>
#
# Output: <repo-out>/x86_64/*.rpm (signed), repodata/ (createrepo_c),
# repodata/repomd.xml.asc (detached signature) and nulavio-packages.asc (public
# key). Upload <repo-out> as it is, to the directory NULAVIO_REPO_BASEURL names
# (repodata/ sits at its top).
#
# No nulavio.repo here: that file decides whether dnf checks signatures, so it
# must not live where the packages are uploaded (anyone who can write the bucket
# could turn the checks off). It is site/rpm/nulavio.repo, served by the site
# (https://nulavio.net/rpm/nulavio.repo) from the reviewed git tree.
#
# With NULAVIO_RELEASE_MANIFEST=<rehearsal-out>/manifest.json (publish_release.sh
# sets it), the rehearsal must pass `release_manifest.py verify` (finished, from a
# committed tree on NULAVIO_PUBLISH_REF, default origin/main, a newer version, the
# packages carrying their own notes) and every package in <packages-dir> must be
# listed there with the same SHA-256, or nothing is signed. The release key (the
# one in site/keys/nulavio-packages.asc) and a real KMS key sign only that way:
# without a manifest they are refused (#292).
#
# The maintainer's release key is required for real releases. Tests run this
# with a throwaway key made for the test (test_signed_repo.sh for the gpg-agent,
# test_kms_signing.sh for KMS, with a stand-in `aws` from NULAVIO_TEST_AWS_DIR).
set -euo pipefail

release=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$release/../.." && pwd)
packages=$(realpath "${1:?usage: sign_repo.sh <packages-dir> <repo-out> <fingerprint>}")
out=$(mkdir -p "${2:?repo-out}" && realpath "$2")
key=${3:?the full 40-character fingerprint}
image=$("$release/base_image.sh" fedora-build)

fingerprint() {
    python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import openpgp_sign as o; print(o.primary_key(open(sys.argv[2], "rb").read()).hex)' \
        "$release" "$1"
}
# Before anything is signed: a checked rehearsal, which the release key and a real KMS key never go without.
checked() {
    local signer=${1^^} manifest=${NULAVIO_RELEASE_MANIFEST:-} released
    [[ $signer =~ ^[0-9A-F]{40}$ ]] || { echo "sign_repo: cannot tell which key signs (${1:-no fingerprint})" >&2; exit 2; }
    # An assignment of its own, so a key file that cannot be read stops the script (set -e) instead of comparing to "".
    released=$(fingerprint "$repo/site/keys/nulavio-packages.asc")
    if [[ -z $manifest ]]; then
        if [[ $signer == "$released" ]] ||
            { [[ -n ${NULAVIO_KMS_KEY_ID:-} ]] && [[ -z ${NULAVIO_TEST_AWS_DIR:-} ]]; }; then
            echo "sign_repo: the release key signs only a checked rehearsal: set NULAVIO_RELEASE_MANIFEST=<rehearsal-out>/manifest.json" >&2
            exit 2
        fi
        return 0
    fi
    [[ $(basename "$manifest") == manifest.json ]] || { echo "sign_repo: $manifest is not a rehearsal's manifest.json" >&2; exit 2; }
    python3 -I "$release/release_manifest.py" verify "$(dirname "$manifest")" --repo "$repo" --on "${NULAVIO_PUBLISH_REF:-origin/main}" >/dev/null
    python3 -I "$release/release_manifest.py" packages "$manifest" "$packages" >/dev/null
}

public=$(mktemp -d)
trap 'rm -rf "$public"' EXIT

if [[ -n ${NULAVIO_KMS_KEY_ID:-} ]]; then
    cp "${NULAVIO_PUBLIC_KEY:-$repo/site/keys/nulavio-packages.asc}" "$public/key.asc"
    fpr=$(fingerprint "$public/key.asc")
    [[ ${key^^} == "$fpr" ]] || { echo "sign_repo: the public key is $fpr, not $key (give the full fingerprint)" >&2; exit 1; }
    checked "$fpr"
    container_env=(-e NULAVIO_KMS_KEY_ID -e NULAVIO_SIGN_FPR="$fpr")
    mounts=(-v "$release:/nulavio-release:ro")
    if [[ -n ${NULAVIO_TEST_AWS_DIR:-} ]]; then
        mounts+=(-v "$(realpath "$NULAVIO_TEST_AWS_DIR"):/opt/aws:ro")
        container_env+=(-e NULAVIO_TEST_AWS=1)
    else
        if [[ -z ${AWS_ACCESS_KEY_ID:-} ]]; then
            # Short-lived credentials of the current session (SSO), as variables: never on a command line.
            eval "$(aws configure export-credentials --format env)"
        fi
        : "${AWS_REGION:?set AWS_REGION to the region of the KMS key}"
        export AWS_REGION
        container_env+=(-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e AWS_REGION)
    fi
    podman run --rm --security-opt label=disable "${container_env[@]}" "${mounts[@]}" \
        -v "$packages:/packages:ro" -v "$public:/public:ro" -v "$out:/repo" "$image" bash -euc '
        tools="rpm-sign createrepo_c python3"
        [[ -n ${NULAVIO_TEST_AWS:-} ]] && export PATH=/opt/aws/bin:$PATH || tools="$tools awscli2"
        dnf -y -q install $tools >/dev/null 2>&1 || { echo "sign_repo: dnf failed" >&2; exit 1; }
        signer="/usr/bin/python3 -I /nulavio-release/openpgp_sign.py --public-key /public/key.asc --kms-key-id $NULAVIO_KMS_KEY_ID"
        mkdir -p /repo/x86_64
        find /packages -name "nulavio-*.rpm" -exec cp {} /repo/x86_64/ \;
        rpmsign --define "_openpgp_sign kms" --define "_openpgp_sign_id $NULAVIO_SIGN_FPR" \
            --define "__kms_sign_cmd() $signer -o %{shescape:%{2}} -- %{shescape:%{1}}" --addsign /repo/x86_64/*.rpm >/dev/null
        createrepo_c --quiet /repo
        $signer --armor -o /repo/repodata/repomd.xml.asc /repo/repodata/repomd.xml
        cp /public/key.asc /repo/nulavio-packages.asc
'
    echo "signed repository in $out (AWS KMS)"
    exit 0
fi

gnupg=$(realpath "${GNUPGHOME:-$HOME/.gnupg}")
gpg-connect-agent --homedir "$gnupg" /bye >/dev/null
agent=$(gpgconf --homedir "$gnupg" --list-dirs agent-extra-socket)
[[ -S $agent ]] || { echo "sign_repo: no gpg-agent extra socket for $gnupg" >&2; exit 1; }
gpg --homedir "$gnupg" --batch --armor --export "$key" >"$public/key.asc"
[[ -s $public/key.asc ]] || { echo "sign_repo: no public key $key in $gnupg" >&2; exit 1; }
# The full fingerprint, and exactly that key: an e-mail or a short id can name several keys, and gpg's
# --export and --local-user need not pick the same one.
[[ ${key^^} =~ ^[0-9A-F]{40}$ ]] || { echo "sign_repo: give the full 40-character fingerprint, not $key" >&2; exit 2; }
fpr=$(fingerprint "$public/key.asc")
[[ $fpr == "${key^^}" ]] || { echo "sign_repo: the public key exported for $key is ${fpr:-unreadable}" >&2; exit 1; }
checked "$fpr"

podman run --rm --security-opt label=disable \
    -v "$packages:/packages:ro" -v "$public:/public:ro" -v "$agent:/run/host-gpg-agent" -v "$out:/repo" "$image" bash -euc '
    dnf -y -q install rpm-sign createrepo_c gnupg2 >/dev/null 2>&1 || { echo "sign_repo: dnf failed" >&2; exit 1; }
    export GNUPGHOME=$(mktemp -d); chmod 700 "$GNUPGHOME"
    ln -s /run/host-gpg-agent "$GNUPGHOME/S.gpg-agent"
    gpg --batch --quiet --import /public/key.asc
    mkdir -p /repo/x86_64
    find /packages -name "nulavio-*.rpm" -exec cp {} /repo/x86_64/ \;
    rpmsign --define "_gpg_name '"$key"'" --addsign /repo/x86_64/*.rpm >/dev/null
    createrepo_c --quiet /repo
    gpg --batch --yes --local-user "'"$key"'" --detach-sign --armor /repo/repodata/repomd.xml
    gpg --batch --yes --armor --export "'"$key"'" > /repo/nulavio-packages.asc
    rm -rf "$GNUPGHOME"
'
echo "signed repository in $out"
