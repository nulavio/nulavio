"""Preference files and Nulavio Guard rules."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import guard, paths, prefs, profile  # noqa: E402

# Prefs that weaken protections the project promises never to weaken
# (sandbox, isolation, signatures, TLS/certs, Safe Browsing, updates).
FORBIDDEN = {
    "security.sandbox.content.level": lambda v: v < 4,
    "security.sandbox.rdd.level": lambda v: True,
    "security.sandbox.socket.process.level": lambda v: True,
    "fission.autostart": lambda v: v is False,
    "xpinstall.signatures.required": lambda v: v is False,
    "extensions.webextensions.remote": lambda v: v is False,
    "security.tls.version.min": lambda v: v < 3,
    "security.cert_pinning.enforcement_level": lambda v: v < 1,
    "security.OCSP.enabled": lambda v: v == 0,
    "browser.safebrowsing.phishing.enabled": lambda v: v is False,
    "browser.safebrowsing.malware.enabled": lambda v: v is False,
    "browser.safebrowsing.downloads.enabled": lambda v: v is False,
    "app.update.enabled": lambda v: True,
    "extensions.update.enabled": lambda v: v is False,
    "extensions.blocklist.enabled": lambda v: v is False,
    "services.settings.server": lambda v: True,
    "network.dns.disableIPv6": lambda v: True,
}


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.baseline = profile.baseline_prefs()

    def test_every_pref_is_documented(self):
        for pref in self.baseline + profile.theme_prefs():
            with self.subTest(pref=pref.name):
                self.assertIn(pref.mode, prefs.VALID_MODES)
                self.assertTrue(pref.category, "missing @category")
                self.assertGreater(len(pref.why), 20, "missing or too short @why")

    def test_no_protection_is_weakened(self):
        for pref in self.baseline + profile.theme_prefs():
            check = FORBIDDEN.get(pref.name)
            if check:
                self.assertFalse(check(pref.value), f"{pref.name}={pref.value!r} weakens a protection")
            self.assertFalse(pref.name.startswith(("security.sandbox.", "marionette.", "remote.", "devtools.debugger.remote")))

    def test_no_remote_endpoints_are_introduced(self):
        for pref in self.baseline:
            if isinstance(pref.value, str):
                self.assertFalse(pref.value.startswith(("http://", "https://")), f"{pref.name} points to a server")

    def test_privacy_defaults_present(self):
        names = {p.name: p.value for p in self.baseline}
        self.assertIs(names["datareporting.healthreport.uploadEnabled"], False)
        self.assertIs(names["dom.security.https_only_mode"], True)
        self.assertEqual(names["browser.contentblocking.category"], "strict")
        self.assertEqual(names["browser.startup.homepage"], "@STARTPAGE_URL@")

    def test_parser_rejects_garbage_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.js"
            bad.write_text('user_pref("a.b", true);\nuser_pref("a.b", false);\n')
            with self.assertRaises(prefs.PrefFileError):
                prefs.parse_annotated(bad)
            bad.write_text("pref_without_call\n")
            with self.assertRaises(prefs.PrefFileError):
                prefs.parse_annotated(bad)
            bad.write_text('// @mode sometimes\nuser_pref("a.b", true);\n')
            with self.assertRaises(prefs.PrefFileError):
                prefs.parse_annotated(bad)

    def test_format_roundtrip_and_escaping(self):
        line = prefs.format_pref("x.y", 'say "hi" \\ there')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.js"
            path.write_text(line + '\nuser_pref("n", 3);\nuser_pref("n", 4);\n')
            values = prefs.read_user_prefs(path)
        self.assertEqual(values["x.y"], 'say "hi" \\ there')
        self.assertEqual(values["n"], 4, "last value must win, as in the engine")
        with self.assertRaises(prefs.PrefFileError):
            prefs.format_pref('bad"); evil("', True)


MOZILLA_AI_OFF = {  # decision D-UX7: the Nulavio assistant (ADR 0007) is the one AI path
    "browser.ml.chat.enabled": False,
    "browser.ml.chat.page": False,
    "browser.ml.chat.menu": False,
    "browser.ml.chat.shortcuts": False,
    "browser.ai.control.sidebarChatbot": "blocked",
    "browser.ai.control.smartTabGroups": "blocked",
    "browser.ai.control.linkPreviewKeyPoints": "blocked",
    "browser.ai.control.smartWindow": "blocked",
    "browser.tabs.groups.smart.enabled": False,
    "browser.ml.linkPreview.enabled": False,
    "extensions.ml.enabled": False,
    "nimbus.rollouts.enabled": False,
}
NO_REGION_LOOKUP = {  # no request to Mozilla's location service on a new profile (review 2026-11-09, RT-1)
    "browser.region.network.url": "",
    "browser.region.update.enabled": False,
}
NO_DRM_UPDATE_PROBE = {  # no request to Google about a DRM module that is off (issue #103)
    "media.gmp-widevinecdm.allow-chromium-update": False,
}
# The two daily checks at Mozilla's update server say nothing about the system or the distribution (issue #126).
UPDATE_CHECKS = {
    "media.gmp-manager.url": "GMP",
    "extensions.systemAddon.update.url": "SystemAddons",
}
FINGERPRINTING = "privacy.fingerprintingProtection.overrides"  # docs/research/fingerprinting.md
# Changing these breaks sites or accessibility; they belong to an opt-in mode, never to the default.
NEVER_BY_DEFAULT = {
    "AllTargets",
    "JSDateTimeUTC",
    "JSLocale",
    "CSSPrefersColorScheme",
    "CSSPrefersReducedMotion",
    "KeyboardEvents",
    "RoundWindowSize",
}
TRACK_B_ONLY = {  # Mozilla account, promos and artwork in the Nulavio build (D-UX8, WCS-10)
    "identity.fxaccounts.enabled": False,
    "browser.aboutaddons.novaThemesPickerEnabled": False,
    "browser.topsites.useRemoteSetting": False,
    "browser.newtabpage.activity-stream.default.sites": "",
    "nulavio.vault.phone.pairing": True,  # D10 revised 2026-11-10: connecting a phone is offered
}


def branding_prefs() -> dict:
    """pref("name", value[, sticky]); lines of the Track B branding defaults."""
    text = (ROOT / "browser" / "branding" / "nulavio" / "pref" / "firefox-branding.js").read_text(encoding="utf-8")
    out = {}
    for name, raw in re.findall(r'^pref\("([^"]+)",\s*(.+?)(?:,\s*sticky)?\);', text, re.M):
        out[name] = {"true": True, "false": False}.get(raw, raw.strip('"') if raw.startswith('"') else raw)
    return out


class MozillaAiAndAccountTest(unittest.TestCase):
    def test_mozilla_ai_is_off_in_both_tracks_with_the_same_values(self):
        baseline = {p.name: p for p in profile.baseline_prefs()}
        branding = branding_prefs()
        for name, value in MOZILLA_AI_OFF.items():
            with self.subTest(pref=name):
                self.assertIn(name, baseline, "Track A needs it too (baseline.js)")
                self.assertEqual(baseline[name].value, value)
                self.assertEqual(baseline[name].mode, "seed", "a default the person can change, not enforced")
                self.assertEqual(branding.get(name), value, "Track B default (firefox-branding.js)")

    def test_no_region_lookup_in_either_track(self):
        baseline = {p.name: p for p in profile.baseline_prefs()}
        branding = branding_prefs()
        for name, value in NO_REGION_LOOKUP.items():
            with self.subTest(pref=name):
                self.assertEqual(baseline[name].value, value, "Track A (baseline.js)")
                self.assertEqual(baseline[name].mode, "seed")
                self.assertEqual(branding.get(name), value, "Track B default (firefox-branding.js)")

    def test_no_drm_update_probe_in_either_track(self):
        baseline = {p.name: p for p in profile.baseline_prefs()}
        branding = branding_prefs()
        for name, value in NO_DRM_UPDATE_PROBE.items():
            with self.subTest(pref=name):
                self.assertEqual(baseline[name].value, value, "Track A (baseline.js)")
                self.assertEqual(baseline[name].mode, "seed")
                self.assertEqual(branding.get(name), value, "Track B default (firefox-branding.js)")
        for names in (set(baseline), set(branding)):
            self.assertFalse(
                {"media.eme.enabled", "media.gmp-widevinecdm.enabled", "media.gmp-provider.enabled"} & names,
                "DRM itself stays the engine's and the person's switch",
            )

    def test_the_update_checks_name_neither_the_system_nor_the_distribution(self):
        baseline = {p.name for p in profile.baseline_prefs()}
        branding = branding_prefs()
        for name, product in UPDATE_CHECKS.items():
            with self.subTest(pref=name):
                self.assertEqual(
                    branding.get(name),
                    f"https://aus5.mozilla.org/update/3/{product}/%VERSION%/%BUILD_ID%/%BUILD_TARGET%/%LOCALE%/%CHANNEL%"
                    "/Linux/default/default/update.xml",
                )
                # Track A runs the distribution's engine: a seed would freeze an address that engine may change.
                self.assertNotIn(name, baseline)

    def test_fingerprinting_additions_are_the_same_in_both_tracks_and_watched(self):
        baseline = {p.name: p for p in profile.baseline_prefs()}
        value = branding_prefs()[FINGERPRINTING]
        self.assertEqual(baseline[FINGERPRINTING].value, value, "Track A seeds what the Nulavio build has by default")
        self.assertEqual(baseline[FINGERPRINTING].mode, "seed")
        items = value.split(",")
        self.assertTrue(all(re.fullmatch(r"[+-][A-Za-z0-9]+", item) for item in items), items)
        self.assertEqual(len(items), len(set(items)))
        # The quick canvas mode leaves raw pixel reads alone: it must be off for the full one to apply.
        self.assertIn("-EfficientCanvasRandomization", items)
        self.assertEqual({item[1:] for item in items} & NEVER_BY_DEFAULT, set())
        guard = (ROOT / "browser" / "shell" / "modules" / "NulavioGuard.sys.mjs").read_text(encoding="utf-8")
        watched = guard[guard.index("WATCHED_PREFS = Object.freeze([") : guard.index("]);", guard.index("WATCHED_PREFS"))]
        for entry in ('"privacy.fingerprintingProtection",', '"privacy.fingerprintingProtection.",'):
            self.assertIn(entry, watched, "a change made outside the browser must be reported at the next start")

    def test_account_promos_and_mozilla_tiles_are_off_in_the_nulavio_build(self):
        branding = branding_prefs()
        for name, value in TRACK_B_ONLY.items():
            with self.subTest(pref=name):
                self.assertEqual(branding.get(name), value)

    def test_branding_prefs_weaken_nothing(self):
        for name, value in branding_prefs().items():
            check = FORBIDDEN.get(name)
            if check:
                self.assertFalse(check(value), f"{name}={value!r} weakens a protection")
            self.assertFalse(name.startswith(("security.sandbox.", "marionette.", "remote.")), name)


class GuardTest(unittest.TestCase):
    def audit(self, prefs_js: str = "", user_js: str = ""):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "prefs.js").write_text(prefs_js)
            Path(tmp, "user.js").write_text(user_js)
            return guard.audit(Path(tmp))

    def test_rules_file_is_valid(self):
        rules = guard.load_rules()
        self.assertGreaterEqual(len(rules), 10)

    def test_clean_profile_has_no_findings(self):
        self.assertEqual(self.audit(), [])

    def test_detects_weakened_sandbox_and_automation(self):
        findings = self.audit(
            prefs_js='user_pref("security.sandbox.content.level", 0);\n',
            user_js='user_pref("marionette.port", 2828);\n',
        )
        severities = {f.pref: f.severity for f in findings}
        self.assertEqual(severities["security.sandbox.content.level"], "critical")
        self.assertEqual(severities["marionette.port"], "critical")

    def test_user_js_overrides_prefs_js(self):
        findings = self.audit(
            prefs_js='user_pref("xpinstall.signatures.required", false);\n',
            user_js='user_pref("xpinstall.signatures.required", true);\n',
        )
        self.assertEqual(findings, [])

    def test_user_choices_are_info_only(self):
        findings = self.audit(prefs_js='user_pref("dom.security.https_only_mode", false);\n')
        self.assertEqual([(f.pref, f.severity) for f in findings], [("dom.security.https_only_mode", "info")])


class ConfigFilesTest(unittest.TestCase):
    def test_providers_reference_locked_extensions(self):
        from nulavio_launcher import extensions

        lock = extensions.load_lock()
        data = profile.load_providers()
        self.assertIn(data["default"], data["providers"])
        for key, provider in data["providers"].items():
            with self.subTest(provider=key):
                if provider["extension"]:
                    self.assertIn(provider["extension"], lock)
                self.assertIn("signon.rememberSignons", provider["prefs"])
        self.assertTrue(data["providers"]["builtin"]["prefs"]["signon.rememberSignons"])
        for key in ("proton-pass", "keepassxc", "bitwarden"):
            self.assertFalse(data["providers"][key]["prefs"]["signon.rememberSignons"])

    def test_config_dir_layout(self):
        self.assertTrue((paths.config_dir() / "prefs" / "baseline.js").is_file())
        self.assertTrue((paths.config_dir() / "guard-rules.json").is_file())


if __name__ == "__main__":
    unittest.main()
