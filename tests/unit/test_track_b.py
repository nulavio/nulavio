"""Track B (source build) inputs: mozconfig, patch stack, branding."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

import apply_patches  # noqa: E402
import fetch_firefox_l10n  # noqa: E402
import make_distribution  # noqa: E402

MOZCONFIG = ROOT / "browser" / "build" / "mozconfig"
BRANDING = ROOT / "browser" / "branding" / "nulavio"
FORBIDDEN_OPTIONS = (
    "--disable-sandbox",
    "--enable-debug",
    "--disable-fission",
    "MOZ_REQUIRE_SIGNING=0",
    "--with-unsigned-addon-scopes",
    "--enable-official-branding",  # Mozilla trademarks
)


def active_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


class MozconfigTest(unittest.TestCase):
    def setUp(self):
        self.lines = active_lines(MOZCONFIG.read_text())

    def test_required_options(self):
        for required in (
            "ac_add_options --with-branding=browser/branding/nulavio",
            "ac_add_options MOZ_REQUIRE_SIGNING=1",
            "ac_add_options --with-app-name=nulavio",
            "ac_add_options --enable-release",
            # System native-messaging hosts are in /usr/lib64/mozilla on Fedora (Nulavio Connect).
            "ac_add_options --libdir=/usr/lib64",
        ):
            self.assertIn(required, self.lines)

    def test_rust_lto_is_thin_and_reaches_cargo(self):
        """Fat Rust LTO does not fit the build laptop. Only "export" lines reach the makefiles that run Cargo:
        without the word, the release build silently goes back to the fat pass (seen on 2026-11-09)."""
        self.assertIn('mk_add_options "export CARGO_RUSTCFLAGS=-Clto=thin"', self.lines)

    def test_no_weakening_or_mozilla_branding(self):
        joined = "\n".join(self.lines)
        for option in FORBIDDEN_OPTIONS:
            self.assertNotIn(option, joined)

    def test_secrets_never_committed(self):
        for line in self.lines:
            if "keyfile" in line:
                self.assertRegex(line, r"keyfile=/run/secrets/", "API keys must come from a secret mount")
        self.assertIn(
            "ac_add_options --with-google-safebrowsing-api-keyfile=/run/secrets/google-safebrowsing.key",
            self.lines,
            "the Safe Browsing key must be wired from the secret mount",
        )

    def test_build_script_requires_safe_browsing_key(self):
        script = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text()
        self.assertIn("/run/secrets/google-safebrowsing.key:ro", script, "key must be mounted read-only")
        self.assertIn("NULAVIO_ALLOW_NO_SAFEBROWSING_KEY", script, "building without a key must be an explicit opt-out")
        self.assertRegex(script, r"missing Google Safe Browsing key[^\n]*\n[^\n]*\n\s*exit 2", "missing key must fail")

    def test_no_api_key_material_in_repo(self):
        pattern = re.compile(r"AIza[0-9A-Za-z_-]{35}")
        offenders = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            try:
                if pattern.search(path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(ROOT)))
            except (UnicodeDecodeError, OSError):
                continue
        self.assertEqual(offenders, [], "Google API key material committed")


class BrandingPrefsTest(unittest.TestCase):
    def test_restores_official_devtools_defaults(self):
        # Without MOZILLA_OFFICIAL the engine enables the privileged Browser Console and
        # remote debugging by default (modules/libpref/init/all.js).
        text = (BRANDING / "pref" / "firefox-branding.js").read_text()
        for pref in (
            "devtools.chrome.enabled",
            "devtools.debugger.remote-enabled",
            "browser.dom.window.dump.enabled",
            "devtools.console.stdout.chrome",
        ):
            self.assertIn(f'pref("{pref}", false, sticky);', text)
        self.assertIn('pref("devtools.selfxss.count", 0);', text)

    def test_safe_browsing_lists_match_what_the_key_can_fetch(self):
        text = (BRANDING / "pref" / "firefox-branding.js").read_text()
        lists = re.search(r'pref\("browser\.safebrowsing\.provider\.google5\.lists", "([^"]+)"\)', text)
        self.assertIsNotNone(lists)
        names = lists.group(1).split(",")
        for required in ("googpub-phish-proto", "goog-malware-proto", "goog-unwanted-proto", "goog-harmful-proto"):
            self.assertIn(required, names)
        for unavailable in ("goog-badbinurl-proto", "goog-downloadwhite-proto"):
            self.assertNotIn(unavailable, names, "one unavailable list makes the whole batch update fail")


class LocalizationTest(unittest.TestCase):
    REV = "1e95d1c5f519c3fbde715345ae7beb56a2c79077"

    def source(self, changesets: dict) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "browser" / "locales").mkdir(parents=True)
        (tmp / "browser" / "locales" / "l10n-changesets.json").write_text(json.dumps(changesets))
        return tmp

    def test_revision_comes_from_the_verified_source(self):
        src = self.source({"pt-BR": {"platforms": ["linux64"], "revision": self.REV}})
        self.assertEqual(fetch_firefox_l10n.revisions(src, ["pt-BR"]), {"pt-BR": self.REV})

    def test_rejects_unknown_unshipped_or_malformed_input(self):
        src = self.source(
            {
                "pt-BR": {"platforms": ["win64"], "revision": self.REV},
                "de": {"platforms": ["linux64"], "revision": "main"},
            }
        )
        for locales in (["pt-BR"], ["de"], ["xx"], ["../etc"]):
            with self.subTest(locales=locales), self.assertRaises(SystemExit):
                fetch_firefox_l10n.revisions(src, locales)

    def test_brand_translation_matches_english_ids_and_keeps_the_name(self):
        def ids(path: Path) -> set[str]:
            lines = path.read_text().splitlines()
            return {line.split("=")[0].strip() for line in lines if "=" in line and not line.startswith("#")}

        en = BRANDING / "locales" / "en-US"
        pt = ROOT / "browser" / "l10n" / "pt-BR" / "browser" / "branding" / "nulavio"
        self.assertEqual(ids(en / "brand.ftl"), ids(pt / "brand.ftl"))
        self.assertEqual(ids(en / "brand.properties"), ids(pt / "brand.properties"))
        for line in (pt / "brand.ftl").read_text().splitlines():
            if line.startswith("-"):
                self.assertTrue(line.endswith("= Nulavio"), line)

    def test_branding_strings_are_localizable_and_follow_the_os(self):
        jar = (BRANDING / "locales" / "jar.mn").read_text()
        self.assertIn("(%*.ftl)", jar)
        self.assertIn("(%brand.properties)", jar)
        self.assertIn('pref("intl.locale.requested", "");', (BRANDING / "pref" / "firefox-branding.js").read_text())

    def test_build_packages_the_locales(self):
        script = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text()
        self.assertIn("fetch_firefox_l10n.py", script)
        self.assertIn("package-multi-locale --locales en-US", script)


class PatchStackTest(unittest.TestCase):
    def test_series_is_small_and_documented(self):
        patches = apply_patches.series()
        self.assertLessEqual(len(patches), 10, "ADR 0001: reconsider ESR if the patch stack exceeds ~10 patches")
        for patch_file in patches:
            with self.subTest(patch=patch_file.name):
                self.assertTrue(patch_file.is_file())
                text = patch_file.read_text()
                self.assertRegex(text, r"(?m)^Owner: ")
                self.assertRegex(text, r"(?m)^Upstream: ")
                self.assertRegex(patch_file.name, r"^\d{4}-[a-z0-9-]+\.patch$")
                self.assertNotRegex(text, r"(?m)^[-+].*(security\.sandbox|MOZ_DISABLE_.*SANDBOX|xpinstall\.signatures)")


CONF = 'line1\nvendor = "Mozilla"\nappid = "x"\ndevtools = "all"\n'
# Two patches on neighbouring lines of one file, like 0001 (vendor) and 0009 (User-Agent name)
# in browser/moz.configure: with the second applied, the first neither reverses nor applies alone.
VENDOR = """--- a/conf.txt
+++ b/conf.txt
@@ -1,4 +1,4 @@
 line1
