#!/usr/bin/env bash
# Sign the Companion's APK with its key in AWS KMS (ADR 0014) and check the result the way
# Android does, before it can be attached to a release:
#
#   NULAVIO_COMPANION_KMS_KEY_ID=alias/nulavio-companion \
#       scripts/release/sign_companion.sh <dir with nulavio-companion-<v>-unsigned.apk> <out>
#
# Writes <out>/nulavio-companion-<v>.apk and copies its SBOM next to it. apksigner (Android
# build-tools, found through ANDROID_HOME) must verify the v2 and v3 signatures, and the
# certificate must be the one published at site/keys/nulavio-companion.der.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
in=$(realpath "${1:?usage: sign_companion.sh <unsigned-dir> <out>}")
out=$(mkdir -p "${2:?out}" && realpath "$2")
key=${NULAVIO_COMPANION_KMS_KEY_ID:-alias/nulavio-companion}
cert=$repo/site/keys/nulavio-companion.der
shopt -s nullglob
unsigned=("$in"/nulavio-companion-*-unsigned.apk)
[[ ${#unsigned[@]} -eq 1 ]] || { echo "sign_companion: expected one nulavio-companion-<version>-unsigned.apk in $in" >&2; exit 2; }
name=$(basename "${unsigned[0]}" -unsigned.apk)
[[ $name =~ ^nulavio-companion-[0-9]+(\.[0-9]+)+$ ]] || { echo "sign_companion: unexpected name $name" >&2; exit 2; }
apksigner=$(find "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/nonexistent}}/build-tools" -name apksigner -type f 2>/dev/null | sort -V | tail -1 || true)
[[ -x $apksigner ]] || { echo "sign_companion: no apksigner under ANDROID_HOME/build-tools" >&2; exit 2; }

python3 -I "$repo/scripts/release/apk_sign.py" sign --certificate "$cert" --kms-key-id "$key" \
    -o "$out/$name.apk" "${unsigned[0]}"
report=$("$apksigner" verify --verbose --print-certs --min-sdk-version 24 "$out/$name.apk" 2>/dev/null) ||
    { echo "sign_companion: apksigner refuses $name.apk" >&2; rm -f "$out/$name.apk"; exit 1; }
want=$(sha256sum "$cert" | cut -d' ' -f1)
if ! grep -qx "Verified using v2 scheme (APK Signature Scheme v2): true" <<<"$report" ||
    ! grep -qx "Verified using v3 scheme (APK Signature Scheme v3): true" <<<"$report" ||
    ! grep -qx "Signer #1 certificate SHA-256 digest: $want\|V3.0 Signer: certificate SHA-256 digest: $want" <<<"$report"; then
    echo "sign_companion: $name.apk is not signed v2 and v3 by the published certificate $want" >&2
    rm -f "$out/$name.apk"
    exit 1
fi
cp "$in/$name.apk.cdx.json" "$out/"
echo "sign_companion: $name.apk signed and verified (certificate SHA-256 $want)"
