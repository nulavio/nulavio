# Disposable environment for Nulavio integration tests and provider spikes.
# Everything is installed inside the container only (nothing on the host).
# Xvfb + xdotool drive provider dialogs (e.g. KeePassXC association) in spikes.
#   podman build -t localhost/nulavio-itest:f44 -f ci/containers/fedora-itest.Containerfile .
FROM registry.fedoraproject.org/fedora:44
RUN dnf -y --setopt=install_weak_deps=False install \
        firefox keepassxc python3 findutils procps-ng git \
        xorg-x11-server-Xvfb xdotool \
    && dnf clean all \
    && useradd --create-home tester
USER tester
WORKDIR /home/tester
