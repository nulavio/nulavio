# Disposable Track B build environment (nothing is installed on the host).
# System packages are the ones `mach bootstrap` asks for on Linux, plus Rust
# from Fedora's GPG-signed repositories (>= MINIMUM_RUST_VERSION; avoids the
# rustup installer). Clang, cbindgen, nasm, node and the sysroot are fetched
# by --enable-bootstrap.
#   podman build -t localhost/nulavio-build:f44 -f ci/containers/fedora-build.Containerfile ci/containers
# The base image is pinned by tag and digest and kept current by Dependabot. The RPM
# scripts run in this same image (scripts/release/base_image.sh); see
# docs/security/dependency-updates.md.
FROM registry.fedoraproject.org/fedora:44@sha256:e34bf26713717aed250ebb18b959df39bca38a0e4a5cb9eb024b8e19c41162e2
RUN dnf -y --setopt=install_weak_deps=False install \
        python3 bash findutils gzip make perl perl-FindBin tar unzip xz zip diffutils patch which \
        rust cargo \
    && dnf clean all
WORKDIR /src
