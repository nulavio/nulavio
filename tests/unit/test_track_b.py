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
        ):
            self.assertIn(required, self.lines)

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
        self.assertIn('browser.contentblocking.category="strict"', ini)
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
