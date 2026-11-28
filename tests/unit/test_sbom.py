"""The SBOM generator (scripts/release/sbom.py): identifiers vulnerability scanners can match, and
the Companion app's libraries as Gradle resolved them."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import MappingProxyType
from unittest import mock

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
            boms = {
                "preview": run(),
                "package": run("--package", str(package), "--engine-version", "158.0.1", "--release-version", "158.0.1-1"),
            }
        for mode, bom in boms.items():
            for component in bom["components"]:
                with self.subTest(mode=mode, component=component["bom-ref"]):
                    exact = re.fullmatch(r"[0-9][0-9A-Za-z._-]*", component["version"])
                    self.assertEqual("purl" in component, bool(exact))  # a range (">=1.0.18 ...") names no package

    def test_packaged_engine_has_its_cpe_and_purl(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-1.x86_64.rpm"
            package.write_bytes(b"package")
            packaged = run("--package", str(package), "--engine-version", "158.0.1", "--release-version", "158.0.1-1")
            # The package itself is described with the licences its own field names (issue #137).
            self.assertEqual(packaged["metadata"]["component"]["licenses"], [{"expression": "MPL-2.0 AND GPL-3.0-only"}])
            engine = packaged["components"][0]
        self.assertEqual(engine["cpe"], "cpe:2.3:a:mozilla:firefox:158.0.1:*:*:*:*:*:*:*")
        self.assertEqual(engine["purl"], "pkg:generic/mozilla/firefox@158.0.1")

    def test_the_package_is_named_by_its_release_and_the_engine_by_firefox(self):
        """Two revisions on one Firefox are two releases: the root names the release, the engine Firefox (#637)."""
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-0.1.fc44.x86_64.rpm"
            package.write_bytes(b"package")
            boms = {
                release: run("--package", str(package), "--engine-version", "158.0.1", "--release-version", release)
                for release in ("158.0.1-0.1", "158.0.1-0.2")
            }
        for release, bom in boms.items():
            with self.subTest(release=release):
                self.assertEqual(bom["metadata"]["component"]["name"], "nulavio")
                self.assertEqual(bom["metadata"]["component"]["version"], release)
                engine = bom["components"][0]
                self.assertEqual(engine["bom-ref"], "engine:firefox")
                self.assertEqual(engine["version"], "158.0.1")
                self.assertEqual(engine["purl"], "pkg:generic/mozilla/firefox@158.0.1")
                self.assertEqual(engine["cpe"], "cpe:2.3:a:mozilla:firefox:158.0.1:*:*:*:*:*:*:*")
        self.assertNotEqual(*(bom["metadata"]["component"]["version"] for bom in boms.values()))

    def test_a_package_needs_its_release_on_that_firefox(self):
        """Without the release, or with one on another Firefox, there is no package SBOM: never a silent fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-0.1.fc44.x86_64.rpm"
            package.write_bytes(b"package")
            for extra in (
                [],
                ["--release-version", "158.0.2-0.1"],
                ["--release-version", "158.0.1"],
                ["--release-version", "158.0.1-"],
            ):
                with self.subTest(extra=extra):
                    result = subprocess.run(
                        [sys.executable, "-I", str(SCRIPT), "--package", str(package), "--engine-version", "158.0.1", *extra],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("--release-version", result.stderr)
                    self.assertEqual(result.stdout, "")
        # Only a package has a release of its own here; an empty one (a caller's unset variable) is still one given.
        for mode in ([], ["--companion"]):
            for release in ("158.0.1-0.1", ""):
                with self.subTest(mode=mode, release=release):
                    result = subprocess.run(
                        [sys.executable, "-I", str(SCRIPT), *mode, "--release-version", release], capture_output=True, text=True
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("--release-version needs --package", result.stderr)
                    self.assertEqual(result.stdout, "")


# The keys the CycloneDX 1.6 JSON schema (bom-1.6.schema.json) allows in the objects the engine's
# pedigree uses. Each definition there has "additionalProperties": false, so any other key makes the
# whole SBOM invalid (issue #634). Copied from the schema's "definitions"; no validator or schema is
# vendored here.
CDX16_PATCH_KEYS = {"type", "diff", "resolves"}  # definitions.patch, "required": ["type"]
CDX16_PATCH_TYPES = {"unofficial", "monkey", "backport", "cherry-pick"}  # definitions.patch.properties.type.enum
CDX16_DIFF_KEYS = {"text", "url"}  # definitions.diff
CDX16_PROPERTY_KEYS = {"name", "value"}  # definitions.property, "required": ["name"]


class PackagePedigreeTest(unittest.TestCase):
    """The engine's patches in a package SBOM: only what CycloneDX 1.6 allows, and each patch's
    SHA-256 still recorded, as a property of the engine component."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-1.x86_64.rpm"
            package.write_bytes(b"package")
            cls.engine = run("--package", str(package), "--engine-version", "158.0.1", "--release-version", "158.0.1-1")[
                "components"
            ][0]
        cls.series = [
            line.strip()
            for line in (ROOT / "browser" / "patches" / "series").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def test_patches_use_only_the_keys_the_schema_allows(self):
        patches = self.engine["pedigree"]["patches"]
        self.assertEqual([p["diff"]["url"] for p in patches], [f"browser/patches/{name}" for name in self.series])
        for patch in patches:
            with self.subTest(patch=patch["diff"]["url"]):
                self.assertLessEqual(set(patch), CDX16_PATCH_KEYS)
                self.assertIn(patch["type"], CDX16_PATCH_TYPES)
                self.assertLessEqual(set(patch["diff"]), CDX16_DIFF_KEYS)

    def test_each_patch_sha256_is_a_property_of_the_engine(self):
        for prop in self.engine["properties"]:
            self.assertLessEqual(set(prop), CDX16_PROPERTY_KEYS)
        recorded = {
            prop["name"].removeprefix("nulavio:patch-sha256:"): prop["value"]
            for prop in self.engine["properties"]
            if prop["name"].startswith("nulavio:patch-sha256:")
        }
        self.assertEqual(list(recorded), self.series)
        for name in self.series:
            digest = hashlib.sha256((ROOT / "browser" / "patches" / name).read_bytes()).hexdigest()
            self.assertEqual(recorded[name], digest, name)


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


def preview_from(lock: dict, *args: str) -> dict:
    """The preview SBOM sbom.py writes for this extension lock (beside the repository's content-filter.json)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "extensions.lock.json"
        path.write_text(json.dumps(lock))
        (path.parent / "content-filter.json").write_bytes((sbom.LOCK.parent / "content-filter.json").read_bytes())
        out = io.StringIO()
        argv = ["sbom.py", *args]
        with mock.patch.object(sbom, "LOCK", path), mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            sbom.main()
    return json.loads(out.getvalue())


def revisions(bom: dict) -> list[str]:
    return [p["value"] for p in bom["metadata"]["component"].get("properties", []) if p["name"] == "nulavio:git-revision"]


class SerialTest(unittest.TestCase):
    """The committed preview names no branch commit, and its serial is its content's (#920). The SBOMs CI and
    a release make name the revision they were made from, with the serial derived from it, as before."""

    def test_two_inventories_never_share_a_serial(self):
        lock = json.loads(sbom.LOCK.read_text())
        bumped = json.loads(json.dumps(lock))
        bumped["extensions"][0]["version"] += ".1"
        rehashed = json.loads(json.dumps(lock))
        rehashed["extensions"][-1]["sha256"] = "0" * 64
        serials = [preview_from(each, "--committed")["serialNumber"] for each in (lock, bumped, rehashed)]
        self.assertEqual(len(set(serials)), 3, serials)  # at one HEAD, so a serial from the revision would be one
        for serial in serials:
            self.assertEqual(serial, f"urn:uuid:{uuid.UUID(serial.removeprefix('urn:uuid:'))}")
        # The same inventory, made again, is the same document under the same serial.
        self.assertEqual(preview_from(lock, "--committed"), preview_from(lock, "--committed"))

    def test_the_committed_copy_names_no_revision(self):
        bom = run("--committed")
        self.assertEqual(revisions(bom), [])
        self.assertNotIn(sbom.git_revision() or "uncommitted", json.dumps(bom))
        self.assertEqual(bom["serialNumber"], sbom.content_serial(bom))

    def test_the_committed_sbom_is_the_generated_one(self):
        committed = json.loads((ROOT / "sbom" / "nulavio-preview.cdx.json").read_text())
        self.assertEqual(
            committed,
            run("--committed"),
            "regenerate it: python3 -I scripts/release/sbom.py --committed > sbom/nulavio-preview.cdx.json",
        )

    def test_ci_and_release_sboms_still_name_their_revision(self):
        """Unchanged by #920: what CI attaches and a release publishes say where they come from."""
        revision = sbom.git_revision()
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-0.1.fc44.x86_64.rpm"
            package.write_bytes(b"package")
            boms = {
                "preview": (run(), "nulavio:" + (revision or sbom.__version__)),
                "package": (
                    run("--package", str(package), "--engine-version", "158.0.1", "--release-version", "158.0.1-0.1"),
                    "nulavio:" + (revision or sbom.__version__),
                ),
                "companion": (run("--companion"), revision and "nulavio-companion:" + revision),  # else from the app's version
            }
        for mode, (bom, seed) in boms.items():
            with self.subTest(mode=mode):
                self.assertEqual(revisions(bom), [revision or "uncommitted"])
                if seed:
                    self.assertEqual(bom["serialNumber"], f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}")

    def test_committed_is_only_for_the_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "nulavio-158.0.1-0.1.fc44.x86_64.rpm"
            package.write_bytes(b"package")
            for mode in (
                ["--package", str(package), "--engine-version", "158.0.1", "--release-version", "158.0.1-0.1"],
                ["--companion"],
            ):
                with self.subTest(mode=mode[0]):
                    result = subprocess.run(
                        [sys.executable, "-I", str(SCRIPT), *mode, "--committed"], capture_output=True, text=True
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("--committed is only for the preview", result.stderr)
                    self.assertEqual(result.stdout, "")


class ExtensionLockTest(unittest.TestCase):
    """The committed copies of what the lock pins (the SBOM and LICENSES.md) follow the lock (#497)."""

    LICENSES_ROW = MappingProxyType(
        {
            "ublock-origin": "uBlock Origin",
            "proton-pass": "Proton Pass extension",
            "keepassxc-browser": "KeePassXC-Browser",
            "bitwarden": "Bitwarden extension",
            "1password": "1Password extension",
        }
    )

    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads(sbom.LOCK.read_text())["extensions"]

    def test_the_committed_sbom_names_the_locked_extensions(self):
        committed = json.loads((ROOT / "sbom" / "nulavio-preview.cdx.json").read_text())
        found = {c["bom-ref"]: c["version"] for c in committed["components"] if c["bom-ref"].startswith("xpi:")}
        expected = {f"xpi:{e['id']}": e["version"] for e in self.lock}
        self.assertEqual(
            found, expected, "regenerate it: python3 -I scripts/release/sbom.py --committed > sbom/nulavio-preview.cdx.json"
        )

    def test_licenses_md_names_the_locked_extensions(self):
        rows = {}
        for line in (ROOT / "LICENSES.md").read_text().splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) >= 2:
                rows[cells[0]] = cells[1]
        for entry in self.lock:
            with self.subTest(extension=entry["key"]):
                self.assertIn(entry["key"], self.LICENSES_ROW, "name its LICENSES.md row in this test")
                label = self.LICENSES_ROW[entry["key"]]
                self.assertIn(label, rows, f"LICENSES.md has no row for {label}")
                self.assertEqual(rows[label], entry["version"])


if __name__ == "__main__":
    unittest.main()
