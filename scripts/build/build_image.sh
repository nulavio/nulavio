#!/usr/bin/env bash
# Build the build container's image, and rebuild it from nothing when the one podman has is old (#482).
#
#   scripts/build/build_image.sh <image> <containerfile> <context> [podman build options...]
#
# The Containerfile pins its base image by digest but installs `rust` from the distribution without a
# version, and podman reuses that layer from its cache for as long as the image exists. A machine that
# keeps its image keeps its Rust compiler: the build laptop's pre-check built with 1.99.0 while the build
# machine, which builds the image anew in every run, had 1.99.1. So an image older than
# NULAVIO_IMAGE_MAX_AGE_DAYS (default 1; 0 = every time) is built again with --no-cache, which installs
# the packages as the distribution serves them today. A younger image is kept: the cache then makes the
# call take seconds. Afterwards the compiler of the image is printed, so a log says which one a build used.
# A release does not rest on this (its attestation names the compiler); this keeps the pre-check, the first
# build of a new engine version, on the compiler the release build will get.
set -euo pipefail

image=${1:?usage: build_image.sh <image> <containerfile> <context> [podman build options...]}
containerfile=${2:?usage: build_image.sh <image> <containerfile> <context> [podman build options...]}
context=${3:?usage: build_image.sh <image> <containerfile> <context> [podman build options...]}
shift 3

max_days=${NULAVIO_IMAGE_MAX_AGE_DAYS:-1}
if [[ ! $max_days =~ ^[0-9]{1,4}$ ]]; then
    echo "nulavio-build: NULAVIO_IMAGE_MAX_AGE_DAYS must be a number of days, not '$max_days'" >&2
    exit 2
fi

fresh=()
if created=$(podman image inspect --format '{{.Created.Unix}}' "$image" 2>/dev/null) && [[ $created =~ ^[0-9]+$ ]]; then
    age=$(( $(date +%s) - created ))
    if (( age >= max_days * 86400 )); then
        echo "nulavio-build: $image is $(( age / 86400 )) day(s) old (limit $max_days): building it again without the cache"
        fresh=(--no-cache)
    fi
else
    fresh=(--no-cache)
fi

podman build "${fresh[@]}" "$@" -q -t "$image" -f "$containerfile" "$context" >/dev/null
echo "nulavio-build: $image has $(podman run --rm "$image" rustc --version)"
