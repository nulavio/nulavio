#!/usr/bin/env bash
# Build Nulavio (Track B) from a verified Firefox source release, in a
# disposable rootless container. Nothing is installed on the host.
#
#   scripts/build/build_nulavio.sh 158.0.1
#
# Work dir: ${NULAVIO_BUILD_DIR:-~/.cache/nulavio-build} (source, toolchains,
# object dir, logs). Output: <work>/firefox-<v>/obj-nulavio/dist/nulavio-*.tar.xz
#
# Google Safe Browsing key (required): a file outside the repository, mode 0600,
# at ${NULAVIO_SAFEBROWSING_KEYFILE:-~/.config/nulavio-build/google-safebrowsing.key}.
# It is mounted read-only into the container; its value is never printed.
# NULAVIO_ALLOW_NO_SAFEBROWSING_KEY=1 builds without it (development only:
# phishing/malware protection is then INACTIVE).
set -euo pipefail

version=${1:?usage: build_nulavio.sh <firefox-version>}
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=${NULAVIO_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nulavio-build}
src="$work/firefox-$version"
image=localhost/nulavio-build:f44

sb_key=${NULAVIO_SAFEBROWSING_KEYFILE:-${XDG_CONFIG_HOME:-$HOME/.config}/nulavio-build/google-safebrowsing.key}
secret_mounts=()
if [[ -r $sb_key ]]; then
    if [[ $(stat -c %a "$sb_key") != [46]00 ]]; then
        echo "nulavio-build: $sb_key must be private (chmod 600)" >&2
        exit 2
    fi
    secret_mounts=(-v "$sb_key:/run/secrets/google-safebrowsing.key:ro,Z")
    echo "nulavio-build: Google Safe Browsing key: present"
elif [[ ${NULAVIO_ALLOW_NO_SAFEBROWSING_KEY:-} == 1 ]]; then
    echo "nulavio-build: WARNING: no Google Safe Browsing key; phishing/malware lists will be INACTIVE." \
        "Development build only, never a release." >&2
else
    echo "nulavio-build: missing Google Safe Browsing key at $sb_key (docs/architecture/build.md)." \
        "Set NULAVIO_ALLOW_NO_SAFEBROWSING_KEY=1 for a development build." >&2
    exit 2
fi

mkdir -p "$work/mozbuild" "$work/logs"
python3 -I "$repo/scripts/upstream/fetch_firefox_source.py" "$version" --dest "$work"
python3 -I "$repo/scripts/build/make_branding.py" --source "$src"
python3 -I "$repo/scripts/build/apply_patches.py" --source "$src"
cp "$repo/browser/build/mozconfig" "$src/mozconfig"
podman build -q -t "$image" -f "$repo/ci/containers/fedora-build.Containerfile" "$repo/ci/containers" >/dev/null

log="$work/logs/build-$version-$(date +%Y%m%dT%H%M%S).log"
start=$(date +%s)
set +e
podman run --rm --name "nulavio-build-$version" \
    -v "$src":/src:Z \
    -v "$work/mozbuild":/root/.mozbuild:Z \
    "${secret_mounts[@]}" \
    -e MOZCONFIG=/src/mozconfig \
    -e MOZBUILD_STATE_PATH=/root/.mozbuild \
    "$image" \
    bash -c 'set -e; cd /src; ./mach --no-interactive build; ./mach --no-interactive package' 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e
end=$(date +%s)
echo "nulavio-build: exit=$status duration_min=$(( (end - start) / 60 )) log=$log" | tee -a "$log"
exit "$status"
