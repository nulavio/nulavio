#!/usr/bin/env bash
# End-to-end check of the keys the automatic updates trust on Fedora (#241), in a clean, disposable container with
# THROWAWAY keys made there (nothing touches the host's keys or the release key). A stand-in `nulavio` package
# carries its key file at /usr/share/nulavio/nulavio-packages.asc, as the real one does:
#   1. the person installs it from a repository signed with key A, as the download page says;
#   2. a release signed with key A arrives: update-nulavio installs it;
#   3. the repository and the key at the repository file's `gpgkey` address change to key B: update-nulavio refuses,
#      the package stays as it was and key B is not imported;
#   4. without the key file the package installed, update-nulavio refuses;
#   5. a new key the way the docs say: a release signed with key A carries keys A and B, then a release signed with
#      key B installs;
#   6. a new key without a release that carries it: the administrator accepts key C in a manual `dnf upgrade`, whose
#      package carries key C, then the next release signed with key C installs.
#
#   scripts/release/test_update_key.sh [update-nulavio]   (default: packaging/linux/updates/update-nulavio)
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
image=$("$repo_root/scripts/release/base_image.sh" fedora-build)
script=$(realpath "${1:-$repo_root/packaging/linux/updates/update-nulavio}")

podman run --rm --security-opt label=disable -v "$script:/checks/update-nulavio:ro" \
    -v "$repo_root/site/rpm/nulavio.repo:/checks/nulavio.repo:ro" "$image" bash -euc '
    fail() { echo "FAIL: $*" >&2; exit 1; }
    dnf -y -q install rpm-build rpm-sign createrepo_c gnupg2 >/dev/null 2>&1 || fail "dnf could not install the tools"
    export GNUPGHOME=/tmp/gnupg
    mkdir -m 700 "$GNUPGHOME"
    mkdir -p /srv/keys /tmp/rpmbuild/SPECS
    for name in a b c; do
        gpg --batch --quiet --pinentry-mode loopback --passphrase "" \
            --quick-gen-key "Throwaway $name <$name@nulavio.invalid>" rsa3072 sign 1d 2>/dev/null
        gpg --batch --armor --export "$name@nulavio.invalid" >/srv/keys/"$name".asc
    done
    cat /srv/keys/a.asc /srv/keys/b.asc >/srv/keys/ab.asc

    # stub <version> <signing key> <key file it carries>: a stand-in nulavio package.
    stub() {
        printf "%s\n" "Name: nulavio" "Version: $1" "Release: 1" "Summary: stand-in" "License: MPL-2.0" \
            "BuildArch: noarch" "%description" "stand-in" "%install" \
            "install -Dm0644 /srv/keys/$3.asc %{buildroot}/usr/share/nulavio/nulavio-packages.asc" \
            "%files" "/usr/share/nulavio/nulavio-packages.asc" >/tmp/rpmbuild/SPECS/stub.spec
        rpmbuild -bb --quiet --define "_topdir /tmp/rpmbuild" /tmp/rpmbuild/SPECS/stub.spec >/dev/null 2>&1
        rpmsign --addsign --define "_gpg_name $2@nulavio.invalid" \
            /tmp/rpmbuild/RPMS/noarch/nulavio-"$1"-1.noarch.rpm >/dev/null 2>&1
    }
    # serve <version> <key>: the repository holds that package, its metadata is signed with <key>, and the
    # repository file'\''s gpgkey address serves <key>.
    serve() {
        rm -rf /srv/repo && mkdir -p /srv/repo
        cp /tmp/rpmbuild/RPMS/noarch/nulavio-"$1"-1.noarch.rpm /srv/repo/
        createrepo_c -q /srv/repo
        gpg --batch --yes --armor --detach-sign -u "$2@nulavio.invalid" /srv/repo/repodata/repomd.xml
        cp /srv/keys/"$2".asc /srv/keys/site.asc
    }
    run_update() { PATH=/usr/sbin:/usr/bin sh /checks/update-nulavio >/tmp/update.out 2>&1; }
    installed() { rpm -q --qf "%{VERSION}" nulavio; }
    keys() { rpmkeys --list 2>/dev/null | grep -o "Throwaway [abc]" | tr "\n" " "; }

    stub 1 a a; stub 2 a a; stub 3 b a; stub 4 a ab; stub 5 b ab; stub 6 c c; stub 7 c c
    # The published repository file, pointed at this repository and at the key it serves.
    sed -e "s|^baseurl=.*|baseurl=file:///srv/repo|" -e "s|^gpgkey=.*|gpgkey=file:///srv/keys/site.asc|" \
        /checks/nulavio.repo >/etc/yum.repos.d/nulavio.repo

    serve 1 a
    # -y stands in for the person comparing the fingerprint on the download page.
    dnf -y -q install nulavio >/dev/null 2>&1 || fail "the first install failed"
    echo "1. installed $(installed) from the repository signed with key A; keys: $(keys)"

    serve 2 a
    run_update || fail "an update signed with key A was refused: $(cat /tmp/update.out)"
    [ "$(installed)" = 2 ] || fail "an update signed with key A did not install"
    echo "2. update signed with key A: installed $(installed)"

    serve 3 b
    if run_update; then
        fail "a repository and gpgkey changed to key B were accepted: now $(installed), keys $(keys)"
    fi
    [ "$(installed)" = 2 ] || fail "the package changed although the update failed"
    case "$(keys)" in *"Throwaway b"*) fail "key B was imported: $(keys)" ;; esac
    echo "3. repository and gpgkey changed to key B: refused, still $(installed), keys: $(keys)"
    grep -i -m 2 "signature\|key\|verif" /tmp/update.out | sed "s/^/   | /" || true

    mv /usr/share/nulavio/nulavio-packages.asc /tmp/
    serve 2 a
    if run_update; then
        fail "update-nulavio ran without the key file the package installed"
    fi
    echo "4. without the packaged key file: refused ($(tail -n 1 /tmp/update.out))"
    mv /tmp/nulavio-packages.asc /usr/share/nulavio/

    serve 4 a
    run_update || fail "a release signed with key A carrying key B was refused: $(cat /tmp/update.out)"
    serve 5 b
    run_update || fail "after a release carried key B, a release signed with key B was refused: $(cat /tmp/update.out)"
    [ "$(installed)" = 5 ] || fail "the release signed with key B did not install"
    echo "5. a release signed with key A carried key B, then a release signed with key B: installed $(installed)"

    serve 6 c
    dnf -y -q --refresh upgrade nulavio >/dev/null 2>&1 || fail "the manual upgrade to key C failed"
    [ "$(installed)" = 6 ] || fail "the manual upgrade to key C did not install"
    serve 7 c
    run_update || fail "after a manual upgrade brought key C, a release signed with key C was refused: $(cat /tmp/update.out)"
    [ "$(installed)" = 7 ] || fail "the release signed with key C did not install"
    echo "6. the administrator accepted key C in a manual dnf upgrade, then a release signed with key C: installed $(installed)"
'
