# Phase 5 spikes: outer confinement, Flatpak, SELinux, sensitive sites

- **Date:** 2026-10-27
- **Slice:** S23 ([execution plan](../product/execution-plan.md)). Each spike ends with a decision and, where adopted, a test.
- **Host measured:** Fedora 44, KDE Plasma, SELinux enforcing, bubblewrap 0.12.0, xdg-desktop-portal 1.22.1, Flatpak 1.18.4. Engine: Nulavio build of Firefox 158.0.1.
- **What none of this changes:** a program running as the same user outside the browser can still read the browser's files ([threat model S11](threat-model.md#s11--local-malicious-process-as-the-same-user-infostealer)). Outer confinement limits what a *compromised browser* can reach; it does not stop an infostealer.

| Spike | Decision |
|---|---|
| [bubblewrap](#bubblewrap) | **Adopted as an opt-in**: `nulavio run --confined` (profiles the Nulavio tools run). The browser sees only its profile and Downloads in the home folder; the engine's own sandbox is unchanged on Fedora; on Ubuntu, where it would not be, the confined start is refused ([below](#bubblewrap-on-ubuntu)) (`test_confine`, `test_confined`) |
| [Flatpak and native messaging](#flatpak-and-native-messaging) | **Not now.** Native messaging is solvable (the host-side proxy ships in Fedora 44 and Ubuntu 26.04+), but a Flatpak adds a second sandbox layout, a second update channel and Flathub publishing for no gain over bubblewrap on the same host. Revisit after the RPM/DEB channel is public |
| [SELinux](#selinux) | **Not adopted.** Installing a policy module needs root on every machine; the browser runs `unconfined_t` like Fedora's Firefox; bubblewrap gives the filesystem part without root |
| [AppArmor on Ubuntu](#apparmor-on-ubuntu) | **Adopted** (found during this slice): the `.deb` ships a profile that lets the engine create the user namespaces its content sandbox needs on Ubuntu 24.04 and later, and nothing else (`check_deb.sh`) |
| [Sensitive sites](#sensitive-sites) | **Adopted** as a profile template, not a container: "Sensitive sites" deletes cookies, site data, history and cache when it closes and refuses extension installs from web pages (`test_profiles` 11) |

## bubblewrap

Question: can the whole browser run inside bubblewrap, hiding the home folder, without weakening the engine's own sandbox?

Measured on Fedora (Nulavio build and distribution Firefox 158, headless and with a real profile, chrome code reading files, `/proc` for every process; Ubuntu [below](#bubblewrap-on-ubuntu)):

| | Without | With `--confined` |
|---|---|---|
| A file elsewhere in the home folder (an artificial `~/.ssh/id_fake`, the real `~/.ssh`) | readable | **not there** |
| Profile and Downloads | writable | writable |
| Content sandbox level (`about:support`) | 6 | 6 |
| User namespaces, seccomp-bpf available to the engine | yes | yes (on Ubuntu, seccomp-bpf only, so the launcher refuses: [below](#bubblewrap-on-ubuntu)) |
| Web content processes under seccomp (`/proc/<pid>/status`) | all (mode 2) | all (mode 2) |
| Profile lock PID | real | real |

Design (`launcher/nulavio_launcher/confine.py`):

- `--ro-bind / /`, then empty in-memory folders over `/home`, the user's home, `/tmp`, `/var/tmp`, `/dev/shm`, `/mnt`, `/media`, `/run/media`, the user's runtime folder (`$XDG_RUNTIME_DIR` and `/run/user/<uid>`) and Nulavio's own folders (data, state, cache and runtime, wherever they are, so the other profiles are not there even when the data folder is outside the home folder). A Unix socket under a read-only mount still accepts connections, so the runtime folder is hidden, not left read-only. Every folder is hidden before anything is put back, so nothing put back is covered again (a temporary profile lives in the runtime folder).
- Put back read-write: the profile and the Downloads folder (from the desktop's folder names; never the home folder itself). Read-only: fonts, GTK and KDE appearance settings, the desktop's folder names, `mimeapps.list`, registered native-messaging hosts, the engine's folder; from the runtime folder only the Wayland socket (`$WAYLAND_DISPLAY`), PipeWire (`pipewire-0`; its separate manager socket is not put back, which does not narrow what a client of `pipewire-0` may ask), PulseAudio (`pulse/native`) and, when it is there, KeePassXC's browser socket folder (`app/org.keepassxc.KeePassXC`). Not the session bus, the user's service manager (`systemd/`), agents' sockets (SSH, GnuPG), other programs' sockets or Nulavio's own runtime folder.
- `/dev` is bubblewrap's own (`null`, `zero`, `random`, its own terminals, an empty `/dev/shm`), with only these put back from the host's, as they are at the start: the GPU (`/dev/dri`, NVIDIA's nodes) and the cameras (`/dev/video*`). Not input devices, the session's terminals (`/dev/pts`), HID devices (security keys among them) or other hardware nodes. System V IPC is its own namespace (`--unshare-ipc`).
- Not passed inside: `DBUS_SESSION_BUS_ADDRESS`, `DISPLAY`, `XAUTHORITY`. There is no session bus inside and no X server is offered; a session with X11 only (no Wayland socket) is refused, since any X client can read and type into the other windows.
- No PID namespace: the profile lock keeps real PIDs, so the launcher still sees a running profile. User namespaces stay available (no `--disable-userns`), so the engine still builds its own content sandboxes: on Fedora; on Ubuntu, AppArmor takes the capabilities they need away, and the launcher refuses ([below](#bubblewrap-on-ubuntu)). `--new-session`; `--die-with-parent` when the launcher supervises (temporary and protected profiles).
- Refusals: an X11-only session (above), no `bwrap`, bubblewrap cannot create its own namespaces here, or the engine could not create its content processes' own inside it (a probe run inside bubblewrap asks for new user, PID, network, IPC and UTS namespaces in one call, as the engine's content sandbox makes them, then uses a capability inside them, since a policy can allow the namespaces and deny their capabilities afterwards; [#282](https://github.com/nulavio/nulavio/issues/282)): each is an error, never an unconfined start or a weaker one; a profile that is already open is not reopened through the running (unconfined) instance.

What it changes and what it does not (bypass analysis). The "Yes" rows rest on bubblewrap's own user namespace, as Fedora's and Ubuntu's unprivileged bubblewrap makes it; a setuid bubblewrap (no user namespace) was not checked:

| Path | Blocked? | Why |
|---|---|---|
| A compromised browser reads `~/.ssh`, `~/.aws`, documents, other apps' data, other profiles | **Yes** | Not mounted in its namespace: the home folder, the runtime folder and Nulavio's own folders are empty there |
| A compromised browser writes a startup file (`~/.bashrc`, `~/.config/autostart`) | **Yes** | The home folder is an in-memory copy; nothing written there reaches the disk. The session bus, the user's service manager, an X server, the session's terminals and input devices, through which other programs could be started or typed into outside the namespace, are not reachable from it |
| A native-messaging host the browser starts reads the home folder | **Yes** | It runs inside the same namespace. A host that needs files in the home folder, or a socket other than KeePassXC's (put back when KeePassXC is running before the confined start), fails; run that profile without `--confined` |
| A compromised browser talks to other programs over the session bus (the service manager, Secret Service, KWallet, the desktop) | **Yes** | The bus is not there inside. An allow-list through `xdg-dbus-proxy` (portals, notifications, media keys) would bring those back; not adopted |
| A compromised browser uses an agent or another program's socket in the runtime folder (SSH, GnuPG, KWallet, containers), or another session's temporary profile | **Yes** | The runtime folder is empty inside except the display and sound sockets |
| A compromised browser reads or types into other windows through an X server | **Yes** on Wayland | No X socket folder, cookie or `DISPLAY` inside; a session with X11 only is refused |
| A compromised browser shares files with the host through `/dev/shm` | **Yes** | Its own, in memory |
| A compromised browser opens the host's device nodes: input devices (`/dev/input`, `/dev/uinput`), the session's terminals (`/dev/pts`), HID, `kvm`, `fuse`, sound or other hardware | **Yes** | `/dev` is bubblewrap's own; only the GPU and the cameras present at the start are put back. The terminal `nulavio run` was started from, when there is one, stays open to the browser as its standard input (and output, with `--engine-output`); `--new-session` keeps it from typing commands into that terminal |
| A compromised browser attaches to another program's System V shared memory, semaphores or message queues | **Yes** | Its own IPC namespace |
| A compromised browser reaches a program listening on an abstract Unix socket (an X server, among others) | **No** | Those belong to the network namespace, which the browser shares with the host. An X server that lets the user's programs in without its cookie (`xhost +si:localuser:…`) is reachable this way |
| A compromised browser uses what Wayland, PipeWire, PulseAudio, the GPU, the cameras and the system bus offer any program of the user | **No** | Put back or left for display, sound, camera and microphone. The browser is an ordinary client of the user's sound server, not limited to playing and recording, and of the compositor: protocols some compositors offer any client (input, screen capture, clipboard) are offered to it too. The system bus has its own policy |
| A compromised browser connects to system services' sockets under `/run` (printing, smart cards, a container engine or libvirt for a user in its group) or to services listening on loopback | **No** | Those are outside the user's runtime folder and stay visible read-only, and a socket under a read-only mount still accepts connections; the network namespace is shared. Each service applies its own access policy, as for any program of the user |
| A compromised browser reads other processes' command lines in `/proc` | **No** | No PID namespace (the profile lock needs real PIDs) |
| A program running as the user reads the profile from outside | **No** | Confinement applies to the browser, not to other programs ([S11](threat-model.md#s11--local-malicious-process-as-the-same-user-infostealer)) |
| Files in Downloads | **No** | Writable by design |
| Uploads | Limited | Only the profile and Downloads exist inside, so a page can be given files from Downloads only |

Not adopted as the default: uploads only from Downloads; no security keys (WebAuthn over HID), gamepads or sound devices opened directly (sound goes through PipeWire or PulseAudio), and a camera plugged in after the start is not there; without the session bus the browser has no portals (screen sharing on Wayland among them), desktop notifications, media keys, accessibility bus, hand-off of a link to the running instance, or Connect status from inside (each reached through that bus; not each measured); Nulavio features that keep data in the Nulavio data folder (protected profiles' unlock, AI Bridge settings) do not reach it from inside, and on Ubuntu it costs the engine's per-process namespaces ([below](#bubblewrap-on-ubuntu)). Profiles of the engine's profile group (Track B's menu entry) are started by the engine, not by the launcher, so they are not confined.

Verification: `tests/unit/test_confine.py` (argument list: home, runtime folder and Nulavio's folders hidden before anything is put back, only the profile and Downloads writable, only the display and sound sockets put back, no session bus or X server passed, an X11-only session refused, bubblewrap's own `/dev` with only the GPU and camera nodes put back and its own IPC namespace, read-only settings only when present, no option that would weaken the engine's sandbox, Downloads never the home folder, missing bubblewrap is an error; real bubblewrap runs where a program cannot see a file in the home folder, its writes elsewhere never reach the disk, it connects to the Wayland and PipeWire sockets but not to the session bus, the service manager or an agent, it does not see another profile, the host's `/dev/shm` is not shared, and it sees no terminal of the session, no input or other host device node and no System V segment made outside) and `tests/integration/test_confined.py` (the real engine: started inside bubblewrap, sees only its profile and Downloads, and in `/dev` only bubblewrap's own nodes and the GPU and cameras, same sandbox level, every web content process under seccomp, an open profile is not reopened confined).

### bubblewrap on Ubuntu

Run on 2026-11-14 for #228 in a full VM: Ubuntu 26.04 LTS cloud image, kernel 7.0.0-38, `kernel.apparmor_restrict_unprivileged_userns=1`, the 160.0-0.4 `.deb` installed by the site's APT instructions, bubblewrap 0.11.1, the launcher from a checkout with `NULAVIO_ENGINE=/usr/lib/nulavio/nulavio`. For each process the engine started on a page, `/proc/<pid>/ns/*` and `Seccomp:`:

| | Own user namespace (content, socket, RDD, utility) | Own network namespace (content, RDD, utility) | seccomp-bpf |
|---|---|---|---|
| Ubuntu, without `--confined` | yes (not the fork server, which runs in the engine's) | yes | mode 2 |
| Ubuntu, `--confined` | **no**: the engine's | **no**: the host's | mode 2 |
| Fedora 44, without bubblewrap | yes | yes | mode 2 |
| Fedora 44, under the same bubblewrap mounts | yes | yes | mode 2 |

Ubuntu's `bwrap-userns-restrict` profile (in the `apparmor` package) moves every program bubblewrap starts to `&bwrap//&unpriv_bwrap`, which has `audit deny capability`. The transition is named, so the `.deb`'s `nulavio` profile never applies inside. The engine's `CanCreateUserNamespace()` check fails (`unshare(CLONE_NEWPID): EPERM`; the kernel logs `apparmor="DENIED" operation="capable" profile="unpriv_bwrap" capname="sys_admin"`), and the engine runs its content processes with seccomp-bpf alone, without saying so. The home folder is still hidden: the engine saw only `Downloads` and the profile under `/proc/<engine>/root/home/<user>`. A rule in `local/unpriv_bwrap` would change it for every bubblewrap user on the machine, so the package does not ship one; a narrower route (for example a bubblewrap of Nulavio's own with its own profile) was not tried. On Ubuntu the confined mode would therefore trade one layer for the other. The maintainer chose on 2026-11-14 that it refuses ([#282](https://github.com/nulavio/nulavio/issues/282)): before starting, the launcher runs a probe inside bubblewrap that asks for the namespaces the engine's content sandbox needs, and when they are refused it does not start, says why, and says that without `--confined` the engine's sandbox is whole but the browser sees the whole home folder. Checked in the same VM on 2026-11-14: the probe is refused there (`Operation not permitted`; the kernel logs `profile="unpriv_bwrap" capname="sys_admin"`), and passes on Fedora 44 with bubblewrap 0.12.0. Run outside bubblewrap on that VM, it is refused too (`profile="unprivileged_userns"`), the same denial the unconfined engine met in the AppArmor measurement below: the probe catches a capability denied after the namespace was made, not only a namespace that could not be made.

## AppArmor on Ubuntu

Found while checking bubblewrap: Ubuntu 23.10 and later (`kernel.apparmor_restrict_unprivileged_userns=1`) let a program create unprivileged user namespaces only when an AppArmor profile allows it. Gecko's content sandbox uses them; without them it falls back to a weaker sandbox. Ubuntu ships such profiles for other browsers; the Nulavio `.deb` had none.

Adopted: `packaging/linux/apparmor-nulavio`, installed as `/etc/apparmor.d/nulavio` (a conffile): `profile nulavio /usr/lib/nulavio/nulavio{,-bin} flags=(unconfined) { userns, }`, the same shape as Ubuntu's own profiles. It confines nothing and grants only user namespaces. The package's only maintainer scripts load it after install and unload it on removal (`apparmor_parser`, as `dh_apparmor` does); the RPM still has none. `check_deb.sh` installs the package in a clean Ubuntu 26.10 container and checks that the profile parses. On a real Ubuntu host on 2026-11-13 (26.04.1 LTS, KDE, kernel 7.0.0-43, the 160.0-0.3 `.deb`): with `kernel.apparmor_restrict_unprivileged_userns=1` and the profile loaded, 8 of the 9 processes the engine starts (every content, socket, RDD and utility process; not the fork server) ran in a user namespace of their own, with seccomp-bpf (`Seccomp: 2`) and `NoNewPrivs`; with the profile unloaded, none did, and the kernel log showed the engine moved to Ubuntu's `unprivileged_userns` profile and refused `sys_admin` there. Seccomp stayed on in both. The PID namespace was the parent's in both runs (with the fork server, processes are forked rather than cloned into a new one), which is how the engine starts them and not a difference the profile makes. The same package installs and renders a page headless in a clean Ubuntu 24.04.5 container.

## Flatpak and native messaging

The blocker recorded in [hardening](hardening.md) was native messaging: password managers (KeePassXC, Bitwarden's biometric unlock) need the browser to start a host program, which a Flatpak cannot see or run.

Measured:

- Gecko 158 has both client paths: the WebExtensions portal (`widget.use-xdg-desktop-portal.native-messaging`) and the newer native-messaging proxy (`widget.use-xdg-desktop-portal.native-messaging-proxy`, design in the engine's `toolkit/components/extensions/docs/native-messaging-portal-design.md`); both default to off outside Flatpak and Snap.
- The WebExtensions portal is **not** in xdg-desktop-portal 1.22.1 (this host's portal lists no `org.freedesktop.portal.WebExtensions`); upstream it is still a pull request, and Ubuntu carries it as a distribution patch.
- The proxy, `xdg-native-messaging-proxy` 0.1.0, **is packaged**: Fedora 44 (`fedora` repository, not installed by default) and Ubuntu 26.04, 26.10 and 27.04 ([Launchpad](https://launchpad.net/ubuntu/+source/xdg-native-messaging-proxy)). It runs on the host, reads the host's native-messaging manifests and starts the host program for the sandboxed browser.

Decision: **not now**. The blocker is gone on the two target systems, but a Flatpak brings no confinement that the bubblewrap mode does not, and it costs a second packaging and update path (runtime updates, Flathub review, a second SLA). The proxy is the path when a Flatpak is wanted (for example for immutable systems); it would need a test with a stand-in native host through the proxy before release. Not installed here: the spike does not install system packages.

**Revisited 2026-11-11: adopted as a second channel, for reach.** Flathub installs on distributions Nulavio has no repository for (Arch, openSUSE, Mint, immutable systems), and the release workflow now builds the Flatpak from the same signed build in every run, so it adds no build and its update path is a pull request per release. The confinement argument above still holds: the Flatpak is for reach, not for more isolation. It turns the proxy on (`widget.use-xdg-desktop-portal.native-messaging-proxy=1`); the Vault, the confined mode and the D-Bus Connect features stay out of it ([build](../architecture/build.md#flatpak-flathub)). Still open: the test with a stand-in native host through the proxy.

## SELinux

Measured: SELinux enforcing; the Nulavio engine runs as `unconfined_u:unconfined_r:unconfined_t`, as Fedora's Firefox does (Fedora's old `mozilla_t` domain is not used for the browser).

Decision: **not adopted**. A policy module needs root to install (`semodule -i`) on every machine and per-release maintenance against Gecko's needs (user namespaces and seccomp for its own sandbox, GPU, D-Bus, portals, PipeWire, native-messaging hosts). A wrong rule either breaks the browser or is too broad to matter. bubblewrap gives the part that matters here (what files a compromised browser can reach) without root and with a test. Revisit if a distribution ships a maintained browser domain.

## Sensitive sites

The [threat model](threat-model.md) (S15) planned a "sensitive sites" container where only the chosen password provider is allowed, cleared on close.

Why a profile and not a container: engine containers (`userContextId`) separate cookies but share every extension, so an extension with access to all sites would still see the bank's pages. A separate profile has its own extension set, its own storage and its own process; routing rules (ADR 0003) already send chosen sites to a profile.

Adopted: a fifth template, **Sensitive sites** (Settings → Profiles and the toolbar selector). At creation, before its first start, Nulavio writes these engine settings into the new profile's `user.js`:

| Setting | Effect |
|---|---|
| `privacy.sanitize.sanitizeOnShutdown` and `privacy.clearOnShutdown_v2.{cookiesAndStorage, cache, browsingHistoryAndDownloads, formdata}` | Cookies, site data, cache, history, download list and form history are deleted every time the profile closes (the engine's own clearing) |
| `browser.formfill.enable` = false | Form history is not kept |
| `xpinstall.enabled` = false | Web pages, including addons.mozilla.org, cannot start an extension install. An explicit file install in the Add-ons page and Nulavio's password-provider chooser still work |

It starts with no extension but what every profile gets (the built-in Nulavio Shell and, in the Nulavio build, uBlock Origin by policy); the user adds only the password manager they trust. Saved logins in the engine's manager are not cleared (they are not site data).

Limits: deleting `user.js` turns the settings off (Settings shows the profile as sensitive only while the file says so); clearing happens at a normal close, so after a crash the data stays until the next close; it does not protect against a program running as the user while the profile is open.

Verification: `tests/integration/test_profiles.py` 11: the file is written, the running profile has the settings, a cookie, site storage and a history entry are gone after it closes and reopens, and Settings marks it.
