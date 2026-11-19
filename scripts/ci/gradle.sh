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
# NULAVIO_MAVEN_MIRROR: an https mirror of Maven Central that Gradle asks before Maven Central itself
# (scripts/ci/maven-mirror.init.gradle, #535); unset, Gradle reads Maven Central only. When the mirror failed a
# run (refused it, dropped it or answered with any error status, 403 included), the next run goes to Maven Central
# without it; after a run that failed for any other reason, the mirror is used again.
# NULAVIO_GRADLE_RETRY_WAITS: the waits in seconds before each new run (default "120 300": three
# runs at most). NULAVIO_GRADLEW: the Gradle wrapper (default android/gradlew; the tests use a stub).
set -euo pipefail
(( $# )) || { echo "usage: gradle.sh <gradle argument>..." >&2; exit 2; }

root=$(cd "$(dirname "$0")/../.." && pwd)
gradlew=${NULAVIO_GRADLEW:-$root/android/gradlew}
read -r -a waits <<< "${NULAVIO_GRADLE_RETRY_WAITS-120 300}"
configured=${NULAVIO_MAVEN_MIRROR-}
mirror=$configured
site=$(grep -Eo '^https://[^/]+' <<< "$configured" || true) # the mirror's scheme and host, as Gradle's errors name it
log=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/gradle.XXXXXX")
trap 'rm -f "$log"' EXIT

# A repository that refused or dropped the request: worth a second run. "Could not resolve" or
# "Could not parse POM" alone are not: they are also what a wrong coordinate or a bad POM say.
refused='Received status code (429|5[0-9][0-9]) from server|Server returned HTTP response code: (429|5[0-9][0-9])|Read timed out|Connect timed out|Connection reset|Connection refused|Remote host terminated the handshake'

attempt=1
while :; do
    status=0
    through=()
    if [[ -n $mirror ]]; then
        echo "gradle.sh: Maven Central through the mirror $mirror first"
        through=(--init-script "$root/scripts/ci/maven-mirror.init.gradle")
    fi
    NULAVIO_MAVEN_MIRROR=$mirror "$gradlew" -p "$root/android" --no-daemon "${through[@]}" "$@" 2>&1 | tee "$log" || status=$?
    (( status == 0 )) && exit 0
    if grep -q 'Dependency verification failed' "$log"; then
        exit "$status" # an artifact differs from its pinned checksum: never fetched again
    fi
    mirror_failed=0
    if [[ -n $mirror && -n $site ]] && grep -Fq -e "Could not GET '$site/" -e "Could not HEAD '$site/" "$log"; then
        mirror_failed=1
    fi
    if (( attempt > ${#waits[@]} )) || { (( ! mirror_failed )) && ! grep -Eq "$refused" "$log"; }; then
        exit "$status"
    fi
    wait=${waits[attempt - 1]}
    host=$(grep -Eo "Could not (GET|HEAD) 'https?://[^/']+" "$log" | head -n 1 | sed -E "s/^Could not (GET|HEAD) '//" || true)
    why=$(grep -Eo "$refused|Received status code [0-9]+ from server" "$log" | head -n 1 || true)
    what="${host:+$host: }$why"
    note=
    if (( mirror_failed )); then
        mirror= # the mirror failed this run: the next one goes to Maven Central directly
        note=", without the mirror"
    else
        mirror=$configured # a failure elsewhere: the mirror again, if there is one
    fi
    echo "::warning title=Gradle::a repository refused the build (${what}); running Gradle again in ${wait} s${note} (run $((attempt + 1)) of $(( ${#waits[@]} + 1 )))"
    sleep "$wait"
    attempt=$((attempt + 1))
done
