#!/usr/bin/env bash
# End-to-end check of the APT repository tooling, without AWS: sign_apt_repo.sh in
# its KMS mode builds and signs a repository for a test package, with a THROWAWAY
# RSA-4096 key whose private part only a stand-in `aws` command holds (the role KMS
# plays). Then, in a clean Ubuntu container, apt installs the package with the
# site's source file pointed at that repository and key, and copies of the
# repository with an altered index, an altered InRelease, or signed by another key
# are refused. Proves apt accepts what the KMS signer makes, through the release
# scripts.
#
#   scripts/release/test_apt_repo.sh
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
image=$("$repo_root/scripts/release/base_image.sh" ubuntu-itest)
work=$(mktemp -d "${TMPDIR:-/tmp}/nulavio-apttest-XXXXXX")
export GNUPGHOME="$work/gnupg"
trap 'gpgconf --kill gpg-agent 2>/dev/null; rm -rf "$work"' EXIT
mkdir -m 700 "$GNUPGHOME" "$work/aws" "$work/aws/bin" "$work/packages"

gpg --batch --quiet --pinentry-mode loopback --passphrase "" \
    --quick-gen-key "Nulavio throwaway test key <test@nulavio.invalid>" rsa4096 sign 1d 2>/dev/null
fpr=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr/ {print $10; exit}')
gpg --batch --armor --export "$fpr" >"$work/key.asc"
gpg --batch --pinentry-mode loopback --passphrase "" --export-secret-keys "$fpr" |
    python3 -I -c '
import base64, json, sys
sys.path[:0] = [sys.argv[1] + "/tests/unit", sys.argv[1] + "/scripts/release"]
import test_openpgp_sign as t
n, e, d = t.secret_numbers(sys.stdin.buffer.read())
json.dump({"n": n, "d": d, "spki": base64.b64encode(t.spki(n, e)).decode()}, open(sys.argv[2] + "/kms.json", "w"))
open(sys.argv[2] + "/fake_aws.py", "w").write(t.FAKE_AWS)
' "$repo_root" "$work/aws"
gpgconf --kill gpg-agent
rm -rf "$GNUPGHOME"   # from here on only the stand-in KMS can sign
printf '%s\n' '#!/bin/sh' \
    "FAKE_KMS_KEY='$work/aws/kms.json' FAKE_KMS_LOG='$work/aws/kms.log' exec python3 '$work/aws/fake_aws.py' \"\$@\"" >"$work/aws/bin/aws"
chmod 755 "$work/aws/bin/aws"

