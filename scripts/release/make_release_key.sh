#!/usr/bin/env bash
# Create the Nulavio package-signing key in a new, separate GnuPG home.
# The maintainer runs this once; gpg asks for the passphrase.
#
#   scripts/release/make_release_key.sh <new-gnupg-home>
#
# Writes into the repository only the PUBLIC key: site/keys/nulavio-packages.asc
# (served at https://nulavio.net/keys/nulavio-packages.asc). The private key,
# its revocation certificate and any backup stay in <new-gnupg-home>, which
# must be outside the repository. Prints the fingerprint for
# packaging/release.json and the backup steps.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
home=${1:?usage: make_release_key.sh <new-gnupg-home>}
uid="Nulavio package signing <security@nulavio.net>"
public="$repo/site/keys/nulavio-packages.asc"

home=$(realpath -m "$home")
case "$home/" in
"$repo"/*) echo "make_release_key: $home is inside the repository; choose a directory outside it" >&2; exit 2 ;;
esac
if [[ -e $home ]] && [[ -n $(ls -A "$home") ]]; then
    echo "make_release_key: $home is not empty; this script only creates a new key home" >&2
    exit 2
fi
if [[ -e $public ]]; then
    echo "make_release_key: $public exists; a second release key needs a decision (rotation), not this script" >&2
    exit 2
fi

mkdir -p "$(dirname "$home")"
[[ -d $home ]] || mkdir "$home"
chmod 700 "$home"
export GNUPGHOME=$home
# RSA 4096, signing only, two years: rpm (Sequoia) and apt both verify it.
gpg --quiet --quick-generate-key "$uid" rsa4096 sign 2y
fpr=$(gpg --with-colons --list-keys "$uid" | awk -F: '$1 == "fpr" { print $10; exit }')
mkdir -p "$(dirname "$public")"
gpg --armor --export "$fpr" >"$public"

cat <<EOF

Release key created.
  Fingerprint: $fpr
  Key home:    $home (private key; keep it off the repository)
  Public key:  $public (commit it; the site serves it)
  Revocation:  $home/openpgp-revocs.d/$fpr.rev

Next:
  1. Back up the private key and the revocation certificate offline, apart
     from each other, for example:
       GNUPGHOME=$home gpg --armor --export-secret-keys $fpr > <offline-media>/nulavio-release-secret.asc
     The passphrase goes in your password manager, not next to the backup.
  2. Put the fingerprint in packaging/release.json ("key_fingerprint").
  3. Sign with: GNUPGHOME=$home scripts/release/publish_release.sh <rehearsal-out> $fpr
EOF
