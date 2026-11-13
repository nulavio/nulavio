"""Track B (source build) inputs: mozconfig, patch stack, branding."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

import apply_patches  # noqa: E402
import fetch_firefox_l10n  # noqa: E402
import make_distribution  # noqa: E402
import refresh_extensions_lock  # noqa: E402

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

    UBLOCK = "uBlock0@raymondhill.net"
    # What Helium switches on, of uBlock Origin's own lists: cookie, newsletter and notification notices, uBlock's
    # annoyances, AdGuard's ads list and tracking parameters in addresses.
    DEFAULT_ON = frozenset(
        {
            "adguard-generic",
            "adguard-spyware-url",
            "adguard-cookies",
            "fanboy-cookiemonster",
            "ublock-cookies-easylist",
            "easylist-newsletters",
            "easylist-notifications",
            "ublock-annoyances",
        }
    )

    def bootstrap_address(self) -> str:
        managed = make_distribution.policies()["policies"]["3rdparty"]["Extensions"]
        self.assertEqual(list(managed), [self.UBLOCK])
        # `toOverwrite`, `userSettings` and the rest are applied by uBlock Origin at every start: they would
        # undo what the person chose in its dashboard. Only the registry of a new profile is Nulavio's.
        self.assertEqual(list(managed[self.UBLOCK]), ["adminSettings"])
        admin = json.loads(managed[self.UBLOCK]["adminSettings"])
        self.assertEqual(list(admin), ["assetsBootstrapLocation"])
        return admin["assetsBootstrapLocation"]

    def test_a_new_profile_starts_with_cookie_notice_lists_on_and_nothing_else_changed(self):
        address = self.bootstrap_address()
        prefix = "data://application/json,"
        # What uBlock Origin 1.75 needs to load it without the network: `scheme://`, and a closing `#` that
        # swallows the cache token it appends. ASCII, because the engine reads the unknown type as US-ASCII.
        self.assertTrue(address.startswith(prefix) and address.endswith("#"), address[:40])
        self.assertTrue(address.isascii())
        self.assertEqual(address.count("#"), 1)
        self.assertNotRegex(address, r"[?\s\"\\]")
        registry = json.loads(urllib.parse.unquote(address[len(prefix) : -1]))
        stock = json.loads((make_distribution.REGISTRY_DIR / "assets.json").read_text(encoding="utf-8"))
        self.assertEqual(list(registry), list(stock))
        self.assertEqual({key for key in stock if registry[key] != stock[key]}, self.DEFAULT_ON)
        for key in self.DEFAULT_ON:
            self.assertIs(stock[key]["off"], True)
            # `false`, not absent: a list without `off` is part of the stock default set, and uBlock Origin
            # drops it from the selection when a registry update no longer has it there.
            self.assertEqual(registry[key], {**stock[key], "off": False})

    def test_the_registry_is_the_pinned_packages(self):
        config = json.loads(make_distribution.CONTENT_FILTER.read_text(encoding="utf-8"))
        ublock = make_distribution.extensions.load_lock()[config["extension"]]
        raw = (make_distribution.REGISTRY_DIR / "assets.json").read_bytes()
        self.assertEqual(config["registry"], {"version": ublock.version, "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(set(config["default_on"]), self.DEFAULT_ON)
        licence = (make_distribution.REGISTRY_DIR / "LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", licence[:200])
        self.assertIn("Version 3", licence[:200])
        package = make_distribution.extensions.cached_path(ublock)
        if not package.is_file() or make_distribution.extensions.sha256_file(package) != ublock.sha256:
            self.skipTest("the pinned uBlock Origin package is not in the local cache: the copy is compared by hash only")
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(archive.read("assets/assets.json"), raw)
            self.assertEqual(archive.read("LICENSE.txt").decode("utf-8"), licence)
            # The pinned package still has what the default lists rest on (dependency-updates.md).
            self.assertEqual(refresh_extensions_lock.bootstrap_report(archive), [])

    def test_a_package_that_changed_what_the_default_rests_on_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.xpi"
            with zipfile.ZipFile(path, "w") as archive:
                for name, markers in refresh_extensions_lock.BOOTSTRAP_MARKERS.items():
                    if name != "js/assets.js":  # one file gone, one marker gone
                        archive.writestr(name, "\n".join(markers[1:] if name == "js/storage.js" else markers))
            with zipfile.ZipFile(path) as archive:
                report = refresh_extensions_lock.bootstrap_report(archive)
        self.assertEqual(
            report,
            ["js/storage.js: µb.assetsBootstrapLocation = data.assetsBootstrapLocation;", "js/assets.js: the file is gone"],
        )

    def test_a_copy_that_is_not_the_packages_is_refused_whatever_its_checksum_says(self):
        """The gate of CI and of the release rehearsal (`--check-registry`), on a stand-in for the pinned package."""
        raw = (make_distribution.REGISTRY_DIR / "assets.json").read_bytes()
        licence = (make_distribution.REGISTRY_DIR / "LICENSE.txt").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            package, copy, changed = Path(tmp) / "pinned.xpi", Path(tmp) / "ublock-origin", Path(tmp) / "content-filter.json"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("assets/assets.json", raw)
                archive.writestr("LICENSE.txt", licence)
                for name, markers in refresh_extensions_lock.BOOTSTRAP_MARKERS.items():
                    archive.writestr(name, "\n".join(markers))
            copy.mkdir()
            (copy / "assets.json").write_bytes(raw)
            (copy / "LICENSE.txt").write_bytes(licence)

            def gate(**fetch) -> int:
                said = io.StringIO()
                with (
                    mock.patch.object(refresh_extensions_lock.extensions, "fetch", **fetch),
                    mock.patch.object(refresh_extensions_lock, "REGISTRY_DIR", copy),
                    contextlib.redirect_stdout(said),
                    contextlib.redirect_stderr(said),
                ):
                    return refresh_extensions_lock.check_registry()

            self.assertEqual(gate(return_value=package), 0)
            # One of uBlock Origin's own default lists taken out of the copy, and the checksum in content-filter.json
            # brought along: the copy and the checksum agree, so the build's own check has nothing to say.
            edited = json.loads(raw)
            del edited["easyprivacy"]
            edited_raw = json.dumps(edited, indent="\t").encode("utf-8")
            (copy / "assets.json").write_bytes(edited_raw)
            config = json.loads(make_distribution.CONTENT_FILTER.read_text(encoding="utf-8"))
            config["registry"]["sha256"] = hashlib.sha256(edited_raw).hexdigest()
            changed.write_text(json.dumps(config), encoding="utf-8")
            with (
                mock.patch.object(make_distribution, "CONTENT_FILTER", changed),
                mock.patch.object(make_distribution, "REGISTRY_DIR", copy),
            ):
                self.assertNotIn("easyprivacy", make_distribution.filter_registry())
            # The comparison with the package says which list, and the gate refuses.
            with zipfile.ZipFile(package) as archive:
                report = refresh_extensions_lock.registry_report(archive, copy)
            self.assertEqual(
                report, ["assets.json: not the package's assets/assets.json", "    easyprivacy: only in the package"]
            )
            self.assertEqual(gate(return_value=package), 1)
            # No package to compare with (no network and nothing cached, or a download that is not the pinned file):
            # not compared is not passed.
            (copy / "assets.json").write_bytes(raw)
            for error in (OSError("no network"), refresh_extensions_lock.extensions.IntegrityError("integrity mismatch")):
                self.assertEqual(gate(side_effect=error), 2)
            # A package that lost what the default rests on is refused as well, with the copy byte for byte its own.
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("assets/assets.json", raw)
                archive.writestr("LICENSE.txt", licence)
            self.assertEqual(gate(return_value=package), 1)

    def test_the_gate_runs_in_ci_and_before_the_release_writes_the_policies(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertEqual(ci.count("run: python3 -I scripts/upstream/refresh_extensions_lock.py --check-registry\n"), 1)
        rehearsal = (ROOT / "scripts" / "release" / "rehearse_release.sh").read_text()
        gate = rehearsal.find('python3 -I "$repo/scripts/upstream/refresh_extensions_lock.py" --check-registry\n')
        self.assertTrue(0 < gate < rehearsal.find('python3 -I "$repo/scripts/build/make_distribution.py"'), "no gate")
        # The release's integration run does not skip the test of the lists for want of the network.
        runner = (ROOT / "scripts" / "release" / "run_integration.sh").read_text()
        self.assertIn("export NULAVIO_REQUIRE_NETWORK=${NULAVIO_REQUIRE_NETWORK:-1}", runner)
        self.assertIn('-e "NULAVIO_REQUIRE_NETWORK=$NULAVIO_REQUIRE_NETWORK"', runner)
        module = (ROOT / "tests" / "integration" / "test_content_filter.py").read_text()
        self.assertIn('os.environ.get("NULAVIO_REQUIRE_NETWORK") == "1"', module)

    def test_a_stale_default_stops_the_build(self):
        config = json.loads(make_distribution.CONTENT_FILTER.read_text(encoding="utf-8"))
        stale = (
            {**config, "registry": {**config["registry"], "version": "0.0.1"}},  # the pin moved, the copy did not
            {**config, "registry": {**config["registry"], "sha256": "0" * 64}},  # the copy was edited
            {**config, "default_on": ["nulavio-no-such-list"]},
            {**config, "default_on": ["easylist"]},  # already on upstream: nothing for Nulavio to switch on
            {**config, "default_on": ["assets.json"]},  # not a list
        )
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / "content-filter.json"
            for case in stale:
                changed.write_text(json.dumps(case), encoding="utf-8")
                with mock.patch.object(make_distribution, "CONTENT_FILTER", changed), self.assertRaises(SystemExit, msg=case):
                    make_distribution.policies()
            # No default list: no managed setting at all, and no registry in the package.
            changed.write_text(json.dumps({**config, "default_on": []}), encoding="utf-8")
            with mock.patch.object(make_distribution, "CONTENT_FILTER", changed):
                self.assertNotIn("3rdparty", make_distribution.policies()["policies"])

    def test_the_shell_carries_the_digests_of_the_policies_a_build_ships(self):
        """The settings page hides "managed by your organization" while only Nulavio's own policies are in effect,
        and learns which those are from digests inside the Shell, not from the file an administrator edits."""
        current = make_distribution.own_policies()
        self.assertEqual(set(current["policies"]), set(make_distribution.policies()["policies"]))
        self.assertEqual(
            make_distribution.OWN_POLICIES.read_text(encoding="utf-8"),
            make_distribution.own_policies_text(),
            "browser/shell/shared/own-policies.json is not current: run scripts/build/make_distribution.py --own-policies",
        )
        for digest in current["policies"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        # A policy that changes changes its digest, and one that sets nothing has none.
        changed = {"policies": {**make_distribution.policies()["policies"], "DisableTelemetry": False, "Empty": {}}}
        with mock.patch.object(make_distribution, "policies", return_value=changed):
            other = make_distribution.own_policies()["policies"]
        self.assertNotEqual(other["DisableTelemetry"], current["policies"]["DisableTelemetry"])
        self.assertNotIn("Empty", other)
        self.assertEqual({k: v for k, v in other.items() if k != "DisableTelemetry"},
                         {k: v for k, v in current["policies"].items() if k != "DisableTelemetry"})  # fmt: skip
        guard = (ROOT / "browser" / "shell" / "modules" / "NulavioGuard.sys.mjs").read_text(encoding="utf-8")
        self.assertIn('"resource://builtin-addons/nulavio-shell/shared/own-policies.json"', guard)
        self.assertNotIn('"XREAppDist"', guard, "the Guard reads the application's own policies file again")

    def test_the_licence_goes_out_with_the_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = ROOT / "scripts" / "build" / "make_distribution.py"
            subprocess.run([sys.executable, "-I", str(script), "--out", tmp], check=True, capture_output=True)
            names = sorted(path.name for path in Path(tmp).iterdir())
            self.assertEqual(
                names, ["distribution.ini", "policies.json", "uBlock-Origin-LICENSE.txt", "uBlock-Origin-NOTICE.txt"]
            )
            licence = (make_distribution.REGISTRY_DIR / "LICENSE.txt").read_bytes()
            self.assertEqual((Path(tmp) / "uBlock-Origin-LICENSE.txt").read_bytes(), licence)
            # The copy in policies.json is a modified one: the notice says so, by whom, when, and what was changed.
            config = json.loads(make_distribution.CONTENT_FILTER.read_text(encoding="utf-8"))
            notice = (Path(tmp) / "uBlock-Origin-NOTICE.txt").read_text(encoding="utf-8")
            self.assertRegex(config["changed_on"], r"^20\d\d-\d\d-\d\d$")
            for said in ("modified copy", f"uBlock Origin {config['registry']['version']}", "GNU General Public License",
                         f"on {config['changed_on']}", "uBlock-Origin-LICENSE.txt", *config["default_on"]):  # fmt: skip
                self.assertIn(said, notice)
            self.assertEqual(json.loads((Path(tmp) / "policies.json").read_text()), make_distribution.policies())


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

    def test_every_package_names_both_licences(self):
        """A build carries one GPL-3.0 data file, uBlock Origin's list registry inside distribution/policies.json
        (issue #137): each package's own licence field says so, and the .deb's copyright file says where the text is."""
        config = json.loads(make_distribution.CONTENT_FILTER.read_text(encoding="utf-8"))
        self.assertTrue(config["default_on"], "no registry is shipped any more: the licence fields can go back to MPL-2.0")
        spec = (ROOT / "packaging" / "rpm" / "nulavio.spec").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?m)^License:\s+(.+)$", spec), ["MPL-2.0 AND GPL-3.0-only"])
        self.assertIn("%license nulavio/LICENSE*", spec)  # LICENSE and LICENSES.md, which make_rpm.sh puts in the tree
        metainfo = (ROOT / "packaging" / "flatpak" / "net.nulavio.Nulavio.metainfo.xml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"<project_license>([^<]+)</project_license>", metainfo), ["MPL-2.0 AND GPL-3.0-only"])
        deb = (ROOT / "scripts" / "release" / "make_deb.sh").read_text(encoding="utf-8")
        note = deb.split("<<'NOTE'\n", 1)[1].split("\nNOTE\n", 1)[0]
        for said in ("Mozilla Public License, version 2.0", "GNU General Public License, version 3 only", "all rights reserved",
                     f"/usr/lib/nulavio/distribution/{make_distribution.LICENCE_NAME}", make_distribution.NOTICE_NAME,
                     "/usr/share/doc/nulavio/LICENSES.md"):  # fmt: skip
            self.assertIn(said, note)
        self.assertIn('cat "$repo/LICENSE"\n} > "$pkg/usr/share/doc/nulavio/copyright"', deb)
        self.assertIn('cp "$repo/LICENSES.md" "$pkg/usr/share/doc/nulavio/LICENSES.md"', deb)
        for packager in ("make_rpm.sh", "make_archive.sh"):
            self.assertIn('"$repo/LICENSES.md"', (ROOT / "scripts" / "release" / packager).read_text(encoding="utf-8"))

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

    def test_kms_signing_passes_credentials_by_name_only(self):
        sign = (ROOT / "scripts" / "release" / "sign_repo.sh").read_text(encoding="utf-8")
        # AWS credentials reach the signing container as inherited variables (podman -e NAME), never as
        # NAME=value on a command line, where other users could read them in /proc.
        self.assertIn("-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e AWS_REGION", sign)
        self.assertNotRegex(sign, r"-e AWS_[A-Z_]+=")
        self.assertIn("aws configure export-credentials --format env", sign)
        # KMS does only the RSA operation: the packages and the metadata are signed by openpgp_sign.py,
        # against the published key, and the public key copied to the repository is that one.
        self.assertIn('--define "_openpgp_sign kms"', sign)
        self.assertIn("/nulavio-release/openpgp_sign.py --public-key /public/key.asc", sign)
        self.assertIn("cp /public/key.asc /repo/nulavio-packages.asc", sign)
        publish = (ROOT / "scripts" / "release" / "publish_release.sh").read_text(encoding="utf-8")
        self.assertIn('openpgp_sign.py" --public-key "$published" --kms-key-id "$kms"', publish)
        # Whatever signed it, SHA256SUMS is checked with only the published key before anything is staged.
        self.assertIn('--verify "$stage/github/SHA256SUMS.asc"', publish)
        test = (ROOT / "scripts" / "release" / "test_kms_signing.sh").read_text(encoding="utf-8")
        self.assertIn("tampered", test)
        self.assertIn("test_kms_signing.sh", (ROOT / "scripts" / "release" / "rehearse_release.sh").read_text(encoding="utf-8"))


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
