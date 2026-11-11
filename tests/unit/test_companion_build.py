"""The Companion app's build (S11, ADR 0005 D4): free software only, pinned, F-Droid ready."""

from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
APP = ANDROID / "app"
FORBIDDEN = re.compile(r"com\.google\.(android\.gms|firebase|mlkit)|firebase|crashlytics|play-services|gms:", re.I)


class CompanionBuildTest(unittest.TestCase):
    def test_no_google_services_or_trackers(self):
        for path in [APP / "build.gradle.kts", ANDROID / "nv1" / "build.gradle.kts", ANDROID / "settings.gradle.kts",
                     *APP.rglob("*.java"), *APP.rglob("*.xml")]:  # fmt: skip
            if "build" in path.relative_to(ANDROID).parts[1:2]:
                continue
            code = re.sub(r"//[^\n]*|/\*.*?\*/|<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
            self.assertIsNone(FORBIDDEN.search(code), path)  # comments may name what is not used

    def test_permissions_are_the_four_the_link_needs(self):
        ns = "{http://schemas.android.com/apk/res/android}"
        manifest = ET.parse(APP / "src" / "main" / "AndroidManifest.xml").getroot()
        permissions = sorted(p.get(f"{ns}name") for p in manifest.iter("uses-permission"))
        self.assertEqual(permissions, sorted([
            "android.permission.INTERNET", "android.permission.ACCESS_LOCAL_NETWORK",
            "android.permission.CAMERA", "android.permission.USE_BIOMETRIC",
        ]))  # fmt: skip
        application = manifest.find("application")
        self.assertEqual(application.get(f"{ns}allowBackup"), "false")

    def test_no_code_path_needs_androidx(self):
        # The APK ships no AndroidX (the scanner library is added without its transitive set), so the
        # library's classes that call AndroidX crash at run time: found on the real phone (2026-11-10).
        needs_androidx = re.compile(r"\bandroidx\.|IntentIntegrator|CaptureManager|CaptureActivity|ScanContract")
        for path in (APP / "src").rglob("*.java"):
            code = re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
            self.assertIsNone(needs_androidx.search(code), path)
        ns = "{http://schemas.android.com/apk/res/android}"
        manifest = ET.parse(APP / "src" / "main" / "AndroidManifest.xml").getroot()
        removed = [a.get(f"{ns}name") for a in manifest.iter("activity")
                   if a.get("{http://schemas.android.com/tools}node") == "remove"]  # fmt: skip
        self.assertEqual(removed, ["com.journeyapps.barcodescanner.CaptureActivity"])

    def test_every_screen_keeps_clear_of_the_system_bars(self):
        # Edge to edge from Android 15: without insets the unlock request's profile and computer are hidden.
        java = APP / "src" / "main" / "java" / "net" / "nulavio" / "companion"
        for name in ("MainActivity.java", "ScanActivity.java"):
            self.assertIn("Insets.pad(", (java / name).read_text(encoding="utf-8"), name)

    def test_keys_need_authentication_for_every_use(self):
        box = (APP / "src" / "main" / "java" / "net" / "nulavio" / "companion" / "KeyBox.java").read_text(encoding="utf-8")
        self.assertIn(".setUserAuthenticationRequired(true)", box)
        self.assertIn(".setUserAuthenticationParameters(0,", box)  # timeout 0: one authentication per use
        self.assertIn(".setIsStrongBoxBacked(strongBox)", box)
        self.assertIn(".setUnlockedDeviceRequired(true)", box)

    def test_debug_hooks_are_debug_only(self):
        activity = (APP / "src" / "main" / "java" / "net" / "nulavio" / "companion" / "MainActivity.java").read_text()
        self.assertIn("BuildConfig.DEBUG && code != null", activity)
        operation = (APP / "src" / "main" / "java" / "net" / "nulavio" / "companion" / "Operation.java").read_text()
        self.assertIn("if (BuildConfig.DEBUG) {", operation)

    def test_the_device_test_never_changes_a_real_phones_screen_lock(self):
        lines = (ROOT / "tests" / "integration" / "test_companion_emulator.py").read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if '"locksettings"' in line:
                guard = next(prev for prev in reversed(lines[:i]) if prev.strip() and not prev.strip().startswith("#"))
                self.assertTrue(guard.strip().startswith(("if cls.emulator", 'adb("shell", "locksettings"')), line)

    def test_build_inputs_are_pinned(self):
        wrapper = (ANDROID / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text()
        self.assertRegex(wrapper, r"distributionSha256Sum=[0-9a-f]{64}")
        verification = ET.parse(ANDROID / "gradle" / "verification-metadata.xml").getroot()
        tag = verification.tag.split("}")[0] + "}"
        self.assertEqual(verification.find(f"{tag}configuration/{tag}verify-metadata").text, "true")
        names = {c.get("name") for c in verification.iter(f"{tag}component")}
        for artifact in ("tink-android", "bcprov-jdk18on", "zxing-android-embedded", "core"):
            self.assertIn(artifact, names)

    def test_fdroid_recipe_builds_this_app(self):
        recipe = (ANDROID / "fdroid" / "net.nulavio.companion.yml").read_text()
        gradle = (APP / "build.gradle.kts").read_text()
        version_code = re.search(r"versionCode = (\d+)", gradle).group(1)
        version_name = re.search(r'versionName = "([^"]+)"', gradle).group(1)
        self.assertIn(f"versionCode: {version_code}", recipe)
        self.assertIn(f"versionName: {version_name}", recipe)
        self.assertIn("subdir: android/app", recipe)
        self.assertIn("License: MPL-2.0", recipe)
        self.assertNotIn("Summary:", recipe)  # fdroiddata's tools/make-summary-translatable.py refuses it
        for locale in ("en-US", "pt-BR"):
            summary = (ANDROID / "fdroid" / "net.nulavio.companion" / locale / "summary.txt").read_text(encoding="utf-8")
            self.assertLessEqual(len(summary.strip()), 80)  # F-Droid's limit for a summary
        self.assertIn('applicationId = "net.nulavio.companion"', gradle)
        self.assertIn("includeInApk = false", gradle)  # no Google-encrypted dependency block


if __name__ == "__main__":
    unittest.main()
