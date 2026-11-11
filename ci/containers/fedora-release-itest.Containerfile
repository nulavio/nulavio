# The integration suite against a Nulavio build, the same everywhere: the release
# rehearsal and the AddressSanitizer run use it on the laptop and in CI
# (scripts/release/run_integration.sh). Fixed fonts, so the component gallery's pixel
# baselines (tests/baselines/component-gallery) hold on any host: the Noto and
# Liberation families the reference laptop (Fedora 44 KDE) renders the Shell with.
# The engine's libraries come with Fedora's firefox package; the rest are the tools
# the tests look for (Vault: gocryptfs, FUSE, libsodium; Connect: D-Bus; certificates).
#   podman build -t localhost/nulavio-fedora-release-itest -f ci/containers/fedora-release-itest.Containerfile ci/containers
# The base image is pinned by tag and digest and kept current by Dependabot
# (docs/security/dependency-updates.md).
FROM registry.fedoraproject.org/fedora:44@sha256:e34bf26713717aed250ebb18b959df39bca38a0e4a5cb9eb024b8e19c41162e2
RUN dnf -y --setopt=install_weak_deps=False install \
        firefox python3 findutils procps-ng git util-linux which \
        google-noto-sans-fonts google-noto-sans-mono-fonts google-noto-serif-fonts \
        google-noto-color-emoji-fonts google-noto-sans-cjk-vf-fonts \
        liberation-sans-fonts liberation-serif-fonts liberation-mono-fonts fontconfig \
        gocryptfs fuse3 libsodium dbus-daemon systemd libsecret xdg-utils \
        nss-tools openssl avahi-tools bubblewrap \
    && dnf clean all \
    && useradd --create-home tester
USER tester
WORKDIR /home/tester
