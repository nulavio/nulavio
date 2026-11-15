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
#    sign_apt_repo.sh, the same way: the APT repository of the .deb (stage/apt/,
#    uploaded to https://packages.nulavio.net/apt/).
# 3. stage/github/: the signed RPM, the .deb, their SBOMs, the portable archive (Flatpak
#    source), the Flatpak bundle when given, manifest.json, the public key, SHA256SUMS and
#    its detached signature (assets of the GitHub release).
# 4. stage/NEXT.md: the upload, tag and release commands for this version.
#
# NULAVIO_FLATPAK_BUNDLE: nulavio-<version>.x86_64.flatpak, built by the release workflow's
# flatpak job from this rehearsal's portable archive (optional; SHA256SUMS covers it).
#
# NULAVIO_COMPANION_APK: nulavio-companion-<version>.apk, signed and checked by
# sign_companion.sh, with <apk>.cdx.json beside it. Required when the build offers phone
# pairing (nulavio.vault.phone.pairing in the branding prefs): ADR 0005's release order.
#
# NULAVIO_PUBLISH_REF: the reviewed branch the rehearsed commit must be on
# (default origin/main). A security release is prepared in a private GitHub
# advisory fork and merged into main when it is published: name that branch.
#
# Fedora (RPM, dnf) and Ubuntu (.deb, APT): a release without its .deb is refused, so
# that Ubuntu users never miss an update the Fedora repository has.
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
[[ -n $(field debs) ]] || { echo "publish_release: the rehearsal has no .deb: the APT repository would miss $tag" >&2; exit 2; }
commit=$(field commit)
firefox=$(field firefox)
bundle=${NULAVIO_FLATPAK_BUNDLE:-}
if [[ -n $bundle ]] && { [[ $(basename "$bundle") != "nulavio-${tag#v}.x86_64.flatpak" ]] || [[ ! -f $bundle ]]; }; then
    echo "publish_release: $bundle is not the Flatpak bundle of $tag" >&2
    exit 2
fi
# Built by Flathub's builder in a job with no attestation: signed only if it is the archive this release
# attested, with what flatpak_manifest.py adds (#324). In CI the flatpak-check job checked it, in a job that cannot
# sign, and this compares its hash (NULAVIO_FLATPAK_BUNDLE_SHA256); by hand, it is checked here.
if [[ -n $bundle ]]; then
    if [[ -n ${NULAVIO_FLATPAK_BUNDLE_SHA256:-} ]]; then
        [[ $(sha256sum "$bundle" | cut -d' ' -f1) == "$NULAVIO_FLATPAK_BUNDLE_SHA256" ]] || {
            echo "publish_release: $bundle is not the bundle the check accepted" >&2
            exit 2
        }
    elif ! python3 -I "$repo/scripts/release/check_flatpak_bundle.py" --bundle "$bundle" \
        --archive "$out/packages/nulavio-${tag#v}.linux-x86_64.tar.xz"; then
        echo "publish_release: $bundle is not the release's portable archive with what flatpak_manifest.py adds" >&2
        exit 2
    fi
fi
# ADR 0005's release order, ADR 0014: a build that offers to pair a phone ships the app it pairs
# with, signed (sign_companion.sh) and next to its SBOM.
# Fails closed: the prefs must be readable and must name the pref, true or false.
apk=${NULAVIO_COMPANION_APK:-}
pairing='^[[:space:]]*pref\("nulavio\.vault\.phone\.pairing",[[:space:]]*'
branding=$(git -C "$repo" show "$commit:browser/branding/nulavio/pref/firefox-branding.js") &&
    [[ $(grep -Ec "${pairing}(true|false)\);" <<<"$branding") == 1 ]] || {
    echo "publish_release: cannot tell whether $tag offers phone pairing (nulavio.vault.phone.pairing in firefox-branding.js)" >&2
    exit 2
}
if grep -Eq "${pairing}true\);" <<<"$branding" && [[ -z $apk ]]; then
    echo "publish_release: $tag offers phone pairing but no signed Companion APK was given (NULAVIO_COMPANION_APK)" >&2
    exit 2
fi
# The name and the SBOM only: sign_companion.sh signed it and checked it with apksigner just before.
if [[ -n $apk ]] && { [[ ! $(basename "$apk") =~ ^nulavio-companion-[0-9]+(\.[0-9]+)+\.apk$ ]] || [[ ! -f $apk ]] || [[ ! -f $apk.cdx.json ]]; }; then
    echo "publish_release: $apk is not a Companion APK with its SBOM (nulavio-companion-<version>.apk)" >&2
    exit 2
fi

mkdir -p "$stage/github"
NULAVIO_RELEASE_MANIFEST="$out/manifest.json" GNUPGHOME=$gnupg NULAVIO_PUBLIC_KEY=$published \
    "$repo/scripts/release/sign_repo.sh" "$out/packages" "$stage/rpm" "$key"
exported=$(fingerprint "$stage/rpm/nulavio-packages.asc")
[[ $exported == "$key" ]] || { echo "publish_release: the repository was signed with $exported" >&2; exit 1; }
NULAVIO_RELEASE_MANIFEST="$out/manifest.json" GNUPGHOME=$gnupg NULAVIO_PUBLIC_KEY=$published \
    "$repo/scripts/release/sign_apt_repo.sh" "$out/packages" "$stage/apt" "$key"

while IFS= read -r rpm; do
    cp "$stage/rpm/x86_64/$(basename "$rpm")" "$stage/github/"
    cp "$out/$rpm.cdx.json" "$stage/github/"
done < <(field rpms)
while IFS= read -r deb; do
    cp "$out/$deb" "$out/$deb.cdx.json" "$stage/github/"
done < <(field debs)
while IFS= read -r archive; do
    [[ -n $archive ]] && cp "$out/$archive" "$stage/github/"
done < <(field archives)
[[ -n $bundle ]] && cp "$bundle" "$stage/github/"
[[ -n $apk ]] && cp "$apk" "$apk.cdx.json" "$stage/github/"
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

1. Upload the dnf and APT repositories (packages first, signed metadata last):

       scripts/release/upload_repo.sh "$stage/rpm"
       scripts/release/upload_repo.sh "$stage/apt"

   Then install from each, in a clean container, with the signature checks on:

       scripts/release/check_published.sh ${tag#v}

   The APT check needs https://nulavio.net/apt/nulavio.sources to be byte for byte
   this commit's site/apt/nulavio.sources: a change to that file is deployed by the
   site workflow before a release runs.

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
