#!/bin/sh
# Check Nulavio's automatic updates on a clean package install (#241), as root inside the package check containers:
# they are off after the install, the helper turns them on and off, the units are valid where systemd-analyze is
# there, and removing the package takes the units away (the flag file stays, empty, read by nothing).
#
#   updates_probe.sh "<command that removes the nulavio package>"
set -eu
flag=/etc/nulavio/automatic-updates
units=/usr/lib/systemd/system
helper=/usr/libexec/nulavio/automatic-updates
link=$units/timers.target.wants/nulavio-update.timer
shipped="$units/nulavio-update.timer $units/nulavio-update.service $helper /usr/libexec/nulavio/update-nulavio
/usr/share/polkit-1/actions/net.nulavio.automatic-updates.policy"
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
"$helper" on >/dev/null 2>&1
sh -c "$1" >/dev/null 2>&1 || fail "removing the package failed"
for f in $shipped; do
    [ ! -e "$f" ] || fail "$f is still there after removal"
done
[ ! -L "$link" ] || fail "the timer's link is still there after removal"
[ -f "$flag" ] || fail "$flag went with the package"
echo "automatic updates: off after install, the helper turns them on and off$verified; removal takes the units, leaves $flag"
