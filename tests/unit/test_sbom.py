"""The SBOM generator (scripts/release/sbom.py): identifiers vulnerability scanners can match, and
the Companion app's libraries as Gradle resolved them."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "sbom.py"
FIXTURES = ROOT / "tests" / "fixtures" / "sbom"
REPORT = FIXTURES / "app-release-runtime-classpath.txt"
APP_LOCK = FIXTURES / "app-gradle.lockfile"
VERIFICATION = FIXTURES / "verification-metadata.xml"

spec = importlib.util.spec_from_file_location("nulavio_sbom", SCRIPT)
sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbom)


def run(*args: str) -> dict:
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class IdentifiersTest(unittest.TestCase):
    def test_cpe_only_for_a_plain_release_number(self):
        self.assertEqual(sbom.cpe(sbom.ENGINE_CPE, "158.0.1"), "cpe:2.3:a:mozilla:firefox:158.0.1:*:*:*:*:*:*:*")
        self.assertEqual(
            sbom.cpe(("bitwarden", "bitwarden", "browser"), "2026.10.0"),
            "cpe:2.3:a:bitwarden:bitwarden:2026.10.0:*:*:*:browser:*:*:*",
        )
        self.assertIsNone(sbom.cpe(sbom.ENGINE_CPE, ">=140 (distribution package, not redistributed in Track A)"))
        self.assertIsNone(sbom.cpe(sbom.ENGINE_CPE, "158.0.1:*:*"))

    def test_purl_encodes_each_part(self):
        self.assertEqual(sbom.purl("maven", "com.google.zxing", "core", "3.5.4"), "pkg:maven/com.google.zxing/core@3.5.4")
        self.assertEqual(
            sbom.purl("generic", "addons.mozilla.org", "{446900e4}@x/y", "1.0"),
            "pkg:generic/addons.mozilla.org/%7B446900e4%7D%40x%2Fy@1.0",
        )

    def test_preview_extensions_have_a_purl_and_known_cpes(self):
        components = {c["bom-ref"]: c for c in run()["components"]}
        extensions = [c for ref, c in components.items() if ref.startswith("xpi:")]
        self.assertTrue(extensions)
        for component in extensions:
            self.assertTrue(component["purl"].startswith("pkg:generic/addons.mozilla.org/"))
        self.assertTrue(components["xpi:uBlock0@raymondhill.net"]["cpe"].startswith("cpe:2.3:a:ublockorigin:ublock_origin:"))
        bitwarden = components["xpi:{446900e4-71c2-419f-a6a7-df9c091e268b}"]
        self.assertRegex(bitwarden["cpe"], r"^cpe:2\.3:a:bitwarden:bitwarden:[\d.]+:\*:\*:\*:browser:")
        self.assertNotIn("cpe", components["xpi:78272b6fa58f4a1abaac99321d503a20@proton.me"])  # not in the NVD
        self.assertNotIn("cpe", components["engine:firefox"])  # the preview uses the distribution's engine, version unknown

    def test_the_list_registry_a_build_carries_is_declared(self):
        carried = {
            c["bom-ref"]: prop["value"]
            for c in run()["components"]
            for prop in c.get("properties", [])
            if prop["name"] == "nulavio:redistributed"
        }
        self.assertEqual(list(carried), ["xpi:uBlock0@raymondhill.net"])
        registry = ROOT / "browser" / "distribution" / "ublock-origin" / "assets.json"
        self.assertIn(hashlib.sha256(registry.read_bytes()).hexdigest(), carried["xpi:uBlock0@raymondhill.net"])

    def test_every_component_with_an_exact_version_has_a_purl(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-1.x86_64.rpm"
            package.write_bytes(b"package")
            boms = {"preview": run(), "package": run("--package", str(package), "--engine-version", "158.0.1")}
        for mode, bom in boms.items():
            for component in bom["components"]:
                with self.subTest(mode=mode, component=component["bom-ref"]):
                    exact = re.fullmatch(r"[0-9][0-9A-Za-z._-]*", component["version"])
                    self.assertEqual("purl" in component, bool(exact))  # a range (">=1.0.18 ...") names no package

    def test_packaged_engine_has_its_cpe_and_purl(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-1.x86_64.rpm"
            package.write_bytes(b"package")
            packaged = run("--package", str(package), "--engine-version", "158.0.1")
            # The package itself is described with the licences its own field names (issue #137).
            self.assertEqual(packaged["metadata"]["component"]["licenses"], [{"expression": "MPL-2.0 AND GPL-3.0-only"}])
            engine = packaged["components"][0]
        self.assertEqual(engine["cpe"], "cpe:2.3:a:mozilla:firefox:158.0.1:*:*:*:*:*:*:*")
        self.assertEqual(engine["purl"], "pkg:generic/mozilla/firefox@158.0.1")


RELEASE_LIBRARIES = sorted([
    "project:nv1",
    "pkg:maven/androidx.annotation/annotation-jvm@1.8.2",
    "pkg:maven/com.google.code.findbugs/jsr305@3.0.2",
    "pkg:maven/com.google.code.gson/gson@2.13.2",
    "pkg:maven/com.google.crypto.tink/tink-android@1.24.0",
    "pkg:maven/com.google.errorprone/error_prone_annotations@2.41.0",
    "pkg:maven/com.google.zxing/core@3.5.4",
    "pkg:maven/com.journeyapps/zxing-android-embedded@4.3.0?type=aar",
    "pkg:maven/org.bouncycastle/bcprov-jdk18on@1.86",
    "pkg:maven/org.jetbrains.kotlin/kotlin-stdlib@2.2.10",
    "pkg:maven/org.jetbrains/annotations@13.0",
])  # fmt: skip


class CompanionTest(unittest.TestCase):
    def test_release_libraries_with_their_pinned_hashes_and_graph(self):
        bom = sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, report=REPORT.read_text(), lock=APP_LOCK.read_text())
        self.assertEqual(bom["metadata"]["component"]["name"], "net.nulavio.companion")
        components = {c["bom-ref"]: c for c in bom["components"]}
        self.assertEqual(sorted(components), RELEASE_LIBRARIES)
        pinned = sbom.maven_artifacts(VERIFICATION)
        for ref, component in components.items():
            if ref.startswith("pkg:maven/"):
                key = f"{component['group']}:{component['name']}:{component['version']}"
                self.assertEqual(component["hashes"], [{"alg": "SHA-256", "content": pinned[key][1]}])
        graph = {d["ref"]: d["dependsOn"] for d in bom["dependencies"]}
        self.assertEqual(set(graph), set(components) | {"app:net.nulavio.companion"})
        self.assertTrue(all(child in components for children in graph.values() for child in children))
        self.assertEqual(
            graph["pkg:maven/androidx.annotation/annotation-jvm@1.8.2"], ["pkg:maven/org.jetbrains.kotlin/kotlin-stdlib@2.2.10"]
        )  # requested 1.7.10, Gradle chose 2.2.10
        self.assertEqual(
            graph["project:nv1"],
            ["pkg:maven/com.google.crypto.tink/tink-android@1.24.0", "pkg:maven/org.bouncycastle/bcprov-jdk18on@1.86"],
        )

    def test_report_lines(self):
        self.assertEqual(sbom.gradle_node("a.b:c:1.0 -> 1.2"), "a.b:c:1.2")
        self.assertEqual(sbom.gradle_node("a.b:c -> 2.0"), "a.b:c:2.0")
        self.assertEqual(sbom.gradle_node("a.b:c:{strictly 1.0} -> 1.0"), "a.b:c:1.0")
        self.assertEqual(sbom.gradle_node("project :nv1"), "project:nv1")
        with self.assertRaises(SystemExit):
            sbom.gradle_node("a.b:c:{strictly 1.0}")
        top, graph = sbom.parse_gradle_dependencies("+--- a:b:1.0\n|    \\--- c:d:2.0 (c)\n\\--- e:f:3.0 (*)\n")
        self.assertEqual((top, graph), (["a:b:1.0", "e:f:3.0"], {"a:b:1.0": [], "e:f:3.0": []}))
        with self.assertRaises(SystemExit):
            sbom.parse_gradle_dependencies("+--- a:b:1.0 FAILED\n")
        with self.assertRaises(SystemExit):
            sbom.parse_gradle_dependencies("No dependencies\n")

    def test_from_the_lock_without_gradle(self):
        bom = sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, lock=APP_LOCK.read_text())
        with_graph = sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, report=REPORT.read_text())
        by_ref = {c["bom-ref"]: c for c in bom["components"]}
        self.assertEqual(by_ref, {c["bom-ref"]: c for c in with_graph["components"]})  # same libraries, hashes, purls
        # No graph in a lock: only the app's entry, never an empty (= "no dependencies") one for a library.
        self.assertEqual(len(bom["dependencies"]), 1)
        self.assertEqual(bom["dependencies"][0]["ref"], "app:net.nulavio.companion")
        self.assertEqual(sorted(bom["dependencies"][0]["dependsOn"]), RELEASE_LIBRARIES)

    def test_lock_lines(self):
        lock = "# comment\na:b:1.0=releaseRuntimeClasspath,releaseCompileClasspath\nc:d:2.0=debugRuntimeClasspath\nempty=\n"
        self.assertEqual(sbom.parse_gradle_lock(lock), ["a:b:1.0"])
        with self.assertRaises(SystemExit):
            sbom.parse_gradle_lock("c:d:2.0=debugRuntimeClasspath\nempty=\n")
        with self.assertRaises(SystemExit):
            sbom.parse_gradle_lock("a:b=releaseRuntimeClasspath\n")

    def test_report_and_lock_must_agree(self):
        drifted = APP_LOCK.read_text().replace("bcprov-jdk18on:1.86", "bcprov-jdk18on:1.85")
        with self.assertRaisesRegex(SystemExit, "bcprov-jdk18on:1.85"):
            sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, report=REPORT.read_text(), lock=drifted)

    def test_a_library_gradle_does_not_verify_is_an_error(self):
        with self.assertRaises(SystemExit):
            sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, report="+--- org.example:unverified:1.0\n")
        with self.assertRaises(SystemExit):
            sbom.companion_bom(VERIFICATION, sbom.APP_GRADLE, lock="org.example:unverified:1.0=releaseRuntimeClasspath\n")

    @unittest.skipUnless(sbom.APP_LOCK.exists(), "android/app/gradle.lockfile not in this checkout")
    def test_the_repositorys_lock_is_verified(self):
        """CI builds the Companion SBOM from the real lock: every locked library has a pinned hash."""
        bom = run("--companion")
        self.assertTrue(all(c["purl"] and c["hashes"] for c in bom["components"] if c["bom-ref"].startswith("pkg:maven/")))


if __name__ == "__main__":
    unittest.main()
