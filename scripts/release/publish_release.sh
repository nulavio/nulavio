#!/usr/bin/env bash
# Sign a rehearsed release and stage everything that gets published.
# It does not upload, tag or create the GitHub release: it prints those commands.
#
#   GNUPGHOME=<key-home> scripts/release/publish_release.sh <rehearsal-out> <key-fingerprint> [stage-dir]
#
# or, with the release key in AWS KMS (credentials from AWS_PROFILE or the environment):
#
#   NULAVIO_KMS_KEY_ID=alias/nulavio-release AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 \
#       scripts/release/publish_release.sh <rehearsal-out> <key-fingerprint> [stage-dir]
#
# 1. release_manifest.py verify: the rehearsal finished, from a committed tree on
#    origin/main, and every package and SBOM still has the SHA-256 it recorded.
# 2. sign_repo.sh with NULAVIO_RELEASE_MANIFEST: signs only those RPMs and builds
#    the dnf repository (stage/rpm/, uploaded to https://packages.nulavio.net/rpm/).
# 3. stage/github/: the signed RPM, its SBOM, the portable archive (Flatpak source), the Flatpak
#    bundle when given, manifest.json, the public key, SHA256SUMS and its detached signature
#    (assets of the GitHub release).
# 4. stage/NEXT.md: the upload, tag and release commands for this version.
#
# NULAVIO_FLATPAK_BUNDLE: nulavio-<version>.x86_64.flatpak, built by the release workflow's
# flatpak job from this rehearsal's portable archive (optional; SHA256SUMS covers it).
#
# NULAVIO_PUBLISH_REF: the reviewed branch the rehearsed commit must be on
# (default origin/main). A security release is prepared in a private GitHub
# advisory fork and merged into main when it is published: name that branch.
#
# The alpha ships for Fedora only (RPM). The .deb stays unsigned and unpublished
# until there is an APT repository (decision of 2026-11-04).
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
out=$(realpath "${1:?usage: publish_release.sh <rehearsal-out> <key-fingerprint> [stage-dir]}")
key=${2:?key fingerprint}
stage=$(realpath -m "${3:-$out/publish}")
kms=${NULAVIO_KMS_KEY_ID:-}
if [[ -n $kms ]]; then
    gnupg=
    signer="AWS KMS ($kms)"
else
    gnupg=${GNUPGHOME:?set GNUPGHOME to the release key home, or NULAVIO_KMS_KEY_ID}
    signer="the gpg-agent of $gnupg"
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -m 700 "$tmp/gpg"
fingerprint() { gpg --homedir "$tmp/gpg" --quiet --with-colons --show-keys "$1" | awk -F: '$1 == "fpr" { print $10; exit }'; }

[[ $key =~ ^[0-9A-F]{40}$ ]] || { echo "publish_release: give the full 40-character fingerprint, upper case" >&2; exit 2; }
published=$repo/site/keys/nulavio-packages.asc
[[ -f $published ]] || { echo "publish_release: $published is missing: the public key must be in the repository first" >&2; exit 2; }
if [[ $(fingerprint "$published") != "$key" ]]; then
    echo "publish_release: $key is not the key in $published" >&2
    exit 2
fi
if [[ -e $stage ]] && [[ -n $(ls -A "$stage") ]]; then
    echo "publish_release: $stage is not empty" >&2
    exit 2
fi

ref=${NULAVIO_PUBLISH_REF:-origin/main}
git -C "$repo" fetch --quiet origin main
info=$(python3 -I "$repo/scripts/release/release_manifest.py" verify "$out" --repo "$repo" --on "$ref")
# Before anything is written: no package in the directory that the manifest does not list.
python3 -I "$repo/scripts/release/release_manifest.py" packages "$out/manifest.json" "$out/packages" >/dev/null
field() { python3 -I -c 'import json, sys; v = json.loads(sys.argv[1])[sys.argv[2]]; print(*v, sep="\n") if isinstance(v, list) else print(v)' "$info" "$1"; }
tag=$(field tag)
commit=$(field commit)
firefox=$(field firefox)
bundle=${NULAVIO_FLATPAK_BUNDLE:-}
if [[ -n $bundle ]] && { [[ $(basename "$bundle") != "nulavio-${tag#v}.x86_64.flatpak" ]] || [[ ! -f $bundle ]]; }; then
    echo "publish_release: $bundle is not the Flatpak bundle of $tag" >&2
    exit 2
