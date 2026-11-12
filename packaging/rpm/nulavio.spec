# Nulavio, packaged from the Track B build (scripts/build/build_nulavio.sh) by
# scripts/release/make_rpm.sh in a disposable Fedora container. The engine is
# built from Mozilla's verified source release with Nulavio's patches; this
# spec only lays the built tree out on the system, owned by root, so programs
# running as the user cannot modify the browser (hardening.md, Guard R38).

%global nulavio_dir %{_libdir}/nulavio
# The tree is already stripped and carries its own libraries: no debuginfo,
# no automatic "Provides" for the private libraries (nothing else links to them).
%global debug_package %{nil}
%global __provides_exclude_from ^%{nulavio_dir}/.*$
%global __requires_exclude ^(libxul|libmoz.*|libnss3|libnssutil3|libsmime3|libssl3|libsoftokn3|libfreeblpriv3|libnspr4|libplc4|libplds4|liblgpllibs|libgkcodecs|libonnxruntime)\\.so.*$
%global __brp_strip %{nil}
%global __brp_strip_static_archive %{nil}
%global __brp_strip_comment_note %{nil}
%global __brp_mangle_shebangs %{nil}

Name:           nulavio
Version:        %{nulavio_version}
Release:        %{nulavio_release}%{?dist}
Summary:        Private, calm web browser built on the Gecko engine
# The browser is MPL-2.0. One data file in it is not: distribution/policies.json carries a modified copy of
# uBlock Origin's filter list registry, GPL-3.0-only, with the licence text and a notice of the change beside it
# (uBlock-Origin-LICENSE.txt, uBlock-Origin-NOTICE.txt); LICENSES.md lists it.
License:        MPL-2.0 AND GPL-3.0-only
URL:            https://nulavio.net
Source0:        nulavio-tree.tar
Source1:        nulavio.desktop
ExclusiveArch:  x86_64

# The Nulavio tools (Vault, AI Bridge, temporary profiles) run on the system Python.
Requires:       python3 >= 3.12
Requires:       util-linux
Requires:       hicolor-icon-theme
# Protected profiles: encryption (libsodium) and storage (gocryptfs on FUSE).
Recommends:     libsodium
Recommends:     gocryptfs
Recommends:     fuse3

%description
Nulavio is a browser for Linux that keeps your data with you: tracking
protection in its strict setting, uBlock Origin from the start, HTTPS-Only,
no telemetry to Nulavio (there is no Nulavio server), separate profiles,
encrypted profiles at rest, and an AI Bridge whose permissions you decide.

%prep
%setup -q -c -T
tar -xf %{SOURCE0}

%build
# Built by scripts/build/build_nulavio.sh (Mozilla's source release, Nulavio's patches).

%install
mkdir -p %{buildroot}%{nulavio_dir} %{buildroot}%{_bindir}
cp -a nulavio/. %{buildroot}%{nulavio_dir}/
# The launcher entry runs the engine from its fixed place; profiles stay in the user's home.
cat > %{buildroot}%{_bindir}/nulavio <<'SH'
#!/bin/sh
exec %{nulavio_dir}/nulavio "$@"
SH
chmod 0755 %{buildroot}%{_bindir}/nulavio
install -Dm0644 %{SOURCE1} %{buildroot}%{_datadir}/applications/nulavio.desktop
for size in 16 32 48 64 128; do
  install -Dm0644 nulavio/browser/chrome/icons/default/default${size}.png \
    %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/nulavio.png
done

%files
%license nulavio/LICENSE*
%{nulavio_dir}
%{_bindir}/nulavio
%{_datadir}/applications/nulavio.desktop
%{_datadir}/icons/hicolor/*/apps/nulavio.png

%changelog
* Mon Oct 26 2026 Caio Barbieri <caio@lombello.com> - %{nulavio_version}-%{nulavio_release}
- Packaged from the Track B build.
