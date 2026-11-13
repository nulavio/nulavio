# Phase 5 spikes: outer confinement, Flatpak, SELinux, sensitive sites

- **Date:** 2026-10-27
- **Slice:** S23 ([execution plan](../product/execution-plan.md)). Each spike ends with a decision and, where adopted, a test.
- **Host measured:** Fedora 44, KDE Plasma, SELinux enforcing, bubblewrap 0.12.0, xdg-desktop-portal 1.22.1, Flatpak 1.18.4. Engine: Nulavio build of Firefox 158.0.1.
- **What none of this changes:** a program running as the same user outside the browser can still read the browser's files ([threat model S11](threat-model.md#s11--local-malicious-process-as-the-same-user-infostealer)). Outer confinement limits what a *compromised browser* can reach; it does not stop an infostealer.

| Spike | Decision |
|---|---|
| [bubblewrap](#bubblewrap) | **Adopted as an opt-in**: `nulavio run --confined` (profiles the Nulavio tools run). The browser sees only its profile and Downloads in the home folder; the engine's own sandbox is unchanged (`test_confine`, `test_confined`) |
| [Flatpak and native messaging](#flatpak-and-native-messaging) | **Not now.** Native messaging is solvable (the host-side proxy ships in Fedora 44 and Ubuntu 26.04+), but a Flatpak adds a second sandbox layout, a second update channel and Flathub publishing for no gain over bubblewrap on the same host. Revisit after the RPM/DEB channel is public |
| [SELinux](#selinux) | **Not adopted.** Installing a policy module needs root on every machine; the browser runs `unconfined_t` like Fedora's Firefox; bubblewrap gives the filesystem part without root |
| [AppArmor on Ubuntu](#apparmor-on-ubuntu) | **Adopted** (found during this slice): the `.deb` ships a profile that lets the engine create the user namespaces its content sandbox needs on Ubuntu 24.04 and later, and nothing else (`check_deb.sh`) |
| [Sensitive sites](#sensitive-sites) | **Adopted** as a profile template, not a container: "Sensitive sites" deletes cookies, site data, history and cache when it closes and refuses extension installs from web pages (`test_profiles` 11) |

## bubblewrap

Question: can the whole browser run inside bubblewrap, hiding the home folder, without weakening the engine's own sandbox?

Measured (Nulavio build and distribution Firefox 158, headless and with a real profile, chrome code reading files, `/proc` for every process):

| | Without | With `--confined` |
|---|---|---|
| A file elsewhere in the home folder (an artificial `~/.ssh/id_fake`, the real `~/.ssh`) | readable | **not there** |
| Profile and Downloads | writable | writable |
| Content sandbox level (`about:support`) | 6 | 6 |
| User namespaces, seccomp-bpf available to the engine | yes | yes |
| Web content processes under seccomp (`/proc/<pid>/status`) | all (mode 2) | all (mode 2) |
| Profile lock PID | real | real |

Design (`launcher/nulavio_launcher/confine.py`):

- `--ro-bind / /`, then empty in-memory folders over `/home`, the user's home, `/tmp`, `/var/tmp`, `/mnt`, `/media`, `/run/media`.
- Put back read-write: the profile and the Downloads folder (from the desktop's folder names; never the home folder itself). Read-only: fonts, GTK and KDE appearance settings, the desktop's folder names, `mimeapps.list`, `.Xauthority`, registered native-messaging hosts, the engine's folder. The runtime folder (`$XDG_RUNTIME_DIR`: Wayland, PipeWire, the session bus, portals) and the X11 socket folder.
- No PID namespace: the profile lock keeps real PIDs, so the launcher still sees a running profile. User namespaces stay available (no `--disable-userns`), so the engine still builds its own content sandboxes. `--new-session`; `--die-with-parent` when the launcher supervises (temporary and protected profiles).
- Refusals: no `bwrap`, or it cannot create namespaces here, is an error, never an unconfined start; a profile that is already open is not reopened through the running (unconfined) instance.

What it changes and what it does not (bypass analysis):

| Path | Blocked? | Why |
|---|---|---|
| A compromised browser reads `~/.ssh`, `~/.aws`, documents, other apps' data, other profiles | **Yes** | Not mounted in its namespace |
| A compromised browser writes a startup file (`~/.bashrc`, `~/.config/autostart`) | **Yes** | The home folder is an in-memory copy; nothing written there reaches the disk |
| A native-messaging host the browser starts reads the home folder | **Yes** | It runs inside the same namespace. A host that needs files in the home folder (beyond a socket in the runtime folder, as KeePassXC's proxy uses) fails; run that profile without `--confined` |
| A compromised browser talks to other programs over the session bus (Secret Service, KWallet, the desktop) | **No** | The bus is not filtered (`xdg-dbus-proxy` would, at the cost of portals and integrations; not adopted) |
| A program running as the user reads the profile from outside | **No** | Confinement applies to the browser, not to other programs ([S11](threat-model.md#s11--local-malicious-process-as-the-same-user-infostealer)) |
| Files in Downloads | **No** | Writable by design |
| Uploads | Limited | Only the profile and Downloads exist inside, so a page can be given files from Downloads only |

Not adopted as the default: uploads only from Downloads, Nulavio features that keep data in the Nulavio data folder (protected profiles' unlock, AI Bridge settings) do not reach it from inside, and on Ubuntu bubblewrap's own user namespaces depend on AppArmor's policy for `bwrap` (not tested on a real Ubuntu host). Profiles of the engine's profile group (Track B's menu entry) are started by the engine, not by the launcher, so they are not confined.

Verification: `tests/unit/test_confine.py` (argument list: home hidden, only the profile and Downloads writable, read-only settings only when present, no option that would weaken the engine's sandbox, Downloads never the home folder, missing bubblewrap is an error; a real bubblewrap run where a program cannot see a file in the home folder and its writes elsewhere never reach the disk) and `tests/integration/test_confined.py` (the real engine: started inside bubblewrap, sees only its profile and Downloads, same sandbox level, every web content process under seccomp, an open profile is not reopened confined).

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
