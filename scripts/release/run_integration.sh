#!/usr/bin/env bash
# Run the integration suite against an installed Nulavio tree.
#
#   scripts/release/run_integration.sh <install-dir> [test-file-pattern]
#
# NULAVIO_INTEGRATION_IMAGE=<name>: in the pinned container ci/containers/<name>.Containerfile
# (fedora-release-itest: the fonts and tools are fixed, so the component gallery's pixel
# baselines hold on any host; the release workflow and asan.yml use it). Otherwise on this
# host, as before. In the container the tree is read-only, the checkout is copied in, and
# FUSE works for the Vault tests (/dev/fuse, SYS_ADMIN inside the rootless user namespace
# only); the test user is mapped to the caller, so what it writes stays the caller's.
# NULAVIO_TEST_ARTIFACTS and NULAVIO_ASAN_LOG_DIR (AddressSanitizer reports, sets
# ASAN_OPTIONS) are directories on the host, mounted in.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
install=$(realpath "${1:?usage: run_integration.sh <install-dir> [test-file-pattern]}")
pattern=${2:-test*.py}
[[ -x $install/nulavio ]] || { echo "run_integration: $install has no nulavio executable" >&2; exit 2; }
asan=
if [[ -n ${NULAVIO_ASAN_LOG_DIR:-} ]]; then
    mkdir -p "$NULAVIO_ASAN_LOG_DIR"
    asan=$(realpath "$NULAVIO_ASAN_LOG_DIR")
fi

if [[ -z ${NULAVIO_INTEGRATION_IMAGE:-} ]]; then
    [[ -n $asan ]] && export ASAN_OPTIONS="log_path=$asan/asan:detect_leaks=0"
    exec env NULAVIO_ENGINE="$install/nulavio" python3 -I "$repo/tests/run.py" integration "$pattern"
fi

name=$NULAVIO_INTEGRATION_IMAGE
[[ $name =~ ^[a-z0-9-]+$ && -f $repo/ci/containers/$name.Containerfile ]] ||
    { echo "run_integration: no ci/containers/$name.Containerfile" >&2; exit 2; }
image=localhost/nulavio-$name
podman build -q -t "$image" -f "$repo/ci/containers/$name.Containerfile" "$repo/ci/containers" >/dev/null
args=(--rm --security-opt label=disable --device /dev/fuse --cap-add SYS_ADMIN
      "--userns=keep-id:uid=1000,gid=1000"
      -v "$repo:/src:ro" -v "$install:/opt/nulavio:ro" -e NULAVIO_ENGINE=/opt/nulavio/nulavio)
if [[ -n ${NULAVIO_TEST_ARTIFACTS:-} ]]; then
    mkdir -p "$NULAVIO_TEST_ARTIFACTS"
    args+=(-v "$(realpath "$NULAVIO_TEST_ARTIFACTS"):/artifacts" -e NULAVIO_TEST_ARTIFACTS=/artifacts)
fi
[[ -n $asan ]] && args+=(-v "$asan:/asan" -e "ASAN_OPTIONS=log_path=/asan/asan:detect_leaks=0")
# shellcheck disable=SC2016 # expanded by the container's shell
exec podman run "${args[@]}" "$image" sh -c 'cp -r /src "$HOME/nulavio" && cd "$HOME/nulavio" && exec python3 -I tests/run.py integration "$0"' "$pattern"
