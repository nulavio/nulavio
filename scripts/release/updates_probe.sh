#!/bin/sh
# Check Nulavio's automatic updates on a clean package install (#241), as root inside the package check containers:
# they are off after the install, the helper turns them on and off, the units are valid where systemd-analyze is
# there, the update fails without Nulavio's repository and, on APT, when the refresh of its index fails, and removing
# the package takes the units away (the flag file stays, empty, read by nothing).
#
#   updates_probe.sh <command that removes the nulavio package>...
set -eu
flag=/etc/nulavio/automatic-updates
units=/usr/lib/systemd/system
helper=/usr/libexec/nulavio/automatic-updates
link=$units/timers.target.wants/nulavio-update.timer
shipped="$units/nulavio-update.timer $units/nulavio-update.service $helper /usr/libexec/nulavio/update-nulavio
/usr/share/polkit-1/actions/net.nulavio.automatic-updates.policy"
# The RPM also carries the key its automatic updates take signing keys from (APT has it in nulavio.sources).
if command -v rpm >/dev/null 2>&1 && rpm -q nulavio >/dev/null 2>&1; then
    shipped="$shipped /usr/share/nulavio/nulavio-packages.asc"
fi
fail() { echo "automatic updates: $*"; exit 1; }
for f in $shipped; do
    [ -e "$f" ] || fail "$f is missing"
done
[ "$(readlink "$link")" = ../nulavio-update.timer ] || fail "the timer's link is missing"
[ ! -e "$flag" ] || fail "on right after the install"
verified=""
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$units/nulavio-update.timer" "$units/nulavio-update.service" || fail "systemd-analyze verify failed"
    verified=", units verified"
fi
# No systemd runs in the container: the helper says the timer starts at the next boot, and still sets the state.
[ "$("$helper" on 2>/dev/null)" = on ] && [ -f "$flag" ] && [ ! -s "$flag" ] || fail "on did not create $flag"
[ "$("$helper" off 2>/dev/null)" = off ] && [ ! -e "$flag" ] || fail "off did not remove $flag"
# What the service runs, with no Nulavio repository configured in the container: it refuses, and changes nothing.
before=$(rpm -q nulavio 2>/dev/null || dpkg-query -W -f='${Version}' nulavio)
if /usr/libexec/nulavio/update-nulavio >/tmp/update.out 2>&1; then
    fail "update-nulavio succeeded without Nulavio's repository: $(cat /tmp/update.out)"
fi
after=$(rpm -q nulavio 2>/dev/null || dpkg-query -W -f='${Version}' nulavio)
[ "$before" = "$after" ] || fail "update-nulavio changed the package without Nulavio's repository"
# On APT, with Nulavio's list pointing at an address that refuses the connection: the failed refresh of its index fails
# the run (#713), instead of a warning and an install from the lists APT had before.
refresh=""
if ! rpm -q nulavio >/dev/null 2>&1; then
    list=/etc/apt/sources.list.d/nulavio.sources
    printf 'Types: deb\nURIs: http://127.0.0.1:9/apt\nSuites: stable\nComponents: main\n' >"$list"
    if /usr/libexec/nulavio/update-nulavio >/tmp/update.out 2>&1; then
        fail "update-nulavio succeeded when the refresh of Nulavio's index failed: $(cat /tmp/update.out)"
    fi
    grep -q "^E: Failed to fetch http://127.0.0.1:9/apt/" /tmp/update.out ||
        fail "update-nulavio did not fail on the refresh of Nulavio's index: $(cat /tmp/update.out)"
    rm -f "$list"
    after=$(dpkg-query -W -f='${Version}' nulavio)
    [ "$before" = "$after" ] || fail "update-nulavio changed the package when the refresh of Nulavio's index failed"
    refresh=" or when the refresh of its index fails"
fi
"$helper" on >/dev/null 2>&1
"$@" >/dev/null 2>&1 || fail "removing the package failed"
for f in $shipped; do
    [ ! -e "$f" ] || fail "$f is still there after removal"
done
[ ! -L "$link" ] || fail "the timer's link is still there after removal"
[ -f "$flag" ] || fail "$flag went with the package"
echo "automatic updates: off after install, the helper turns them on and off$verified, update-nulavio refuses without Nulavio's repository$refresh; removal takes the units, leaves $flag"
