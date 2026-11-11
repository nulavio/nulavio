#!/usr/bin/env bash
# End-to-end check of signing through AWS KMS, without AWS: sign_repo.sh in its
# KMS mode signs a test package and the repository metadata, with a THROWAWAY
# RSA-4096 key whose private part only a stand-in `aws` command holds (the role
# KMS plays; mounted through NULAVIO_TEST_AWS_DIR). Then, in a clean Fedora
# container, dnf installs the package with gpgcheck and repo_gpgcheck on, and a
# copy of the repository with altered metadata is refused. Proves rpm 6 and
# dnf 5 accept what the KMS signer makes, through the release scripts.
#
#   scripts/release/test_kms_signing.sh
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
image=$("$repo_root/scripts/release/base_image.sh" fedora-build)
work=$(mktemp -d "${TMPDIR:-/tmp}/nulavio-kmstest-XXXXXX")
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
    'FAKE_KMS_KEY=/opt/aws/kms.json FAKE_KMS_LOG=/tmp/fake-kms.log exec python3 /opt/aws/fake_aws.py "$@"' >"$work/aws/bin/aws"
chmod 755 "$work/aws/bin/aws"
chmod 644 "$work/aws/kms.json" "$work/aws/fake_aws.py"

podman run --rm --security-opt label=disable -v "$work/packages:/out" "$image" bash -euc '
    dnf -y -q install rpm-build >/dev/null 2>&1 || { echo "test_kms_signing: dnf failed" >&2; exit 1; }
    mkdir -p /tmp/rpmbuild/SPECS
    printf "%s\n" "Name: nulavio-kms-test" "Version: 1" "Release: 1" "Summary: KMS signing test" "License: MPL-2.0" \
        "BuildArch: noarch" "%description" "Test package." "%install" \
        "mkdir -p %{buildroot}/usr/share/nulavio-kms-test && echo ok > %{buildroot}/usr/share/nulavio-kms-test/ok" \
        "%files" "/usr/share/nulavio-kms-test/ok" >/tmp/rpmbuild/SPECS/test.spec
    rpmbuild -bb --quiet --define "_topdir /tmp/rpmbuild" /tmp/rpmbuild/SPECS/test.spec >/dev/null 2>&1
    cp /tmp/rpmbuild/RPMS/noarch/*.rpm /out/
'

NULAVIO_KMS_KEY_ID=alias/nulavio-test NULAVIO_PUBLIC_KEY="$work/key.asc" NULAVIO_TEST_AWS_DIR="$work/aws" \
    "$repo_root/scripts/release/sign_repo.sh" "$work/packages" "$work/repo" "$fpr" >/dev/null

install_from() {
    podman run --rm --security-opt label=disable -v "$1:/repo:ro" "$image" bash -euc '
        printf "%s\n" "[kms-test]" "name=KMS signing test" "baseurl=file:///repo" "gpgcheck=1" "repo_gpgcheck=1" \
            "gpgkey=file:///repo/nulavio-packages.asc" >/etc/yum.repos.d/kms-test.repo
        dnf -y -q --disablerepo="*" --enablerepo=kms-test install nulavio-kms-test >/dev/null 2>&1 || { echo refused; exit 3; }
        rpmkeys --checksig /repo/x86_64/*.rpm | grep -q "digests signatures OK" || { echo "bad package signature"; exit 4; }
        echo installed
    '
}
result=$(install_from "$work/repo" || true)
[[ $result == installed ]] || { echo "test_kms_signing: the signed repository was not accepted ($result)" >&2; exit 1; }

cp -a "$work/repo" "$work/tampered"
sed -i 's|<revision>|<revision>1|' "$work/tampered/repodata/repomd.xml"
result=$(install_from "$work/tampered" || true)
[[ $result == refused ]] || { echo "test_kms_signing: a repository with altered metadata was accepted ($result)" >&2; exit 1; }

echo "signed through sign_repo.sh and a stand-in KMS: dnf installs it with both checks on and refuses tampered metadata"
