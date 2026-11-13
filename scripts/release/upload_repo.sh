#!/usr/bin/env bash
# Upload a signed repository that publish_release.sh staged, the dnf one (<stage>/rpm)
# or the APT one (<stage>/apt), to the Cloudflare R2 bucket served at
# https://packages.nulavio.net/, with the S3 API. The directory's name says which.
#
#   R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… R2_ACCOUNT=<account id> \
#       scripts/release/upload_repo.sh <stage>/rpm|<stage>/apt
#
# The token is the bucket-scoped "nulavio-packages-upload" (Object Read & Write on
# nulavio-packages only). The release workflow passes it from the `release`
# environment; any AWS credentials already set (the KMS signing role) are not used.
# Order: the packages and the hash-named metadata files first, the signed metadata
# last, so the signed metadata never names a file that is not there yet:
# - dnf: everything else, then repomd.xml.asc, then repomd.xml;
# - APT: pool/ and the indexes (apt fetches them by hash, from by-hash/), then
#   Release and Release.gpg, then InRelease, which apt reads first.
# Nothing is deleted: older packages and indexes stay, and the new metadata no longer
# lists them.
set -euo pipefail

repo=$(realpath "${1:?usage: upload_repo.sh <stage>/rpm|<stage>/apt}")
: "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_ACCOUNT:?set R2_ACCOUNT to the Cloudflare account id}"
bucket=${NULAVIO_R2_BUCKET:-nulavio-packages}
kind=$(basename "$repo")
case $kind in
    rpm)
        for file in repodata/repomd.xml repodata/repomd.xml.asc nulavio-packages.asc; do
            [[ -s $repo/$file ]] || { echo "upload_repo: $repo/$file is missing: not a signed repository" >&2; exit 2; }
        done
        compgen -G "$repo/x86_64/nulavio-*.rpm" >/dev/null || { echo "upload_repo: no package in $repo/x86_64" >&2; exit 2; }
        ;;
    apt)
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

s3() {
    # R2 does not take the AWS CLI's default request checksums on every operation.
    env -u AWS_SESSION_TOKEN -u AWS_PROFILE -u AWS_DEFAULT_PROFILE \
        AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_PAGER= \
        AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
        AWS_REGION=auto AWS_DEFAULT_REGION=auto \
        AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required \
        aws --endpoint-url "https://$R2_ACCOUNT.r2.cloudflarestorage.com" s3 "$@" --only-show-errors
}
if [[ $kind == rpm ]]; then
    s3 sync "$repo" "s3://$bucket/rpm/" --exclude "repodata/repomd.xml" --exclude "repodata/repomd.xml.asc"
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
