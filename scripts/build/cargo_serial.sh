#!/usr/bin/env bash
# Make can schedule multiple Cargo edges; serialize them across the whole container.
set -euo pipefail
# Cargo prioritizes inherited jobserver tokens over both --jobs and BUILD_JOBS.
unset MAKEFLAGS MFLAGS CARGO_MAKEFLAGS
export CARGO_BUILD_JOBS=1
exec flock /tmp/nulavio-cargo.lock /usr/bin/cargo "$@"
