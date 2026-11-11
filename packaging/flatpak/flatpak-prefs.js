// Flatpak only (installed as browser/defaults/preferences/flatpak.js). Native messaging
// (password-manager apps, KDE integration) goes through xdg-native-messaging-proxy on the
// host, which reads the host's manifests and starts the host program; Gecko's default is
// off. docs/security/phase5-spikes.md, "Flatpak and native messaging".
pref("widget.use-xdg-desktop-portal.native-messaging-proxy", 1);