-vendor = "Mozilla"
+vendor = "Nulavio"
 appid = "x"
 devtools = "all"
"""
UA_NAME = """--- a/conf.txt
+++ b/conf.txt
@@ -1,4 +1,5 @@
 line1
 vendor = "Nulavio"
+ua = "Firefox"
 appid = "x"
 devtools = "all"
"""
BOTH = 'line1\nvendor = "Nulavio"\nua = "Firefox"\nappid = "x"\ndevtools = "all"\n'


class ApplyPatchesTest(unittest.TestCase):
    """A tree an earlier build patched is built again (the release rehearsal on 2026-11-10 stopped here)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-patches-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = self.tmp / "src"
        self.source.mkdir()
        (self.source / "conf.txt").write_text(CONF)
        self.patches = []
        for name, text in (("0001-vendor.patch", VENDOR), ("0002-ua-name.patch", UA_NAME)):
            (self.tmp / name).write_text(text)
            self.patches.append(self.tmp / name)

    def run_series(self):
        lines = []
        apply_patches.apply_series(self.source, self.patches, log=lines.append)
        return lines

    def test_fresh_tree_gets_the_whole_series(self):
        self.assertEqual(self.run_series(), ["+ 0001-vendor.patch", "+ 0002-ua-name.patch"])
        self.assertEqual((self.source / "conf.txt").read_text(), BOTH)

    def test_a_patched_tree_is_left_as_it_is(self):
        self.run_series()
        self.assertEqual(self.run_series(), ["= 0001-vendor.patch (already applied)", "= 0002-ua-name.patch (already applied)"])
        self.assertEqual((self.source / "conf.txt").read_text(), BOTH)
        # Checked on its own, the first patch neither reverses nor applies: the old check stopped here.
        self.assertFalse(apply_patches.patch(self.source, self.patches[0], "--reverse", "--check"))
        self.assertFalse(apply_patches.patch(self.source, self.patches[0], "--check"))

    def test_a_tree_with_the_head_of_the_series_gets_the_rest(self):
        self.assertTrue(apply_patches.patch(self.source, self.patches[0]))
        self.assertEqual(self.run_series(), ["= 0001-vendor.patch (already applied)", "+ 0002-ua-name.patch"])
        self.assertEqual((self.source / "conf.txt").read_text(), BOTH)

    def test_a_patch_that_does_not_fit_stops_the_build(self):
        (self.source / "conf.txt").write_text(CONF.replace("appid", "app_id"))
        with self.assertRaises(SystemExit):
            self.run_series()


