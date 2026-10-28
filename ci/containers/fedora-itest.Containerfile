# Disposable environment for Nulavio integration tests and provider spikes.
# Everything is installed inside the container only (nothing on the host).
# Xvfb + xdotool drive provider dialogs (e.g. KeePassXC association) in spikes.
#   podman build -t localhost/nulavio-itest:f44 -f ci/containers/fedora-itest.Containerfile .
# The base image is pinned by tag and digest and kept current by Dependabot
# (docs/security/dependency-updates.md).
FROM registry.fedoraproject.org/fedora:44@sha256:e34bf26713717aed250ebb18b959df39bca38a0e4a5cb9eb024b8e19c41162e2
RUN dnf -y --setopt=install_weak_deps=False install \
        firefox keepassxc python3 findutils procps-ng git \
        xorg-x11-server-Xvfb xdotool \
    && dnf clean all \
    && useradd --create-home tester
USER tester
WORKDIR /home/tester
