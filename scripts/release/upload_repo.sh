#!/usr/bin/env bash
# Upload a signed repository that publish_release.sh staged, the dnf one (<stage>/rpm)
# or the APT one (<stage>/apt), to the Cloudflare R2 bucket served at
# https://packages.nulavio.net/, with the S3 API. The directory's name says which.
#
#   R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… R2_ACCOUNT=<account id> \
#       scripts/release/upload_repo.sh <stage>/rpm|<stage>/apt
#
# The token is the bucket-scoped "nulavio-packages-upload" (Object Read & Write on
# nulavio-packages only). The release workflow passes it from the `release-upload`
# environment; any AWS credentials already set (the KMS signing role) are not used.
# Order: the packages and the hash-named metadata files first, the signed metadata
# last, so the signed metadata never names a file that is not there yet:
# - dnf: everything else, then the signed pair under keys named after the revision
#   (repodata/<firefox>-<release>/repomd.xml.asc and repomd.xml, #740), then the served
#   repomd.xml.asc, then repomd.xml. A publish that stops between those two leaves the new
#   signature beside the old repomd.xml, which dnf and the build job refuse; the revision's
#   pair is still in the bucket, and the runbook copies it onto the served keys;
# - APT: pool/ and the indexes (apt fetches them by hash, from by-hash/), then
#   Release and Release.gpg, then InRelease, which apt reads first.
# Nothing is deleted: older packages and indexes stay, and the new metadata no longer
# lists them.
# Nothing is overwritten with other bytes either (#656): before the first write, every
# package staged here that the bucket already holds under its name is downloaded and
# compared. The same bytes pass (the same run's publish job, run again); other bytes stop
# the upload (exit 3) with the object's upload time: another run uploaded this revision
# and stopped before its draft. The runbook step: docs/architecture/build.md, "After a
# failed publish".
set -euo pipefail

repo=$(realpath "${1:?usage: upload_repo.sh <stage>/rpm|<stage>/apt}")
: "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_ACCOUNT:?set R2_ACCOUNT to the Cloudflare account id}"
bucket=${NULAVIO_R2_BUCKET:-nulavio-packages}
kind=$(basename "$repo")
case $kind in
    rpm)
        pool=x86_64
        for file in repodata/repomd.xml repodata/repomd.xml.asc nulavio-packages.asc; do
            [[ -s $repo/$file ]] || { echo "upload_repo: $repo/$file is missing: not a signed repository" >&2; exit 2; }
        done
        compgen -G "$repo/x86_64/nulavio-*.rpm" >/dev/null || { echo "upload_repo: no package in $repo/x86_64" >&2; exit 2; }
        # The revision names the pair's keys: <firefox>-<release> from nulavio-<firefox>-<release>.<dist>.x86_64.rpm,
        # as release_manifest.py's tag gives it (without the v), one for every package staged here.
        revision=
        for package in "$repo"/x86_64/nulavio-*.rpm; do
            name=$(basename "$package")
            if [[ ! $name =~ ^nulavio-([0-9]+(\.[0-9]+)+-[0-9]+(\.[0-9]+)*)\.[[:lower:]][[:lower:][:digit:]_]*\.x86_64\.rpm$ ]]; then
                echo "upload_repo: $name does not name a revision (nulavio-<firefox>-<release>.<dist>.x86_64.rpm)" >&2
                exit 2
            fi
            if [[ -n $revision && ${BASH_REMATCH[1]} != "$revision" ]]; then
                echo "upload_repo: the packages in $repo/x86_64 carry more than one revision ($revision, ${BASH_REMATCH[1]})" >&2
                exit 2
            fi
            revision=${BASH_REMATCH[1]}
        done
        ;;
    apt)
        pool=pool/main/n/nulavio
        for file in dists/stable/Release dists/stable/Release.gpg dists/stable/InRelease dists/stable/main/binary-amd64/Packages; do
            [[ -s $repo/$file ]] || { echo "upload_repo: $repo/$file is missing: not a signed repository" >&2; exit 2; }
        done
        compgen -G "$repo/pool/main/n/nulavio/nulavio_*.deb" >/dev/null || { echo "upload_repo: no package in $repo/pool" >&2; exit 2; }
        ;;
    *)
        echo "upload_repo: $repo is neither a staged rpm/ nor apt/ directory" >&2
        exit 2
        ;;