class BrandingTest(unittest.TestCase):
    def test_names_are_nulavio(self):
        ftl = (BRANDING / "locales" / "en-US" / "brand.ftl").read_text()
        for key in ("-brand-shorter-name", "-brand-short-name", "-brand-full-name", "-brand-product-name"):
            self.assertRegex(ftl, rf"(?m)^{key} = Nulavio$")
        props = (BRANDING / "locales" / "en-US" / "brand.properties").read_text()
        self.assertNotRegex(props, r"(?i)firefox|nightly")
        self.assertIn("MOZ_APP_DISPLAYNAME=Nulavio", (BRANDING / "configure.sh").read_text())

    def test_no_mozilla_marks_outside_the_disclaimer(self):
        for path in BRANDING.rglob("*"):
            if path.is_dir() or path.name in {"moz.build", "jar.mn"}:
                continue
            for line in active_lines(path.read_text()):
                if line.startswith(("//", "/*", "*")) or "Source Code Form" in line or "mozilla.org/MPL" in line:
                    continue
                if "not affiliated with Mozilla" in line or "Gecko engine by Mozilla" in line:
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), line=line):
                    self.assertNotRegex(line, r"(?i)\bfirefox\b|\bnightly\b")

    def test_self_xss_gate_stays_on(self):
        prefs = (BRANDING / "pref" / "firefox-branding.js").read_text()
        self.assertIn('pref("devtools.selfxss.count", 0);', prefs)

    @unittest.skipUnless(shutil.which("magick"), "ImageMagick not installed")
    def test_generator_produces_every_jar_entry(self):
        import make_branding

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nulavio"
            make_branding.build(target)
            jar = (target / "content" / "jar.mn").read_text()
            for match in re.finditer(r"^\s+content/branding/(\S+)(?:\s+\((\S+)\))?", jar, re.M):
                source = match.group(2) or match.group(1)
                with self.subTest(entry=match.group(1)):
                    self.assertTrue((target / "content" / source).resolve().exists(), source)
            for size in (16, 32, 48, 64, 128):
                self.assertTrue((target / f"default{size}.png").exists())


