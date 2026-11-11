#!/usr/bin/env bash
# Start the installed Flatpak (net.nulavio.Nulavio) headless, with a fresh profile, and
# require a rendered page: the engine, its libraries and the runtime fit together inside
# the sandbox. Also checks the Flatpak-only preference that turns on the native-messaging
# proxy. Needs flatpak and dbus-run-session.
#
#   scripts/release/check_flatpak.sh
set -euo pipefail

# shellcheck disable=SC2016 # the shell inside the sandbox expands these
out=$(timeout 300 dbus-run-session -- flatpak run --command=sh net.nulavio.Nulavio -c '
    profile=$(mktemp -d)
    /app/bin/nulavio --headless --profile "$profile" --screenshot "$profile/shot.png" \
        "data:text/html,<h1>Nulavio</h1>" >"$profile/engine.log" 2>&1 || true
    if [ -s "$profile/shot.png" ]; then echo rendered; else tail -20 "$profile/engine.log"; fi
    grep -q "native-messaging-proxy\", 1" /app/lib/nulavio/browser/defaults/preferences/flatpak.js && echo proxy-pref
' 2>&1 || true)
printf '%s\n' "$out"
grep -qx rendered <<<"$out" || { echo "check_flatpak: the browser did not render a page in the sandbox" >&2; exit 1; }
grep -qx proxy-pref <<<"$out" || { echo "check_flatpak: the native-messaging proxy preference is missing" >&2; exit 1; }
echo "check_flatpak: net.nulavio.Nulavio renders a page in the sandbox"
