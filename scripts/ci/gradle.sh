#!/usr/bin/env bash
# Run the Companion's Gradle build on a CI runner, again after a wait when a Maven repository
# refused it for a moment (#516). Maven Central answers runners with 429 Too Many Requests now
# and then; Gradle then disables every repository for the rest of the build, and the job fails
# for a reason outside the change. A plain second run reuses what the first one downloaded.
#
# Nothing about what is fetched changes: no forced refresh, no write flag, and Gradle
# checks every artifact against android/gradle/verification-metadata.xml on each run. A failed
# dependency verification is never retried, and neither is any other build failure.
#
#   scripts/ci/gradle.sh <gradle argument>...
#
# NULAVIO_GRADLE_RETRY_WAITS: the waits in seconds before each new run (default "60 120": three
# runs at most). NULAVIO_GRADLEW: the Gradle wrapper (default android/gradlew; the tests use a stub).
set -euo pipefail
(( $# )) || { echo "usage: gradle.sh <gradle argument>..." >&2; exit 2; }

root=$(cd "$(dirname "$0")/../.." && pwd)
gradlew=${NULAVIO_GRADLEW:-$root/android/gradlew}
read -r -a waits <<< "${NULAVIO_GRADLE_RETRY_WAITS-60 120}"
log=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/gradle.XXXXXX")
trap 'rm -f "$log"' EXIT

# A repository that refused or dropped the request: worth a second run. "Could not resolve" or
# "Could not parse POM" alone are not: they are also what a wrong coordinate or a bad POM say.
refused='Received status code (429|5[0-9][0-9]) from server|Read timed out|Connect timed out|Connection reset|Connection refused|Remote host terminated the handshake'

attempt=1
while :; do
    status=0
    "$gradlew" -p "$root/android" --no-daemon "$@" 2>&1 | tee "$log" || status=$?
    (( status == 0 )) && exit 0
    if grep -q 'Dependency verification failed' "$log"; then
        exit "$status" # an artifact differs from its pinned checksum: never fetched again
    fi
    if (( attempt > ${#waits[@]} )) || ! grep -Eq "$refused" "$log"; then
        exit "$status"
    fi
    wait=${waits[attempt - 1]}
    what=$(grep -Eo "Could not (GET|HEAD) 'https?://[^/']+|$refused" "$log" | head -n 2 | sed -E "s/^Could not (GET|HEAD) '//" | paste -sd ' ' - || true)
    echo "::warning title=Gradle::a repository refused the build (${what}); running Gradle again in ${wait} s (run $((attempt + 1)) of $(( ${#waits[@]} + 1 )))"
    sleep "$wait"
    attempt=$((attempt + 1))
done
