#!/usr/bin/env bash
# Build a signed APT repository from Nulavio .deb packages: the indexes in a
# disposable Ubuntu container (apt-ftparchive), the signatures on this machine.
# The private key never enters the container. Two signers, as sign_repo.sh:
#
# - The release key in AWS KMS (NULAVIO_KMS_KEY_ID set: key ID, ARN or alias):
#   scripts/release/openpgp_sign.py makes the signatures and KMS does the RSA
#   operation (`aws` on PATH with credentials; NULAVIO_TEST_AWS_DIR/bin first, for
#   the tests' stand-in). The public key is NULAVIO_PUBLIC_KEY (default
#   site/keys/nulavio-packages.asc), and it must be <fingerprint>.
#
#       NULAVIO_KMS_KEY_ID=alias/nulavio-release AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 \
#           scripts/release/sign_apt_repo.sh <packages-dir> <repo-out> <fingerprint>
#
# - The gpg-agent of GNUPGHOME (otherwise): gpg signs with <fingerprint>.
#
# Output, uploaded as it is to https://packages.nulavio.net/apt/ (upload_repo.sh):
#
#   pool/main/n/nulavio/nulavio_<version>_amd64.deb
#   dists/stable/main/binary-amd64/Packages{,.gz,.xz} and by-hash/SHA256/<hash>
#   dists/stable/Release, Release.gpg (detached) and InRelease (cleartext-signed)
#
# Release says Acquire-By-Hash: apt then fetches each index by its hash, so a client
# that reads the old InRelease while a new one is uploaded still finds the indexes it
# names. Release carries no Valid-Until, as the dnf metadata carries no expiry: a
# release that waits for the maintainer's approval must not stop `apt update` for
# everyone meanwhile (R57 says what that leaves open).
#
# No .sources file here: that file decides whether apt checks signatures, so it must
# not live where the packages are uploaded. It is site/apt/nulavio.sources, served by
# the site (https://nulavio.net/apt/nulavio.sources) from the reviewed git tree.
#
# With NULAVIO_RELEASE_MANIFEST=<rehearsal-out>/manifest.json (publish_release.sh
# sets it), every package in <packages-dir> must be listed there with the same
# SHA-256, or nothing is signed.
#
# Real releases sign with the maintainer's release key. test_apt_repo.sh runs this
# with a throwaway key behind a stand-in KMS and installs from the result.
set -euo pipefail

release=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$release/../.." && pwd)
packages=$(realpath "${1:?usage: sign_apt_repo.sh <packages-dir> <repo-out> <fingerprint>}")
out=$(mkdir -p "${2:?repo-out}" && realpath "$2")
key=${3:?fingerprint}
image=${NULAVIO_APT_IMAGE:-$("$release/base_image.sh" ubuntu-itest)}
pinned='^[a-z0-9-]+(\.[a-z0-9-]+)+(:[0-9]+)?(/[a-z0-9._-]+)+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$'  # as base_image.sh
[[ $image =~ $pinned ]] || { echo "sign_apt_repo: the image must be registry/name:tag@sha256:digest, not $image" >&2; exit 2; }
suite=stable

[[ ${key^^} =~ ^[0-9A-F]{40}$ ]] || { echo "sign_apt_repo: give the full 40-character fingerprint" >&2; exit 2; }
key=${key^^}
compgen -G "$packages/nulavio_*.deb" >/dev/null || { echo "sign_apt_repo: no nulavio_*.deb in $packages" >&2; exit 2; }
[[ -z $(ls -A "$out") ]] || { echo "sign_apt_repo: $out is not empty" >&2; exit 2; }
if [[ -n ${NULAVIO_RELEASE_MANIFEST:-} ]]; then
    python3 -I "$release/release_manifest.py" packages "$NULAVIO_RELEASE_MANIFEST" "$packages" >/dev/null
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -m 700 "$tmp/gpg"
if [[ -n ${NULAVIO_KMS_KEY_ID:-} ]]; then
    cp "${NULAVIO_PUBLIC_KEY:-$repo/site/keys/nulavio-packages.asc}" "$tmp/key.asc"
else
    gnupg=$(realpath "${GNUPGHOME:-$HOME/.gnupg}")
    gpg --homedir "$gnupg" --batch --armor --export "$key" >"$tmp/key.asc"
fi
fpr=$(gpg --homedir "$tmp/gpg" --quiet --with-colons --show-keys "$tmp/key.asc" | awk -F: '$1 == "fpr" { print $10; exit }')
[[ $fpr == "$key" ]] || { echo "sign_apt_repo: the public key is ${fpr:-missing}, not $key" >&2; exit 1; }

mkdir -p "$out/pool/main/n/nulavio"
find "$packages" -maxdepth 1 -name 'nulavio_*.deb' -exec cp {} "$out/pool/main/n/nulavio/" \;
podman run --rm --security-opt label=disable -v "$out:/repo" "$image" bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    { apt-get -qq update && apt-get -qq install -y apt-utils xz-utils; } >/dev/null 2>&1 || { echo "sign_apt_repo: apt failed" >&2; exit 1; }
    cd /repo
    index=dists/'"$suite"'/main/binary-amd64
    mkdir -p "$index"
    apt-ftparchive packages pool >"$index/Packages"
    gzip -9nk "$index/Packages"
    xz -9k "$index/Packages"
    apt-ftparchive -o APT::FTPArchive::MD5=false -o APT::FTPArchive::SHA1=false -o APT::FTPArchive::DoByHash=true \
        -o APT::FTPArchive::Release::Origin=Nulavio -o APT::FTPArchive::Release::Label=Nulavio \
        -o APT::FTPArchive::Release::Suite='"$suite"' -o APT::FTPArchive::Release::Codename='"$suite"' \
        -o APT::FTPArchive::Release::Architectures=amd64 -o APT::FTPArchive::Release::Components=main \
        -o "APT::FTPArchive::Release::Description=Nulavio web browser" \
        release dists/'"$suite"' >/tmp/Release
    mv /tmp/Release dists/'"$suite"'/Release
    chown -R "$(stat -c %u:%g /repo)" /repo
