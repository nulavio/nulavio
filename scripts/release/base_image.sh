#!/usr/bin/env bash
# Print the base image a release script runs in. The one place it is pinned is the
# FROM line of ci/containers/<name>.Containerfile, as tag@sha256:digest, which
# Dependabot keeps current; reading it here means the scripts never drift from it.
# Refuses anything but one registry/name:tag@sha256:digest (no short names).
#
#   scripts/release/base_image.sh fedora-build    # registry.fedoraproject.org/fedora:44@sha256:...
set -euo pipefail

file="$(cd "$(dirname "$0")/../.." && pwd)/ci/containers/${1:?usage: base_image.sh <containerfile name>}.Containerfile"
refs=$(sed -n 's/^FROM[[:space:]]\{1,\}\([^[:space:]]\{1,\}\).*/\1/p' "$file")
pinned='^[a-z0-9-]+(\.[a-z0-9-]+)+(:[0-9]+)?(/[a-z0-9._-]+)+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$'  # registry host first
if [[ $refs == *$'\n'* || ! $refs =~ $pinned ]]; then
    echo "base_image: $file needs exactly one FROM <image>:<tag>@sha256:<digest>" >&2
    exit 2
fi
printf '%s\n' "$refs"