class DistributionTest(unittest.TestCase):
    def test_ini_contains_seed_prefs_as_defaults(self):
        ini = make_distribution.distribution_ini()
        self.assertIn("[Preferences]", ini)
        self.assertIn("dom.security.https_only_mode=true", ini)
        # Only works as a user value; the Shell sets it once per profile (NulavioPrivacy.seedDefaults).
        self.assertNotIn("browser.contentblocking.category", ini)
        shell = (ROOT / "browser" / "shell" / "modules" / "NulavioPrivacy.sys.mjs").read_text(encoding="utf-8")
        self.assertIn('Services.prefs.setStringPref("browser.contentblocking.category", "strict")', shell)
        self.assertNotIn("@STARTPAGE_URL@", ini)
        self.assertNotRegex(ini, r"(?m)^security\.sandbox|^xpinstall\.signatures")

    def test_policies_install_pinned_filter_without_forcing(self):
        data = make_distribution.policies()
        settings = data["policies"]["ExtensionSettings"]
        self.assertEqual(list(settings), ["uBlock0@raymondhill.net"])
        ublock = settings["uBlock0@raymondhill.net"]
        self.assertEqual(ublock["installation_mode"], "normal_installed", "users must be able to disable it")
        self.assertTrue(ublock["install_url"].startswith("https://addons.mozilla.org/"))
        self.assertTrue(ublock["private_browsing"])
        self.assertNotIn("*", settings, "do not block user-installed extensions by default")


if __name__ == "__main__":
    unittest.main()


class ToolsBundleTest(unittest.TestCase):
    def test_tools_are_copied_next_to_the_build(self):
        import importlib.util
        import tempfile

        spec = importlib.util.spec_from_file_location("make_tools", ROOT / "scripts" / "build" / "make_tools.py")
        make_tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(make_tools)
        out = Path(tempfile.mkdtemp()) / "nulavio-tools"
        try:
            make_tools.build(out)
            self.assertTrue((out / "bin" / "nulavio").stat().st_mode & 0o111)
            self.assertTrue((out / "launcher" / "nulavio_launcher" / "vault" / "cli.py").is_file())
            self.assertTrue((out / "browser" / "config" / "prefs" / "baseline.js").is_file())
            self.assertFalse(list(out.rglob("__pycache__")))
        finally:
            import shutil

            shutil.rmtree(out.parent, ignore_errors=True)


class PackagingTest(unittest.TestCase):
    """RPM and .deb (phase 6): one engine build, root-owned install, identity that matches the build."""

    def test_desktop_entry_matches_the_build_identity(self):
        desktop = (ROOT / "packaging" / "linux" / "nulavio.desktop").read_text(encoding="utf-8")
        mozconfig = (ROOT / "browser" / "build" / "mozconfig").read_text(encoding="utf-8")
        self.assertIn("ac_add_options MOZ_APP_REMOTINGNAME=nulavio", mozconfig)
        self.assertIn("StartupWMClass=nulavio\n", desktop)  # the Wayland app_id is the remoting name
        self.assertIn("Exec=nulavio %u\n", desktop)
        self.assertIn("x-scheme-handler/https", desktop)

    def test_deb_lets_the_engine_sandbox_use_user_namespaces_and_nothing_else(self):
        """Ubuntu 24.04+ restricts unprivileged user namespaces to programs with an AppArmor profile."""
        profile = (ROOT / "packaging" / "linux" / "apparmor-nulavio").read_text(encoding="utf-8")
        rules = [line.strip() for line in profile.splitlines() if line.strip() and not line.strip().startswith("#")]
        self.assertIn("profile nulavio /usr/lib/nulavio/nulavio{,-bin} flags=(unconfined) {", rules)
        body = rules[rules.index("profile nulavio /usr/lib/nulavio/nulavio{,-bin} flags=(unconfined) {") + 1 : -1]
        self.assertEqual(body, ["userns,", "include if exists <local/nulavio>"])
        make_deb = (ROOT / "scripts" / "release" / "make_deb.sh").read_text(encoding="utf-8")
        self.assertIn('"$pkg/etc/apparmor.d/nulavio"', make_deb)
        self.assertIn("printf '/etc/apparmor.d/nulavio\\n' > \"$pkg/DEBIAN/conffiles\"", make_deb)
        self.assertIn("apparmor_parser -Q -K /etc/apparmor.d/nulavio", (ROOT / "scripts/release/check_deb.sh").read_text())

    def test_packages_install_under_system_directories_only(self):
        spec = (ROOT / "packaging" / "rpm" / "nulavio.spec").read_text(encoding="utf-8")
        self.assertIn("%global nulavio_dir %{_libdir}/nulavio", spec)
        self.assertNotIn("%post", spec)  # no scripts run as root at install time
        self.assertNotRegex(spec, r"(?m)^\s*(curl|wget)\b")
        deb = (ROOT / "scripts" / "release" / "make_deb.sh").read_text(encoding="utf-8")
        self.assertIn("--root-owner-group", deb)
        # The only maintainer scripts load and unload the AppArmor profile (as dh_apparmor does), nothing else.
        for name in ("POSTINST", "POSTRM"):
            script = deb.split(f"<<'{name}'\n", 1)[1].split(f"\n{name}\n", 1)[0]
            commands = [line.strip() for line in script.splitlines() if line.strip() and not line.strip().startswith("#")]
            self.assertTrue(script.startswith("#!/bin/sh\nset -e\n"), script)
            calls = [c for c in commands if "apparmor_parser" in c and not c.startswith("if ")]
            self.assertEqual(len(calls), 1, script)
            self.assertRegex(calls[0], r"^apparmor_parser -(r -T -W|R) /etc/apparmor\.d/nulavio")
            self.assertNotRegex(script, r"\b(curl|wget|rm|chmod|chown|useradd|systemctl)\b")

    def test_one_build_reads_the_system_directory_the_distribution_has(self):
        series = (ROOT / "browser" / "patches" / "series").read_text(encoding="utf-8")
        self.assertIn("0006-xre-use-the-system-mozilla-directory-the-distribution-has.patch", series)
        for check, directory in (("check_rpm.sh", "/usr/lib64/mozilla"), ("check_deb.sh", "/usr/lib/mozilla")):
            self.assertIn(f'[ "$sysdir" = "{directory}" ]', (ROOT / "scripts" / "release" / check).read_text(encoding="utf-8"))

    def test_repository_signing_never_stores_a_key(self):
        sign = (ROOT / "scripts" / "release" / "sign_repo.sh").read_text(encoding="utf-8")
        # The host's agent signs (its extra socket in the container): a passphrase works and the
        # private key never enters the container; only the exported public key does.
        self.assertIn("--list-dirs agent-extra-socket", sign)
        self.assertIn('ln -s /run/host-gpg-agent "$GNUPGHOME/S.gpg-agent"', sign)
        self.assertNotIn("/gnupg-ro", sign)
        self.assertNotIn("export-secret", sign)
        self.assertIn('rm -rf "$GNUPGHOME"', sign)
        # Both checks are on in the .repo file, which the site serves from git (not the bucket).
        self.assertIn("repo_gpgcheck=1", (ROOT / "site" / "rpm" / "nulavio.repo").read_text(encoding="utf-8"))
        test = (ROOT / "scripts" / "release" / "test_signed_repo.sh").read_text(encoding="utf-8")
        self.assertIn("tampered", test)


