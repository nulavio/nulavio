# Track A on Ubuntu userspace: Firefox from Mozilla's APT repository (the
# Ubuntu "firefox" package is a Snap, which the launcher refuses). The signing
# key is accepted only if its fingerprint matches the one Mozilla publishes.
# Note: this tests Ubuntu userspace on the host kernel; Ubuntu's AppArmor
# user-namespace restriction must be checked on a real Ubuntu host.
#   podman build -t localhost/nulavio-itest:ubuntu -f ci/containers/ubuntu-itest.Containerfile ci/containers
# The base image is pinned by tag and digest and kept current by Dependabot. The .deb
# scripts run in this same image (scripts/release/base_image.sh); see
# docs/security/dependency-updates.md.
FROM docker.io/library/ubuntu:26.10@sha256:262df65c0ec6bf8d9dcc87454f4330a05fae4b97825f45854af3b136666584c2
ARG MOZILLA_APT_FPR=35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates wget gnupg python3 procps findutils \
 && install -d -m 0755 /etc/apt/keyrings \
 && wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O /etc/apt/keyrings/packages.mozilla.org.asc \
 && export GNUPGHOME="$(mktemp -d)" \
 && test "$(gpg -n -q --import --import-options import-show --with-colons /etc/apt/keyrings/packages.mozilla.org.asc | awk -F: '/^fpr/{print $10; exit}')" = "$MOZILLA_APT_FPR" \
 && echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" > /etc/apt/sources.list.d/mozilla.list \
 && printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' > /etc/apt/preferences.d/mozilla \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends firefox \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home tester
USER tester
WORKDIR /home/tester