esac

r2() {
    # R2 does not take the AWS CLI's default request checksums on every operation.
    env -u AWS_SESSION_TOKEN -u AWS_PROFILE -u AWS_DEFAULT_PROFILE \
        AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_PAGER= \
        AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
        AWS_REGION=auto AWS_DEFAULT_REGION=auto \
        AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required \
        aws --endpoint-url "https://$R2_ACCOUNT.r2.cloudflarestorage.com" "$@"
}
s3() { r2 s3 "$@" --only-show-errors; }

# The packages the bucket already holds under this repository's pool, as "<key><TAB><upload time>" lines.
# Assigned, not read through a pipe, so that a failed listing stops the script before anything is written.
listing=$(r2 s3api list-objects-v2 --bucket "$bucket" --prefix "$kind/$pool/" --output json)
held=$(python3 -I -c '
import json, sys
listing = json.load(sys.stdin)
for entry in listing.get("Contents") or []:
    print(entry["Key"], entry["LastModified"], sep="\t")
' <<<"$listing")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for package in "$repo/$pool"/nulavio[-_]*.{rpm,deb}; do
    [[ -f $package ]] || continue
    name=$(basename "$package")
    key=$kind/$pool/$name
    uploaded=$(awk -F '\t' -v key="$key" '$1 == key { print $2; exit }' <<<"$held")
    [[ -n $uploaded ]] || continue
    s3 cp "s3://$bucket/$key" "$tmp/$name"
    theirs=$(sha256sum "$tmp/$name" | cut -d' ' -f1)
    ours=$(sha256sum "$package" | cut -d' ' -f1)
    rm -f "$tmp/$name"
    if [[ $theirs != "$ours" ]]; then
        echo "upload_repo: $bucket/$key, uploaded $uploaded, holds other bytes (sha256 $theirs) than this run's $name" \
            "($ours): another release run uploaded this revision and stopped before its draft. Nothing of $repo was uploaded." \
            "Re-run that run's publish job while its signed files last (7 days); a new run would stop here too." \
            "See docs/architecture/build.md, \"After a failed publish\", before starting another run." >&2
        exit 3
    fi
done

if [[ $kind == rpm ]]; then
    s3 sync "$repo" "s3://$bucket/rpm/" --exclude "repodata/repomd.xml" --exclude "repodata/repomd.xml.asc"
    s3 cp "$repo/repodata/repomd.xml.asc" "s3://$bucket/rpm/repodata/$revision/repomd.xml.asc"
    s3 cp "$repo/repodata/repomd.xml" "s3://$bucket/rpm/repodata/$revision/repomd.xml"
    s3 cp "$repo/repodata/repomd.xml.asc" "s3://$bucket/rpm/repodata/repomd.xml.asc"
    s3 cp "$repo/repodata/repomd.xml" "s3://$bucket/rpm/repodata/repomd.xml"
else
    s3 sync "$repo" "s3://$bucket/apt/" --exclude "dists/stable/Release" --exclude "dists/stable/Release.gpg" \
        --exclude "dists/stable/InRelease"
    s3 cp "$repo/dists/stable/Release" "s3://$bucket/apt/dists/stable/Release"
    s3 cp "$repo/dists/stable/Release.gpg" "s3://$bucket/apt/dists/stable/Release.gpg"
    s3 cp "$repo/dists/stable/InRelease" "s3://$bucket/apt/dists/stable/InRelease"
fi
echo "upload_repo: $repo uploaded to $bucket/$kind"