class UpstreamWatchTest(unittest.TestCase):
    """Update SLA: the watcher's verdicts from Mozilla's release history."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts" / "release"))
        import watch_upstream

        self.watch = watch_upstream
        self.history = {"157.0": "2026-09-29", "158.0": "2026-10-13", "158.0.1": "2026-10-20", "153.5.1": "2026-10-20"}

    def at(self, text: str):
        import datetime as dt

        return dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)

    def test_up_to_date_ignores_older_and_esr_lines(self):
        result = self.watch.status("158.0.1", self.history, self.at("2026-10-27T00:00:00"))
        self.assertEqual(result["state"], "up-to-date")

    def test_pending_then_overdue_after_72_hours(self):
        history = {**self.history, "158.0.2": "2026-10-28"}
        pending = self.watch.status("158.0.1", history, self.at("2026-10-29T12:00:00"))
        self.assertEqual((pending["state"], pending["first"], pending["hours_left"]), ("pending", "158.0.2", 36.0))
        overdue = self.watch.status("158.0.1", history, self.at("2026-10-31T00:00:01"))
        self.assertEqual(overdue["state"], "overdue")
        self.assertIn("OVERDUE", self.watch.describe(overdue))

    def test_the_earliest_newer_release_sets_the_deadline(self):
        history = {**self.history, "159.0": "2026-11-06", "158.0.2": "2026-10-28"}
        result = self.watch.status("158.0.1", history, self.at("2026-10-28T01:00:00"))
        self.assertEqual(result["first"], "158.0.2")
        self.assertEqual(result["newer"], ["158.0.2", "159.0"])

    def test_pinned_version_is_the_built_one(self):
        engine = json.loads((ROOT / "browser" / "build" / "engine.json").read_text())
        self.assertRegex(engine["firefox"], r"^\d+\.\d+(\.\d+)?$")
        workflow = (ROOT / ".github" / "workflows" / "upstream.yml").read_text()
        self.assertIn("watch_upstream.py", workflow)
        self.assertIn("contents: read", workflow)


if __name__ == "__main__":
    unittest.main()
