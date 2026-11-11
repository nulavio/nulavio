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
# Extra UI languages packaged with en-US (signed-off firefox-l10n revisions).
read -r -a locales <<< "${NULAVIO_LOCALES:-pt-BR}"

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

# Serialize preparation too, across caches/worktrees; the guard takes its own
# workload lock. FD 9 stays with this script through exec, never with compilers.
lock_dir="${XDG_RUNTIME_DIR:-$HOME/.cache}/nulavio-build-$(id -u)"
mkdir -p "$lock_dir"
exec 9>"$lock_dir/prepare.lock"
flock -n 9 || { echo "nulavio-build: another build is preparing" >&2; exit 75; }

# Refuse unsafe host conditions before fetching, extracting or building an image.
python3 -B -I "$repo/scripts/build/build_guard.py" --check
mkdir -p "$work/mozbuild" "$work/logs"
python3 -I "$repo/scripts/upstream/fetch_firefox_source.py" "$version" --dest "$work"
python3 -I "$repo/scripts/upstream/fetch_firefox_l10n.py" --source "$src" \
    --dest "$work/mozbuild/l10n-central" --git-dir "$work/l10n-git" "${locales[@]}"
python3 -I "$repo/scripts/build/make_branding.py" --source "$src"
python3 -I "$repo/scripts/build/apply_patches.py" --source "$src"
cp "$repo/browser/build/mozconfig" "$src/mozconfig"
# Bootstrap also respects the requested memory budget and fixed two-CPU quota.
# NULAVIO_BUILD_PROFILE=runner: a disposable CI machine (build_guard.py, docs/architecture/build.md).
if [[ ${NULAVIO_BUILD_PROFILE:-laptop} == runner ]]; then
    memory_gib=${NULAVIO_BUILD_MEMORY_GIB:-48}
    cpu_quota=$(( ${MOZ_PARALLEL_BUILD:-16} * 100000 ))
else
    memory_gib=${NULAVIO_BUILD_MEMORY_GIB:-16}
    cpu_quota=200000
fi
podman build --memory="${memory_gib}g" --memory-swap="${memory_gib}g" \
    --cpu-period=100000 --cpu-quota="$cpu_quota" --jobs=1 -q -t "$image" \
    -f "$repo/ci/containers/fedora-build.Containerfile" "$repo/ci/containers" >/dev/null

# Single-quoted command expands inside the container.
control="$work/logs/guard-$(date +%Y%m%dT%H%M%S)-$$"
# shellcheck disable=SC2016
exec python3 -B -I "$repo/scripts/build/build_guard.py" --control "$control" -- \
    -v "$src":/src:Z \
    -v "$work/mozbuild":/root/.mozbuild:Z \
    "${secret_mounts[@]}" \
    -e MOZCONFIG=/src/mozconfig \
    -e MOZBUILD_STATE_PATH=/root/.mozbuild \
    -e NULAVIO_LOCALES="${locales[*]}" \
    "$image" -- \
    bash -c 'set -e; cd /src
             printf "\nmk_add_options MOZ_PARALLEL_BUILD=%s\n" "$MOZ_PARALLEL_BUILD" >> mozconfig
             if [ "$NULAVIO_BUILD_PROFILE" != runner ]; then
                 printf "ac_add_options CARGO=/nulavio-build/cargo_serial.sh\n" >> mozconfig
                 if [ "$MOZ_PARALLEL_BUILD" -gt 1 ]; then
                     printf "ac_add_options CARGOFLAGS=--jobs=1\n" >> mozconfig
                 fi
             fi
             ./mach --no-interactive build --jobs "$MOZ_PARALLEL_BUILD"
             ./mach --no-interactive package-multi-locale --locales en-US $NULAVIO_LOCALES'