# A test package named like Nulavio's, with no dependencies.
podman run --rm --security-opt label=disable -v "$work/packages:/out" "$image" bash -euc '
    mkdir -p /tmp/pkg/DEBIAN /tmp/pkg/usr/share/nulavio-apt-test
    echo ok >/tmp/pkg/usr/share/nulavio-apt-test/ok
    printf "%s\n" "Package: nulavio" "Version: 1.0-0.1" "Architecture: amd64" "Maintainer: Test <test@nulavio.invalid>" \
        "Description: APT signing test" " Test package." >/tmp/pkg/DEBIAN/control
    dpkg-deb --root-owner-group --build /tmp/pkg /out/nulavio_1.0-0.1_amd64.deb >/dev/null
    chown "$(stat -c %u:%g /out)" /out/*.deb
'

NULAVIO_KMS_KEY_ID=alias/nulavio-test NULAVIO_PUBLIC_KEY="$work/key.asc" NULAVIO_TEST_AWS_DIR="$work/aws" \
    "$repo_root/scripts/release/sign_apt_repo.sh" "$work/packages" "$work/repo" "$fpr" >/dev/null
grep -q '"kms", "sign"' "$work/aws/kms.log" || { echo "test_apt_repo: the stand-in KMS was never asked to sign" >&2; exit 1; }

# The published site/apt/nulavio.sources, pointed at this local repository and the throwaway key.
python3 -I - "$repo_root/site/apt/nulavio.sources" "$work/key.asc" "$work/nulavio.sources" <<'PY'
import sys
lines = open(sys.argv[1], encoding="ascii").read().splitlines()
key = [" " + (line or ".") for line in open(sys.argv[2], encoding="ascii").read().strip("\n").split("\n")]
out, skipping = [], False
for line in lines:
    if line.startswith(" ") and skipping:
        continue
    skipping = line == "Signed-By:"
    out.append("URIs: file:///repo" if line.startswith("URIs: ") else line)
    if skipping:
        out.extend(key)
open(sys.argv[3], "w", encoding="ascii").write("\n".join(out) + "\n")
PY

install_from() {
    podman run --rm --security-opt label=disable -v "$1:/repo:ro" -v "$work/nulavio.sources:/nulavio.sources:ro" "$image" bash -euc '
        export DEBIAN_FRONTEND=noninteractive
        rm -f /etc/apt/sources.list.d/* /etc/apt/sources.list   # this repository alone, no network
        cp /nulavio.sources /etc/apt/sources.list.d/nulavio.sources
        apt-get -q -o APT::Update::Error-Mode=any update >/tmp/update.log 2>&1 ||
            { echo "refused: $(grep -m1 "^E:" /tmp/update.log)"; exit 3; }
        apt-get -q install -y nulavio >/tmp/install.log 2>&1 || { echo "refused at install: $(grep -m1 "^E:" /tmp/install.log)"; exit 3; }
        [ "$(dpkg-query -W -f="\${Version}" nulavio)" = 1.0-0.1 ] && echo installed
    ' 2>/dev/null || true
}
result=$(install_from "$work/repo")
[[ $result == installed ]] || { echo "test_apt_repo: the signed repository was not accepted ($result)" >&2; exit 1; }

index=dists/stable/main/binary-amd64
# An index changed after signing, in every form apt may fetch (plain, gz, xz, by hash).
cp -a "$work/repo" "$work/index"
sed -i 's/^Version: 1.0-0.1/Version: 1.0-0.2/' "$work/index/$index/Packages"
gzip -9nc "$work/index/$index/Packages" >"$work/index/$index/Packages.gz"
xz -9c "$work/index/$index/Packages" >"$work/index/$index/Packages.xz"
for f in "$work/index/$index"/by-hash/*/*; do
    case $(file -b --mime-type "$f") in
        text/plain) cp "$work/index/$index/Packages" "$f" ;;
        application/gzip) cp "$work/index/$index/Packages.gz" "$f" ;;
        application/x-xz) cp "$work/index/$index/Packages.xz" "$f" ;;
        *) echo "test_apt_repo: unexpected index $f" >&2; exit 1 ;;
    esac
done
cp -a "$work/repo" "$work/package"   # the package changed after signing
printf x >>"$work/package/pool/main/n/nulavio/nulavio_1.0-0.1_amd64.deb"
cp -a "$work/repo" "$work/inrelease"   # the signed text changed
sed -i 's/^Suite: stable/Suite: stablx/' "$work/inrelease/dists/stable/InRelease"
rm -f "$work/inrelease/dists/stable/Release" "$work/inrelease/dists/stable/Release.gpg"
for name in index package inrelease; do
    result=$(install_from "$work/$name")
    [[ $result == refused* ]] || { echo "test_apt_repo: a repository with a changed $name was accepted ($result)" >&2; exit 1; }
    echo "changed $name: $result"
done

# Signed by another key: the source file names the release key only.
export GNUPGHOME="$work/other"
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --pinentry-mode loopback --passphrase "" \
    --quick-gen-key "Another key <other@nulavio.invalid>" rsa3072 sign 1d 2>/dev/null
other=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr/ {print $10; exit}')
"$repo_root/scripts/release/sign_apt_repo.sh" "$work/packages" "$work/otherkey" "$other" >/dev/null
gpgconf --kill gpg-agent
result=$(install_from "$work/otherkey")
[[ $result == refused* ]] || { echo "test_apt_repo: a repository signed by another key was accepted ($result)" >&2; exit 1; }
echo "another key: $result"

echo "signed through sign_apt_repo.sh and a stand-in KMS: apt installs it with the site's source file, and refuses a changed index, a changed package, a changed InRelease and another key"