'

dists=$out/dists/$suite
# What the container wrote, checked here before anything is signed: the .deb files are the ones
# given (and so, with a manifest, the ones the rehearsal checked), and the index lists exactly
# those, each once, with their SHA-256.
python3 -I - "$packages" "$out" "$suite" <<'PY' || { echo "sign_apt_repo: the repository does not hold exactly the packages given" >&2; exit 1; }
import hashlib, pathlib, sys
packages, out, suite = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
given = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in packages.glob("nulavio_*.deb")}
pool = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out / "pool").rglob("*") if p.is_file()}
assert pool == given, (pool, given)
entries = (out / "dists" / suite / "main" / "binary-amd64" / "Packages").read_text(encoding="utf-8").strip().split("\n\n")
listed = {}
for entry in entries:
    fields = dict(line.split(": ", 1) for line in entry.splitlines() if not line.startswith(" ") and ": " in line)
    name = fields["Filename"].rsplit("/", 1)[-1]
    assert fields["Package"] == "nulavio" and name not in listed, entry[:200]
    assert name == f"nulavio_{fields['Version']}_{fields['Architecture']}.deb", name
    listed[name] = fields["SHA256"]
assert listed == given, (listed, given)
PY
if [[ -n ${NULAVIO_KMS_KEY_ID:-} ]]; then
    # The tests' stand-in `aws` is put first on PATH for the signer alone, never for the checks below.
    signer_path=$PATH
    [[ -z ${NULAVIO_TEST_AWS_DIR:-} ]] || signer_path=$(realpath "$NULAVIO_TEST_AWS_DIR")/bin:$PATH
    sign=(env PATH="$signer_path" python3 -I "$release/openpgp_sign.py" --public-key "$tmp/key.asc" --kms-key-id "$NULAVIO_KMS_KEY_ID")
    "${sign[@]}" --clearsign -o "$dists/InRelease" "$dists/Release"
    "${sign[@]}" --armor -o "$dists/Release.gpg" "$dists/Release"
    signer="AWS KMS"
else
    gpg --homedir "$gnupg" --batch --yes --local-user "$key" --digest-algo SHA256 --clearsign -o "$dists/InRelease" "$dists/Release"
    gpg --homedir "$gnupg" --batch --yes --local-user "$key" --digest-algo SHA256 --armor --detach-sign -o "$dists/Release.gpg" "$dists/Release"
    signer="gpg"
fi

# Check both the way apt does, with only the public key, before anything leaves this machine.
gpg --homedir "$tmp/gpg" --quiet --dearmor -o "$tmp/keyring.gpg" "$tmp/key.asc"
gpgv --keyring "$tmp/keyring.gpg" "$dists/InRelease" 2>/dev/null ||
    { echo "sign_apt_repo: InRelease does not verify with $key" >&2; exit 1; }
gpgv --keyring "$tmp/keyring.gpg" "$dists/Release.gpg" "$dists/Release" 2>/dev/null ||
    { echo "sign_apt_repo: Release.gpg does not verify with $key" >&2; exit 1; }
gpgv --keyring "$tmp/keyring.gpg" --output "$tmp/signed" "$dists/InRelease" 2>/dev/null
cmp -s "$tmp/signed" "$dists/Release" || { echo "sign_apt_repo: InRelease does not carry Release as it is" >&2; exit 1; }
# And the way apt does on Ubuntu (sqv since 25.10, stricter than gpgv): an update from this
# repository alone, with the site's source file pointed at it, and each package fetched and checked
# against the index (downloaded only: its dependencies come from Ubuntu's archive, not this one).
sed -e 's|^URIs: .*|URIs: file:///repo|' -e '/^Signed-By:/,$d' "$repo/site/apt/nulavio.sources" >"$tmp/nulavio.sources"
printf 'Signed-By:\n' >>"$tmp/nulavio.sources"
sed -e 's/^$/./' -e 's/^/ /' "$tmp/key.asc" >>"$tmp/nulavio.sources"
podman run --rm --security-opt label=disable -v "$out:/repo:ro" -v "$tmp/nulavio.sources:/nulavio.sources:ro" "$image" bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    rm -f /etc/apt/sources.list.d/* /etc/apt/sources.list
    cp /nulavio.sources /etc/apt/sources.list.d/nulavio.sources
    apt-get -q -o APT::Update::Error-Mode=any update >/tmp/update.log 2>&1 || { tail -3 /tmp/update.log >&2; exit 1; }
    cd /tmp && apt-get -qq download nulavio >/tmp/fetch.log 2>&1 || { tail -3 /tmp/fetch.log >&2; exit 1; }
' || { echo "sign_apt_repo: apt refuses the signed repository" >&2; exit 1; }
echo "signed APT repository in $out ($signer)"
