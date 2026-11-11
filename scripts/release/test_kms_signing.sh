#!/usr/bin/env bash
# End-to-end check of signing through AWS KMS (scripts/release/openpgp_sign.py),
# without AWS: in a clean Fedora container, make a throwaway RSA-4096 key, hand
# its private part to a stand-in `aws` command (the role KMS plays), delete the
# key, then sign a package with rpmsign and the repository metadata with
# openpgp_sign.py, and install from that repository with gpgcheck and
# repo_gpgcheck on. Proves rpm 6 and dnf 5 accept what the KMS signer makes.
#
#   scripts/release/test_kms_signing.sh
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
image=$("$repo_root/scripts/release/base_image.sh" fedora-build)

podman run --rm --security-opt label=disable -v "$repo_root:/src:ro" "$image" bash -euc '
    dnf -y -q install rpm-sign rpm-build gnupg2 python3 createrepo_c >/dev/null 2>&1 || { echo "test_kms_signing: dnf failed" >&2; exit 1; }
    work=$(mktemp -d)
    export GNUPGHOME=$work/gnupg
    mkdir -m 700 "$GNUPGHOME"
    gpg --batch --quiet --pinentry-mode loopback --passphrase "" \
        --quick-gen-key "Nulavio throwaway test key <test@nulavio.invalid>" rsa4096 sign 1d 2>/dev/null
    gpg --batch --armor --export >"$work/key.asc"
    gpg --batch --pinentry-mode loopback --passphrase "" --export-secret-keys >"$work/secret.gpg"
    mkdir "$work/bin"
    WORK=$work python3 -I -c "
import base64, json, os, sys
sys.path[:0] = [\"/src/tests/unit\", \"/src/scripts/release\"]
import test_openpgp_sign as t
work = os.environ[\"WORK\"]
n, e, d = t.secret_numbers(open(work + \"/secret.gpg\", \"rb\").read())
json.dump({\"n\": n, \"d\": d, \"spki\": base64.b64encode(t.spki(n, e)).decode()}, open(work + \"/kms.json\", \"w\"))
open(work + \"/bin/aws\", \"w\").write(t.FAKE_AWS)
"
    chmod 700 "$work/bin/aws"
    rm -rf "$GNUPGHOME" "$work/secret.gpg"   # from here on only the stand-in KMS can sign
    export PATH=$work/bin:$PATH FAKE_KMS_KEY=$work/kms.json FAKE_KMS_LOG=$work/aws.log

    mkdir -p "$work/rpmbuild/SPECS" /repo/noarch
    printf "%s\n" "Name: nulavio-kms-test" "Version: 1" "Release: 1" "Summary: KMS signing test" "License: MPL-2.0" \
        "BuildArch: noarch" "%description" "Test package." "%install" \
        "mkdir -p %{buildroot}/usr/share/nulavio-kms-test && echo ok > %{buildroot}/usr/share/nulavio-kms-test/ok" \
        "%files" "/usr/share/nulavio-kms-test/ok" >"$work/rpmbuild/SPECS/test.spec"
    rpmbuild -bb --quiet --define "_topdir $work/rpmbuild" "$work/rpmbuild/SPECS/test.spec" >/dev/null 2>&1
    cp "$work"/rpmbuild/RPMS/noarch/*.rpm /repo/noarch/

    signer="/usr/bin/python3 -I /src/scripts/release/openpgp_sign.py --public-key $work/key.asc --kms-key-id alias/nulavio-test"
    fpr=$(python3 -I -c "import sys; sys.path.insert(0, \"/src/scripts/release\"); import openpgp_sign as o; print(o.primary_key(open(\"$work/key.asc\", \"rb\").read()).hex)")
    rpmsign --define "_openpgp_sign kms" --define "_openpgp_sign_id $fpr" \
        --define "__kms_sign_cmd() $signer -o %{shescape:%{2}} -- %{shescape:%{1}}" --addsign /repo/noarch/*.rpm >/dev/null
    createrepo_c --quiet /repo
    $signer --armor -o /repo/repodata/repomd.xml.asc /repo/repodata/repomd.xml

    rpmkeys --import "$work/key.asc"
    rpmkeys --checksig /repo/noarch/*.rpm | grep -q "digests signatures OK" || { echo "test_kms_signing: package signature not accepted" >&2; exit 1; }
    printf "%s\n" "[kms-test]" "name=KMS signing test" "baseurl=file:///repo" "gpgcheck=1" "repo_gpgcheck=1" \
        "gpgkey=file://$work/key.asc" >/etc/yum.repos.d/kms-test.repo
    dnf -y -q --disablerepo="*" --enablerepo=kms-test install nulavio-kms-test >/dev/null 2>&1 ||
        { echo "test_kms_signing: dnf refused the signed repository" >&2; exit 1; }
    echo "signed through the stand-in KMS ($(wc -l <"$work/aws.log") calls): rpm and dnf accept the package and the metadata"
'