fi

mkdir -p "$stage/github"
NULAVIO_RELEASE_MANIFEST="$out/manifest.json" GNUPGHOME=$gnupg NULAVIO_PUBLIC_KEY=$published \
    "$repo/scripts/release/sign_repo.sh" "$out/packages" "$stage/rpm" "$key"
exported=$(fingerprint "$stage/rpm/nulavio-packages.asc")
[[ $exported == "$key" ]] || { echo "publish_release: the repository was signed with $exported" >&2; exit 1; }

while IFS= read -r rpm; do
    cp "$stage/rpm/x86_64/$(basename "$rpm")" "$stage/github/"
    cp "$out/$rpm.cdx.json" "$stage/github/"
done < <(field rpms)
while IFS= read -r archive; do
    [[ -n $archive ]] && cp "$out/$archive" "$stage/github/"
done < <(field archives)
[[ -n $bundle ]] && cp "$bundle" "$stage/github/"
cp "$out/manifest.json" "$stage/github/manifest.json"
cp "$published" "$stage/github/nulavio-packages.asc"
(cd "$stage/github" && sha256sum -- * >SHA256SUMS)
if [[ -n $kms ]]; then
    python3 -I "$repo/scripts/release/openpgp_sign.py" --public-key "$published" --kms-key-id "$kms" \
        --armor -o "$stage/github/SHA256SUMS.asc" "$stage/github/SHA256SUMS"
else
    GNUPGHOME=$gnupg gpg --batch --yes --local-user "$key" --armor --detach-sign "$stage/github/SHA256SUMS"
fi
# Check the signature the way a user would: with only the published public key.
gpg --homedir "$tmp/gpg" --quiet --import "$published" 2>/dev/null
gpg --homedir "$tmp/gpg" --quiet --verify "$stage/github/SHA256SUMS.asc" "$stage/github/SHA256SUMS" 2>/dev/null ||
    { echo "publish_release: SHA256SUMS.asc does not verify with $published" >&2; exit 1; }

cat >"$stage/NEXT.md" <<EOF
# Publishing $tag (Firefox $firefox, commit ${commit:0:12})

Checked: the rehearsal manifest, the packages' SHA-256, the base commit on
$ref; signed with $key by $signer. Not done by the script: everything below.

1. Upload the dnf repository (the host decides the command; with Cloudflare R2):

       rclone sync --checksum "$stage/rpm" r2:nulavio-packages/rpm

   Then, in a clean Fedora container, install from it with both checks on:

       podman run --rm -it $("$repo/scripts/release/base_image.sh" fedora-build) bash -c \\
         'dnf -y config-manager addrepo --from-repofile=https://nulavio.net/rpm/nulavio.repo && dnf -y install nulavio && rpm -q nulavio'

2. Tag and create the GitHub release as a draft, review it, then publish it:

       git -C "$repo" tag -a "$tag" -m "Nulavio $tag (Firefox $firefox)" $commit
       git -C "$repo" push origin "$tag"
       gh release create "$tag" --draft --prerelease --verify-tag \\
         --title "Nulavio $tag (alpha)" --notes-file <notes.md> "$stage"/github/*

3. Set "version" in packaging/release.json to ${tag#v}, rebuild the site with
   scripts/site/build_site.py --release and upload it (the download pages appear).
4. Add the entry to docs/security/changelog.md (hours to "published").
EOF

echo "publish_release: $tag staged in $stage (nothing uploaded); next steps in $stage/NEXT.md"
