"""Every pinned dependency stays pinned by version and hash, in a form the update tooling can maintain,
and the daily watcher (scripts/release/watch_dependencies.py) reaches the right verdicts. No network:
the watcher's and the Gradle review's network calls are replaced by fakes."""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
for extra in (ROOT / "scripts" / "release", ROOT / "scripts" / "upstream"):
    sys.path.insert(0, str(extra))

import review_gradle_verification as review  # noqa: E402
import watch_dependencies as watch  # noqa: E402

GRADLE_FILES = [ANDROID / "build.gradle.kts", ANDROID / "settings.gradle.kts", *sorted(ANDROID.glob("*/build.gradle.kts"))]
COORDINATE = re.compile(r'"([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-+]+)"')
PLUGIN = re.compile(r'id\("([A-Za-z0-9_.\-]+)"\)\s+version\s+"([^"]+)"')
SHIPPED = re.compile(r'\b(?:implementation|api|runtimeOnly)\("([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-+]+)"\)')
LOCKED = {"app": "releaseRuntimeClasspath", "nv1": "runtimeClasspath"}  # the classpaths whose code ships in the APK
IMAGE_REF = re.compile(
    r"\b(?:registry\.fedoraproject\.org|docker\.io|quay\.io|ghcr\.io|registry\.access\.redhat\.com)/[\w./:@-]+"
)
PINNED_IMAGE = re.compile(
    r"^[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?(/[a-z0-9._-]+)+:[\w.-]+@sha256:[0-9a-f]{64}$"
)  # registry host first
RELEASE_SCRIPTS = (
    "make_rpm.sh", "make_deb.sh", "check_rpm.sh", "check_deb.sh", "sign_repo.sh", "test_signed_repo.sh", "test_kms_signing.sh",
    "check_published.sh", "sign_apt_repo.sh", "test_apt_repo.sh",
)  # fmt: skip
# Android lint's Security checks that default to a warning (lint 9.4, `lint --show`), promoted to errors in app/lint.xml.
LINT_SECURITY = {
    "AcceptsUserCertificates", "AddJavascriptInterface", "AllowAllHostnameVerifier", "AuthLeak", "BadHostnameVerifier",
    "CustomPermissionTypo", "CustomX509TrustManager", "DataExtractionRules", "DeprecatedProvider", "ExportedContentProvider",
    "ExportedPreferenceActivity", "ExportedReceiver", "ExportedService", "GetInstance", "GrantAllUris", "HardwareIds",
    "InsecureBaseConfiguration", "IntentFilterExportedReceiver", "IntentWithNullActionLaunch", "ProviderReadPermissionOnly",
    "ProxyPassword", "SSLCertificateSocketFactoryCreateSocket", "SSLCertificateSocketFactoryGetInsecure", "SecretInSource",
    "SecureRandom", "SetJavaScriptEnabled", "SetWorldReadable", "SetWorldWritable", "SignatureOrSystemPermissions",
    "SystemPermissionTypo", "TileProviderPermissions", "TrulyRandom", "TrustAllX509TrustManager",
    "UnprotectedSMSBroadcastReceiver", "UnsafeDynamicallyLoadedCode", "UnsafeIntentLaunch", "UnsafeNativeCodeLocation",
    "UnsafeProtectedBroadcastReceiver", "UnsanitizedFilenameFromContentProvider", "UseCheckPermission", "UsingHttp",
    "WebViewClientOnReceivedSslError", "WorldReadableFiles", "WorldWriteableFiles",
}  # fmt: skip
FIX = "regenerate and review android/gradle/verification-metadata.xml and the lockfiles (docs/security/dependency-updates.md)"


def code(path: Path) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


def verified_components() -> dict[tuple[str, str, str], list[str]]:
    root = ET.parse(ANDROID / "gradle" / "verification-metadata.xml").getroot()
    ns = root.tag.split("}")[0] + "}"
    return {
        (c.get("group"), c.get("name"), c.get("version")): [a.get("name") for a in c.iter(f"{ns}artifact")]
        for c in root.iter(f"{ns}component")
    }


def lock_entries(module: str) -> dict[tuple[str, str], tuple[str, set[str]]]:
    """(group, name) -> (version, configurations) from android/<module>/gradle.lockfile."""
    entries = {}
    for line in (ANDROID / module / "gradle.lockfile").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("empty="):
            continue
        module_id, _, configurations = line.partition("=")
        group, name, version = module_id.split(":")
        entries[(group, name)] = (version, set(configurations.split(",")))
    return entries


class GradlePinsTest(unittest.TestCase):
    def test_every_declared_dependency_and_plugin_has_verification_metadata(self):
        # Dependabot bumps versions but cannot write this file (dependabot-core #1996): fail early and say what to do.
        components = verified_components()
        declared = set()
        for path in GRADLE_FILES:
            text = code(path)
            declared |= {m.groups() for m in COORDINATE.finditer(text)}
            declared |= {(pid, f"{pid}.gradle.plugin", version) for pid, version in PLUGIN.findall(text)}
        self.assertIn(("com.google.zxing", "core"), {d[:2] for d in declared})  # the parsing still finds them
        missing = sorted(":".join(d) for d in declared if d not in components)
        self.assertEqual(missing, [], FIX)
        for key in declared:
            self.assertTrue(any(a.endswith((".jar", ".aar", ".pom")) for a in components[key]), key)

    def test_the_apks_classpath_is_locked_and_matches_the_build_files(self):
        components = verified_components()
        for module, configuration in LOCKED.items():
            build = code(ANDROID / module / "build.gradle.kts")
            self.assertIn("lockMode.set(LockMode.STRICT)", build, module)
            self.assertRegex(build, rf'"{configuration}"[^\n]*\n?[^\n]*activateDependencyLocking\(\)', module)
            locked = lock_entries(module)
            self.assertTrue(locked, module)
            for (group, name), (version, configurations) in locked.items():
                self.assertEqual(configurations, {configuration}, f"{module}: {group}:{name}")
                self.assertIn((group, name, version), components, f"{module} locks {group}:{name}:{version}; {FIX}")
            for group, name, version in SHIPPED.findall(build):
                self.assertEqual(locked.get((group, name), ("missing",))[0], version, f"{module}: {group}:{name}; {FIX}")
        self.assertIn(("org.bouncycastle", "bcprov-jdk18on"), lock_entries("app"))  # nv1's dependencies reach the APK

    def test_wrapper_comes_from_gradle_with_a_checksum(self):
        props = dict(
            line.split("=", 1) for line in (ANDROID / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text().splitlines()
            if "=" in line and not line.startswith("#")
        )  # fmt: skip
        self.assertRegex(props["distributionUrl"], r"^https\\://services\.gradle\.org/distributions/gradle-[0-9.]+-bin\.zip$")
        self.assertRegex(props["distributionSha256Sum"], r"^[0-9a-f]{64}$")
        self.assertEqual(props.get("validateDistributionUrl"), "true")

    def test_android_lint_security_checks_are_errors(self):
        issues = {i.get("id"): i.get("severity") for i in ET.parse(ANDROID / "app" / "lint.xml").getroot().iter("issue")}
        self.assertEqual(sorted(LINT_SECURITY - issues.keys()), [])
        self.assertEqual({k: v for k, v in issues.items() if v not in ("error", "fatal")}, {}, "lint.xml only raises severities")
        app = code(ANDROID / "app" / "build.gradle.kts")
        for setting in ('lintConfig = file("lint.xml")', "checkDependencies = true", "abortOnError = true"):
            self.assertIn(setting, app)
        self.assertIn('id("com.android.lint")', code(ANDROID / "nv1" / "build.gradle.kts"))  # nv1 ships too


class OtherPinsTest(unittest.TestCase):
    def test_python_tools_are_pinned_with_hashes(self):
        files = sorted((ROOT / "requirements").glob("*.txt"))
        self.assertIn("fuzz.txt", [f.name for f in files])
        for path in files:
            text = path.read_text()
            requirements = [r for r in re.sub(r"\\\n\s*", " ", text).splitlines() if r.strip() and not r.lstrip().startswith("#")]
            self.assertTrue(requirements, path.name)
            for requirement in requirements:
                self.assertRegex(
                    requirement, r"^[A-Za-z0-9_.\-]+==\S+ .*--hash=sha256:[0-9a-f]{64}", f"{path.name}: {requirement}"
                )

    def test_actions_carry_their_version_next_to_the_sha(self):
        # Dependabot keeps "# vX.Y.Z" current; the watcher needs it to look up advisories.
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            for line in workflow.read_text().splitlines():
                if re.search(r"uses:\s*[^\s.]", line):
                    self.assertRegex(line, r"uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*\s*$", line.strip())

    def test_base_images_are_pinned_by_digest_in_one_place(self):
        refs = []
        for path in sorted((ROOT / "ci" / "containers").glob("*.Containerfile")):
            refs += [(path.name, ref) for ref in re.findall(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.M)]
        self.assertEqual(len(refs), 4)  # fedora-build, fedora-itest, fedora-release-itest, ubuntu-itest
        self.assertEqual([r for r in refs if not PINNED_IMAGE.match(r[1])], [])
        by_tag: dict[str, set[str]] = {}
        for _, ref in refs:
            by_tag.setdefault(ref.split("@")[0], set()).add(ref)
        self.assertEqual({tag: digests for tag, digests in by_tag.items() if len(digests) > 1}, {}, "one digest per tag")
        # Scripts take their image from the Containerfiles (scripts/release/base_image.sh), so Dependabot's update covers them.
        literal = []
        for path in sorted((ROOT / "scripts").rglob("*")):
            if path.suffix in (".sh", ".py", "") and path.is_file():
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not line.lstrip().startswith("#") and IMAGE_REF.search(line):
                        literal.append(f"{path.relative_to(ROOT)}: {line.strip()}")
        self.assertEqual(literal, [])
        for script in RELEASE_SCRIPTS:
            self.assertIn("base_image.sh", (ROOT / "scripts" / "release" / script).read_text(encoding="utf-8"), script)

    def test_base_image_helper_refuses_a_reference_without_a_digest(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash not available")
        out = subprocess.run(
            [bash, str(ROOT / "scripts" / "release" / "base_image.sh"), "fedora-build"], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout.strip(), PINNED_IMAGE)
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "scripts" / "release").mkdir(parents=True)
            (tree / "ci" / "containers").mkdir(parents=True)
            shutil.copy(ROOT / "scripts" / "release" / "base_image.sh", tree / "scripts" / "release")
            digest = "@sha256:" + "a" * 64
            cases = {
                "tag-only": "registry.fedoraproject.org/fedora:44",
                "short": "fedora:44" + digest,
                "no-registry": "library/ubuntu:26.10" + digest,
            }
            for name, ref in cases.items():
                line = f"FROM {ref}"
                (tree / "ci" / "containers" / f"{name}.Containerfile").write_text(line + "\nRUN true\n")
                result = subprocess.run(
                    [bash, str(tree / "scripts" / "release" / "base_image.sh"), name], capture_output=True, text=True
                )
                self.assertNotEqual(result.returncode, 0, name)
                self.assertEqual(result.stdout, "", name)

    def test_dependabot_covers_every_pinned_ecosystem(self):
        config = (ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem, directory in [("github-actions", "/"), ("pip", "/requirements"), ("gradle", "/android"),
                                     ("docker", "/ci/containers"), ("npm", "/ci/site")]:  # fmt: skip
            self.assertRegex(config, rf'package-ecosystem: "{ecosystem}"\n\s+directory: "{re.escape(directory)}"')
        self.assertEqual(config.count("cooldown:"), 4)  # all but docker, whose registries give no release dates
        self.assertNotIn("insecure-external-code-execution", config)
        self.assertNotRegex(config, r"(?m)^\s*registries:")  # no credentials handed to Dependabot

    def test_vulnerability_exceptions_name_one_version_with_a_reason_and_an_expiry(self):
        data = json.loads((ROOT / "docs" / "security" / "vulnerability-exceptions.json").read_text())
        seen = set()
        for item in data["exceptions"]:
            self.assertEqual(set(item), {"id", "ecosystem", "package", "version", "reason", "until"}, item)
            self.assertRegex(item["id"], r"^(GHSA|CVE|PYSEC|OSV|BIT)-[\w-]+$", item)
            self.assertIn(item["ecosystem"], ("Browser extension", "Maven", "PyPI", "GitHub Actions", "Bitnami", "npm"), item)
            self.assertGreater(len(item["reason"]), 40, item)
            until = datetime.date.fromisoformat(item["until"])
            self.assertLessEqual((until - datetime.date.today()).days, 366, f"{item['id']}: at most a year ahead")
            key = (item["id"], item["package"], item["version"])
            self.assertNotIn(key, seen)
            seen.add(key)


class FakeNet:
    """Stands in for watch_dependencies.Net: OSV, AMO and the registries answer from fixtures."""

    def __init__(
        self,
        vulns=None,
        action_vulns=None,
        details=None,
        digests=None,
        amo=None,
        served=None,
        versions=None,
        blocks=None,
        down=(),
    ):
        self.down = down  # URL prefixes that fail as if the service were unreachable
        self.vulns = vulns or {}  # (ecosystem, name, version) -> [ids]
        self.action_vulns = action_vulns or {}  # name -> [OSV records]
        self.details = details or {}
        self.digests = digests or {}  # manifest URL -> digest (default: the pinned one)
        self.amo = amo or {}  # extension id -> current_version override
        self.served = served or {}  # extension id -> the pinned version's reply override (None: a 404)
        self.versions = versions or {}  # extension id -> the versions list override
        self.blocks = blocks or {}
        self.lock = json.loads((ROOT / "browser" / "distribution" / "extensions.lock.json").read_text())
        self.pinned = {watch.manifest_url(ref): ref.partition("@")[2] for _, ref in watch.image_refs(ROOT)}

    def unreachable(self, url):
        if url.startswith(tuple(self.down)):
            raise OSError(f"test: {url} is down")

    def json(self, url, data=None, missing_ok=False):
        self.unreachable(url)
        if url == watch.OSV + "querybatch":
            return {
                "results": [
                    {
                        "vulns": [
                            {"id": i} for i in self.vulns.get((q["package"]["ecosystem"], q["package"]["name"], q["version"]), [])
                        ]
                    }
                    for q in data["queries"]
                ]
            }
        if url == watch.OSV + "query":
            return {"vulns": self.action_vulns.get(data["package"]["name"], [])}
        if url.startswith(watch.OSV + "vulns/"):
            return self.details[urllib.parse.unquote(url.rsplit("/", 1)[1])]
        if url.startswith(watch.AMO + "blocklist/block/"):
            if not missing_ok:
                raise AssertionError("a 404 from the blocklist means: not blocked")
            return self.blocks.get(urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[1]))
        if url.startswith(watch.AMO + "addons/addon/"):
            parts = url[len(watch.AMO) :].partition("?")[0].strip("/").split("/")  # addons addon <guid> [versions [<v>]]
            guid = urllib.parse.unquote(parts[2])
            entry = next(e for e in self.lock["extensions"] if e["id"] == guid)
            pinned = {
                "version": entry["version"],
                "channel": "listed",
                "file": {
                    "hash": "sha256:" + entry["sha256"],
                    "size": entry["size"],
                    "created": "2026-10-01T00:00:00Z",
                    "status": "public",
                },
            }
            if len(parts) == 3:
                return {"current_version": self.amo.get(guid, pinned)}
            if len(parts) == 5:
                if not missing_ok:
                    raise AssertionError("a 404 for the pinned version means: AMO no longer has it")
                return self.served.get(guid, pinned)
            return self.versions.get(guid, {"next": None, "results": [self.amo.get(guid, pinned), pinned]})
        raise AssertionError(f"unexpected URL {url}")

    def github_json(self, url):
        self.unreachable(url)
        return []  # no published advisory (test_extension_advisories.py has the recorded ones)

    def head(self, url, headers):
        self.unreachable(url)
        return 200, {"docker-content-digest": self.digests.get(url, self.pinned[url])}


NOW = datetime.datetime(2026, 10, 27, 12, tzinfo=datetime.UTC)
ADVISORY = {"summary": "test advisory", "aliases": ["CVE-2026-0001"], "database_specific": {"severity": "HIGH"}}


class WatcherTest(unittest.TestCase):
    def test_versions_and_osv_ranges(self):
        self.assertLess(watch.version_key("1.2.0-rc1"), watch.version_key("1.2.0"))
        self.assertEqual(watch.version_key("v2.3"), watch.version_key("2.3.0"))
        self.assertLess(watch.version_key("45.0.7"), watch.version_key("46.0.1"))
        events = [{"introduced": "0"}, {"fixed": "46.0.1"}]
        vuln = {
            "affected": [
                {"package": {"name": "o/a", "ecosystem": "GitHub Actions"}, "ranges": [{"type": "ECOSYSTEM", "events": events}]}
            ]
        }
        self.assertTrue(watch.affected(vuln, {"o/a"}, "45.0.7"))
        self.assertFalse(watch.affected(vuln, {"o/a"}, "46.0.1"))
        self.assertFalse(watch.affected(vuln, {"o/b"}, "1"))
        events = [{"introduced": "2"}, {"last_affected": "2.3"}]
        last = {"affected": [{"package": {"name": "o/a"}, "ranges": [{"events": events}]}]}
        self.assertTrue(watch.affected(last, {"o/a"}, "2.3.0"))
        self.assertFalse(watch.affected(last, {"o/a"}, "1.9"))
        self.assertFalse(watch.affected(last, {"o/a"}, "2.4"))
        self.assertTrue(watch.affected({"affected": [{"package": {"name": "o/a"}, "versions": ["v1.2"]}]}, {"o/a"}, "1.2"))
        git = {"affected": [{"package": {"name": "o/a"}, "ranges": [{"type": "GIT", "events": [{"introduced": "0"}]}]}]}
        self.assertFalse(watch.affected(git, {"o/a"}, "1.0"))
        self.assertEqual(
            watch.action_names("gradle/actions/wrapper-validation"), {"gradle/actions/wrapper-validation", "gradle/actions"}
        )

    def test_inventory_reads_the_repository(self):
        found = watch.inventory()
        # npm left with the AI review's Claude Code (2026-11-14).
        self.assertEqual({d.ecosystem for d in found}, {"GitHub Actions", "PyPI", "Maven", "Bitnami"})
        keys = [(d.ecosystem, d.name, d.version) for d in found]
        self.assertEqual(len(keys), len(set(keys)), "one entry per package version, with all its sources")
        checkout = next(d for d in found if d.name == "actions/checkout")
        self.assertIn(".github/workflows/ci.yml", checkout.sources)
        shipped = {(d.name, d.version) for d in found if d.ships}
        self.assertEqual(shipped, watch.locked_modules(ANDROID / "app" / "gradle.lockfile"))
        self.assertIn(("org.bouncycastle:bcprov-jdk18on", "1.86"), shipped)
        self.assertFalse(any(d.ships for d in found if d.name == "com.android.tools.build:gradle"))
        self.assertIn(("Bitnami", "gradle"), {(d.ecosystem, d.name) for d in found})
        pypi = {d.name: d.sources for d in found if d.ecosystem == "PyPI"}
        self.assertEqual(list(pypi.get("hypothesis", ())), ["requirements/fuzz.txt"])  # every requirements file is watched (#149)
        self.assertIn("ruff", pypi)

    def test_the_ai_review_downloads_nothing(self):
        # Since 2026-11-14 the review calls the Messages API from a standard-library script: no program
        # is downloaded into the job that holds the credential, so there is no pin for the watch to miss.
        workflow = (ROOT / ".github" / "workflows" / "ai-review.yml").read_text()
        for downloaded in ("curl ", "wget ", "_VERSION:", "_SHA256:", "pip install", "npm "):
            self.assertNotIn(downloaded, workflow)

    def test_clean_run_has_nothing_to_act_on(self):
        deps, rows = watch.run(FakeNet(), NOW, exceptions=[])
        self.assertGreater(len(deps), 200)
        self.assertEqual([r.text for r in rows if r.state != "ok"], [])
        self.assertEqual(watch.exit_status(rows), 0)
        self.assertEqual({r.check for r in rows}, {"advisory", "extension", "image"})

    def test_a_vulnerability_without_a_valid_exception_fails(self):
        net = FakeNet(
            vulns={("Maven", "org.bouncycastle:bcprov-jdk18on", "1.86"): ["GHSA-test-0001"]}, details={"GHSA-test-0001": ADVISORY}
        )
        _, rows = watch.run(net, NOW, exceptions=[])
        failing = [r for r in rows if r.state == "fail"]
        self.assertEqual(len(failing), 1)
        self.assertIn("ships in the APK", failing[0].text)
        self.assertIn("[HIGH]", failing[0].text)
        self.assertEqual(watch.exit_status(rows), 1)
        self.assertIn("**fail**", watch.markdown(*watch.run(net, NOW, exceptions=[])))

    def test_an_exception_covers_one_advisory_in_one_version_until_it_expires(self):
        net = FakeNet(
            vulns={("Maven", "org.bouncycastle:bcprov-jdk18on", "1.86"): ["GHSA-test-0001"]}, details={"GHSA-test-0001": ADVISORY}
        )
        base = {"ecosystem": "Maven", "package": "org.bouncycastle:bcprov-jdk18on", "reason": "test", "until": "2026-12-31"}
        accepted = {**base, "id": "CVE-2026-0001", "version": "1.86"}  # matched through an alias
        _, rows = watch.run(net, NOW, exceptions=[accepted])
        self.assertEqual([r.state for r in rows if r.check == "osv"], ["accepted"])
        self.assertEqual(watch.exit_status(rows), 0)
        other_version = {**accepted, "version": "1.85"}
        _, rows = watch.run(net, NOW, exceptions=[other_version])
        self.assertEqual(
            [r.state for r in rows if r.check in ("osv", "exception")], ["fail", "warn"]
        )  # and the stale entry is named
        expired = {**accepted, "until": "2026-10-26"}
        _, rows = watch.run(net, NOW, exceptions=[expired])
        self.assertEqual([r.state for r in rows if r.check == "osv"], ["fail"])
        self.assertIn("expired", next(r.text for r in rows if r.check == "osv"))
        withdrawn = FakeNet(vulns=net.vulns, details={"GHSA-test-0001": {**ADVISORY, "withdrawn": "2026-10-01T00:00:00Z"}})
        self.assertEqual(watch.exit_status(watch.run(withdrawn, NOW, exceptions=[])[1]), 0)

    def test_actions_are_matched_locally(self):
        record = {
            "id": "GHSA-test-0002",
            "affected": [{"package": {"ecosystem": "GitHub Actions", "name": "actions/checkout"},
                          "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "99.0.0"}]}]}],
        }  # fmt: skip
        fixed = {**record, "id": "GHSA-test-0003"}
        fixed["affected"] = [
            {**record["affected"][0], "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.0.0"}]}]}
        ]
        net = FakeNet(
            action_vulns={"actions/checkout": [record, fixed]}, details={"GHSA-test-0002": ADVISORY, "GHSA-test-0003": ADVISORY}
        )
        _, rows = watch.run(net, NOW, exceptions=[])
        failing = [r.text for r in rows if r.state == "fail"]
        self.assertEqual(len(failing), 1)
        self.assertIn("GHSA-test-0002", failing[0])

    def test_extension_verdicts(self):
        entry = {"key": "x", "id": "x@y", "version": "1.0", "sha256": "a" * 64, "size": 10}
        same = {"version": "1.0", "sha256": "a" * 64, "size": 10, "created": "2026-01-01T00:00:00Z"}
        now = watch.parse_time("2026-03-01T00:00:00Z")

        def verdict(current, block=None, served=same, newer=None, complete=True):
            return watch.extension_verdict(entry, served, current, newer, block, now, complete)[0]

        self.assertEqual(verdict(same), "ok")
        self.assertEqual(verdict({**same, "sha256": "b" * 64}), "fail")
        self.assertEqual(verdict(same, {"blocked": ["1.0"], "soft_blocked": []}), "fail")
        self.assertEqual(verdict(same, {"blocked": [], "soft_blocked": ["1.0"]}), "fail")
        self.assertEqual(verdict(same, {"is_all_versions": True}), "fail")
        self.assertEqual(verdict(same, {"blocked": ["0.9"], "soft_blocked": []}), "ok")
        newer = {**same, "version": "1.1", "created": "2026-02-25T00:00:00Z"}
        self.assertEqual(verdict(newer), "warn")  # no first newer version known: counted from the current one
        self.assertEqual(verdict({**newer, "created": "2026-01-02T00:00:00Z"}), "fail")
        # the lag is counted from the first version after the pin, not from AMO's newest (#629)
        first = {"version": "1.0.1", "created": "2026-01-15T00:00:00Z"}
        self.assertEqual(verdict(newer, newer=first), "fail")
        self.assertEqual(verdict(newer, newer={**first, "created": "2026-02-20T00:00:00Z"}), "warn")
        # the pinned version's own file is checked while a newer version exists
        self.assertEqual(verdict(newer, served={**same, "sha256": "b" * 64}, newer=first), "fail")
        self.assertEqual(verdict(newer, served={**same, "size": 11}), "fail")
        self.assertEqual(verdict(same, served={**same, "size": 11}), "fail")
        self.assertEqual(verdict(newer, served=None), "fail")  # AMO no longer has the pinned version
        # a versions list not read back to the pin: a lower bound, which fails once it is over the limit
        self.assertEqual(verdict(newer, newer=first, complete=False), "fail")
        self.assertEqual(verdict(newer, newer={**first, "created": "2026-02-20T00:00:00Z"}, complete=False), "error")
        # AMO's current version counts only when it came after the pin, in number and in date (OCR on #820)
        backport = {**same, "version": "0.9.1", "created": "2026-01-02T00:00:00Z"}
        self.assertEqual(verdict(backport), "warn")
        self.assertIn("is not newer than the pin", watch.extension_verdict(entry, same, backport, None, None, now)[1])
        self.assertEqual(verdict({**same, "version": "1.1", "created": "2025-12-01T00:00:00Z"}), "warn")
        self.assertEqual(verdict(backport, complete=False), "error")
        # a lock written in upper-case hex, as the launcher accepts it, is the same file
        upper = {**entry, "sha256": "A" * 64}
        self.assertEqual(watch.extension_verdict(upper, same, same, None, None, now)[0], "ok")
        self.assertEqual(watch.extension_verdict(upper, same, newer, None, None, now)[0], "warn")

    def test_a_blocked_extension_fails_the_run(self):
        guid = "uBlock0@raymondhill.net"
        net = FakeNet(blocks={guid: {"blocked": [], "soft_blocked": [], "is_all_versions": True}})
        _, rows = watch.run(net, NOW, exceptions=[])
        self.assertEqual([r.detail["key"] for r in rows if r.state == "fail"], ["ublock-origin"])

    def test_a_newer_image_build_is_reported_not_failed(self):
        ref = next(ref for name, ref in watch.image_refs(ROOT) if name == "ubuntu-itest.Containerfile")
        net = FakeNet(digests={watch.manifest_url(ref): "sha256:" + "b" * 64})
        _, rows = watch.run(net, NOW, exceptions=[])
        self.assertEqual([r.state for r in rows if r.check == "image"].count("warn"), 1)
        self.assertEqual(watch.exit_status(rows), 0)

    def test_registry_digest_asks_for_an_anonymous_token(self):
        class Registry:
            def __init__(self):
                self.calls = []

            def head(self, url, headers):
                self.calls.append(("head", url, headers.get("Authorization")))
                if "Authorization" not in headers:
                    challenge = 'Bearer realm="https://auth.example.org/token",service="registry.example.org",'
                    return 401, {"www-authenticate": challenge + 'scope="repository:library/ubuntu:pull"'}
                return 200, {"docker-content-digest": "sha256:" + "c" * 64}

            def json(self, url, data=None, missing_ok=False):
                self.calls.append(("token", url, None))
                return {"token": "anonymous-test-token"}

        registry = Registry()
        digest = watch.registry_digest("docker.io/library/ubuntu:26.10@sha256:" + "a" * 64, registry)
        self.assertEqual(digest, "sha256:" + "c" * 64)
        self.assertEqual(registry.calls[0][1], "https://registry-1.docker.io/v2/library/ubuntu/manifests/26.10")
        self.assertTrue(registry.calls[1][1].startswith("https://auth.example.org/token?service=registry.example.org&scope="))
        self.assertEqual(registry.calls[2][2], "Bearer anonymous-test-token")
        with self.assertRaises(ValueError):
            watch.manifest_url("fedora:44")  # short names are ambiguous

    def test_one_source_down_does_not_hide_what_the_others_found(self):
        vulnerable = {("Maven", "org.bouncycastle:bcprov-jdk18on", "1.86"): ["GHSA-test-0001"]}
        net = FakeNet(vulns=vulnerable, details={"GHSA-test-0001": ADVISORY}, down=[watch.AMO, "https://registry-1.docker.io/"])
        _, rows = watch.run(net, NOW, exceptions=[])
        states = sorted({(r.check, r.state) for r in rows if r.state in ("fail", "error")})
        self.assertEqual(states, [("extension", "error"), ("image", "error"), ("osv", "fail")])
        self.assertEqual(watch.exit_status(rows), 1)  # action needed outranks missing data
        self.assertIn("no data from addons.mozilla.org", watch.report([], rows))
        images = {r.text.split(":")[0]: r.state for r in rows if r.check == "image"}
        self.assertEqual(images["ubuntu-itest.Containerfile"], "error")
        self.assertEqual(images["fedora-build.Containerfile"], "ok")  # one registry down, the other still checked
        _, rows = watch.run(FakeNet(down=[watch.OSV]), NOW, exceptions=[])
        self.assertEqual([r.state for r in rows if r.check == "osv"], ["error"])
        self.assertEqual({r.state for r in rows if r.check != "osv"}, {"ok"})
        self.assertEqual(watch.exit_status(rows), 2)
        self.assertTrue(watch.markdown([], rows).splitlines()[2].startswith("Could not check"), watch.markdown([], rows))

    def test_a_malformed_exception_stops_the_run(self):
        good = {
            "id": "GHSA-test-0001",
            "ecosystem": "Maven",
            "package": "a:b",
            "version": "1",
            "reason": "r",
            "until": "2026-12-31",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "exceptions.json"
            for bad in ({**good, "until": "soon"}, {k: v for k, v in good.items() if k != "version"}, {**good, "reason": " "}):
                path.write_text(json.dumps({"exceptions": [bad]}))
                with self.assertRaises(ValueError, msg=bad):
                    watch.load_exceptions(path)
            path.write_text(json.dumps({"exceptions": [good]}))
            self.assertEqual(watch.load_exceptions(path), [good])

    def test_only_https_is_fetched(self):
        with self.assertRaises(ValueError):
            watch.Net().json("http://api.osv.dev/v1/query")


AMO_FIXTURES = ROOT / "tests" / "fixtures" / "amo"


class RecordedAmo:
    """AMO's replies recorded on 2026-11-26 (tests/fixtures/amo/<key>.json), keyed by the path the watch requests."""

    def __init__(self, keys, change=None, down=()):
        self.records = [json.loads((AMO_FIXTURES / f"{key}.json").read_text()) for key in keys]
        self.down = down  # path prefixes that fail as if AMO were unreachable there
        self.replies = {}
        for record in self.records:
            self.replies.update(record["replies"])
        for path, reply in (change or {}).items():
            self.replies[path] = reply
        self.requested = []

    def lock(self, tmp: Path) -> Path:
        """A repository root whose lock holds the recorded pins, so a refresh of the real lock leaves these tests alone."""
        target = tmp / "browser" / "distribution" / "extensions.lock.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"extensions": [r["lock"] for r in self.records]}))
        return tmp

    def json(self, url, data=None, missing_ok=False):
        self.requested.append(url)
        if not url.startswith(watch.AMO):
            raise AssertionError(f"unexpected URL {url}")
        path = url[len(watch.AMO) :]
        if path.startswith(tuple(self.down)):
            raise OSError(f"test: {path} is down")
        if path not in self.replies:
            raise AssertionError(f"not recorded: {path}")
        reply = self.replies[path]
        if reply is None and not missing_ok:
            raise AssertionError(f"a 404 that the watch does not expect: {path}")
        return copy.deepcopy(reply)


UBLOCK = "addons/addon/uBlock0%40raymondhill.net/"


def at(text: str) -> datetime.datetime:
    return watch.parse_time(text)


class ExtensionLagTest(unittest.TestCase):
    """The lag is counted from the first version AMO published after the pin, and the pinned file is read on every
    run (#629): on AMO's replies recorded on 2026-11-26, and on a made-up stream of releases."""

    KEYS = ("ublock-origin", "proton-pass", "keepassxc-browser", "bitwarden", "1password")

    def rows(self, net, now):
        with tempfile.TemporaryDirectory() as tmp:
            return {r.detail["key"]: r for r in watch.extension_rows(net, now, net.lock(Path(tmp)))}

    def test_the_recorded_pins_of_2026_11_26(self):
        rows = self.rows(RecordedAmo(self.KEYS), at("2026-11-26T20:00:00Z"))
        self.assertEqual({k: r.state for k, r in rows.items()}, {
            "ublock-origin": "warn", "proton-pass": "warn", "keepassxc-browser": "ok", "bitwarden": "warn", "1password": "warn",
        })  # fmt: skip
        # uBlock Origin: pinned 1.76.4, AMO's newest is 1.77.2 (that day), the first after the pin 1.76.6 (6 days earlier)
        self.assertEqual(
            rows["ublock-origin"].text, "ublock-origin pinned 1.76.4, AMO has had 1.76.6 for 6 days (current 1.77.2)"
        )
        self.assertEqual(
            rows["ublock-origin"].detail, {"key": "ublock-origin", "pinned": "1.76.4", "amo": "1.77.2", "newer": "1.76.6"}
        )
        self.assertEqual(rows["proton-pass"].detail["newer"], "1.43.1")
        self.assertIn("for 23 days (current 1.44.0)", rows["proton-pass"].text)
        self.assertEqual(rows["bitwarden"].detail["newer"], "2026.11.0")  # the first newer one is the current one
        self.assertNotIn("current", rows["bitwarden"].text)
        # KeePassXC-Browser's blocklist entry covers two old versions, not the pin
        self.assertEqual(rows["keepassxc-browser"].text, "keepassxc-browser 1.10.4.1 is AMO's current version")

    def test_a_pin_left_behind_fails_while_amo_keeps_releasing(self):
        # 2026-12-22: uBlock Origin's newest recorded version (1.77.2) is 26 days old, so counting from it, as the
        # watch did before #629, gave a warning; the pin was first superseded (1.76.6) 32 days before.
        now = at("2026-12-22T20:00:00Z")
        net = RecordedAmo(["ublock-origin"])
        current = net.replies[UBLOCK]["current_version"]["file"]["created"]
        self.assertLessEqual((now - at(current)).days, watch.EXTENSION_LAG_DAYS)
        row = self.rows(net, now)["ublock-origin"]
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.76.6 for 32 days (current 1.77.2)", row.text)
        # Proton Pass: 1.43.1 (2026-11-03) is 31 days old on 2026-12-04, its newest 1.44.0 only 16
        row = self.rows(RecordedAmo(["proton-pass"]), at("2026-12-04T20:00:00Z"))["proton-pass"]
        self.assertEqual(row.state, "fail", row.text)

    def test_a_replaced_pinned_file_fails_while_a_newer_version_exists(self):
        pinned = UBLOCK + "versions/1.76.4/"
        reply = RecordedAmo(["ublock-origin"]).replies[pinned]
        now = at("2026-11-26T20:00:00Z")
        for change in (
            {**reply, "file": {**reply["file"], "hash": "sha256:" + "b" * 64}},
            {**reply, "file": {**reply["file"], "size": reply["file"]["size"] + 1}},
        ):
            net = RecordedAmo(["ublock-origin"], {pinned: change})
            row = self.rows(net, now)["ublock-origin"]
            self.assertEqual(row.state, "fail", row.text)
            self.assertIn("AMO now serves a different file", row.text)
            self.assertIn(watch.AMO + pinned, net.requested)
        row = self.rows(RecordedAmo(["ublock-origin"], {pinned: None}), now)["ublock-origin"]  # a 404
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("no longer serves the pinned version", row.text)
        # the pinned file is read when the pin is AMO's current version too
        net = RecordedAmo(["keepassxc-browser"])
        path = "addons/addon/keepassxc-browser%40keepassxc.org/versions/1.10.4.1/"
        net.replies[path]["file"]["hash"] = "sha256:" + "c" * 64
        self.assertEqual(self.rows(net, now)["keepassxc-browser"].state, "fail")

    def test_a_malformed_reply_is_unavailable_data(self):
        pinned = UBLOCK + "versions/1.76.4/"
        reply = RecordedAmo(["ublock-origin"]).replies[pinned]
        listed = UBLOCK + "versions/?page=1&page_size=50"
        page = RecordedAmo(["ublock-origin"]).replies[listed]
        first = page["results"][0]  # 1.77.2, newer than the pin
        for change in (
            {pinned: {**reply, "file": {**reply["file"], "hash": "md5:" + "a" * 32}}},
            {pinned: {**reply, "file": {**reply["file"], "size": "6332093"}}},
            {pinned: {**reply, "version": "1.76.6"}},  # an answer for another version
            {listed: {"next": None, "results": "none"}},
            {listed: {"next": None, "results": [None]}},
            {listed: {"next": None, "results": [{"version": 1.77, "file": {"created": "2026-11-26T00:00:00Z"}}]}},
            {listed: {"next": None, "results": [{"version": "1.77", "file": {"created": 1}}]}},
            {pinned: {**reply, "file": {**reply["file"], "created": None}}},
            {pinned: {**reply, "file": {**reply["file"], "size": 0}}},
            {pinned: {**reply, "file": {**reply["file"], "size": -1}}},
            {listed: {k: v for k, v in page.items() if k != "next"}},  # no "next": the end of the list is not known
            {listed: {**page, "next": 2}},
            {listed: {**page, "results": [{k: v for k, v in first.items() if k != "channel"}, *page["results"][1:]]}},
            {listed: {**page, "results": [{**first, "file": {**first["file"], "status": None}}, *page["results"][1:]]}},
        ):
            row = self.rows(RecordedAmo(["ublock-origin"], change), at("2026-11-26T20:00:00Z"))["ublock-origin"]
            self.assertEqual(row.state, "error", (change, row.text))

    def test_an_upper_case_digest_from_amo_is_the_same_file(self):
        pinned = UBLOCK + "versions/1.76.4/"
        reply = RecordedAmo(["ublock-origin"]).replies[pinned]
        change = {pinned: {**reply, "file": {**reply["file"], "hash": reply["file"]["hash"].upper().replace("SHA256", "sha256")}}}
        row = self.rows(RecordedAmo(["ublock-origin"], change), at("2026-11-26T20:00:00Z"))["ublock-origin"]
        self.assertEqual(row.state, "warn", row.text)

    def test_a_confirmed_failure_stands_when_another_amo_reply_is_missing(self):
        # OCR on #820: the blocklist, the pinned file and the lag are judged apart, so one endpoint down hides no failure
        now = at("2026-11-26T20:00:00Z")
        guid = "uBlock0%40raymondhill.net"
        pinned = UBLOCK + "versions/1.76.4/"
        listed = UBLOCK + "versions/?"
        block = f"blocklist/block/{guid}/"
        blocked = {block: {"blocked": ["1.76.4"], "soft_blocked": [], "is_all_versions": False}}
        reply = RecordedAmo(["ublock-origin"]).replies[pinned]
        replaced = {pinned: {**reply, "file": {**reply["file"], "hash": "sha256:" + "b" * 64}}}
        for change, down, expect in (
            (blocked, [UBLOCK + "versions/"], "blocklist"),  # the pin and the versions list down
            (blocked, [UBLOCK], "blocklist"),  # every add-on reply down
            (replaced, [listed], "different file"),
            (replaced, [block], "different file"),
            ({pinned: None}, [block, listed], "no longer serves"),
        ):
            row = self.rows(RecordedAmo(["ublock-origin"], change, down), now)["ublock-origin"]
            self.assertEqual(row.state, "fail", (down, row.text))
            self.assertIn(expect, row.text)
        # the pin is AMO's current version and the summary shows another file: that stands with the pin's reply down
        keepass = "addons/addon/keepassxc-browser%40keepassxc.org/"
        net = RecordedAmo(["keepassxc-browser"], down=[keepass + "versions/1.10.4.1/"])
        net.replies[keepass]["current_version"]["file"]["hash"] = "sha256:" + "c" * 64
        row = self.rows(net, now)["keepassxc-browser"]
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("different file", row.text)
        # a lag already over the limit stands when only the blocklist is down
        row = self.rows(RecordedAmo(["ublock-origin"], down=[block]), at("2026-12-22T20:00:00Z"))["ublock-origin"]
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("for 32 days", row.text)
        # nothing confirmed: unavailable data, never a pass or a warning
        for down in ([block], [listed], [pinned], [UBLOCK]):
            row = self.rows(RecordedAmo(["ublock-origin"], down=down), now)["ublock-origin"]
            self.assertEqual(row.state, "error", (down, row.text))
            self.assertIn("no data from addons.mozilla.org", row.text)

    def test_a_backport_as_current_is_not_a_lag(self):
        # the pin (1.0) is AMO's newest number; AMO's current is a backport (0.9.1) made after it, 60 days ago
        versions = self.stream(0)
        backport = {**versions[0], "version": "0.9.1", "file": {**versions[0]["file"], "created": "2026-05-02T00:00:00Z"}}
        row, _ = self.stream_row([backport, *versions], at("2026-07-01T00:00:00Z"))
        self.assertEqual(row.state, "warn", row.text)
        self.assertIn("0.9.1 is not newer than the pin", row.text)

    def stream(self, count, every_days=10):
        """A pin (1.0, 2026-05-01) followed by `count` releases, one every `every_days` days, newest first."""
        start = at("2026-05-01T00:00:00Z")
        made = [(f"1.{n}", start + datetime.timedelta(days=every_days * n)) for n in range(count + 1)]
        return [
            {
                "version": v,
                "channel": "listed",
                "file": {
                    "hash": "sha256:" + "a" * 64,
                    "size": 10,
                    "created": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "public",
                },
            }
            for v, t in reversed(made)
        ]

    def stream_net(self, versions, down_pages=()):
        """AMO for that stream: the versions list in pages, with a "next" link that points elsewhere."""
        base = f"{watch.AMO}addons/addon/x%40y/"

        class Stream:
            def __init__(self):
                self.requested = []

            def json(self, url, data=None, missing_ok=False):
                self.requested.append(url)
                if url == base:
                    return {"current_version": versions[0]}
                if url == base + "versions/1.0/":
                    return versions[-1]
                if url == f"{watch.AMO}blocklist/block/x%40y/":
                    return None
                if not url.startswith(base + "versions/?"):
                    raise AssertionError(f"unexpected URL {url}")
                query = urllib.parse.parse_qs(url.partition("?")[2])
                page, size = int(query["page"][0]), int(query["page_size"][0])
                if page in down_pages:
                    raise OSError(f"test: page {page} is down")
                more = page * size < len(versions)
                return {
                    "next": "https://elsewhere.example/next" if more else None,
                    "results": versions[(page - 1) * size : page * size],
                }

        return Stream()

    def stream_row(self, versions, now, page_size=5, pages=watch.VERSIONS_PAGES, down_pages=()):
        net = self.stream_net(versions, down_pages)
        entry = {"key": "x", "id": "x@y", "version": "1.0", "sha256": "a" * 64, "size": 10}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "browser" / "distribution" / "extensions.lock.json"
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({"extensions": [entry]}))
            with mock.patch.object(watch, "VERSIONS_PAGE_SIZE", page_size), mock.patch.object(watch, "VERSIONS_PAGES", pages):
                (row,) = watch.extension_rows(net, now, Path(tmp))
        return row, net.requested

    def test_a_stream_of_releases_counts_from_the_first_after_the_pin(self):
        # a release every 10 days since the pin (2026-05-01): the newest is always under 30 days old
        versions = self.stream(17)  # 1.1 (2026-05-11) ... 1.17 (2026-10-28)
        row, requested = self.stream_row(versions, at("2026-10-30T00:00:00Z"))
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.1 for 172 days (current 1.17)", row.text)
        pages = [u for u in requested if "versions/?" in u]
        self.assertEqual(len(pages), 4)  # 18 versions, 5 a page: read until the pin, no further
        self.assertTrue(all(u.startswith(watch.AMO) for u in requested), "a reply's next link is never followed")
        # within the limit: only a warning, counted from 1.1 and not from 1.3
        row, _ = self.stream_row(self.stream(3), at("2026-05-31T00:00:00Z"))
        self.assertEqual((row.state, row.detail["newer"]), ("warn", "1.1"))
        self.assertIn("for 20 days (current 1.3)", row.text)

    def test_a_list_not_read_back_to_the_pin_is_a_lower_bound(self):
        versions = self.stream(17)
        row, requested = self.stream_row(versions, at("2026-10-30T00:00:00Z"), pages=2)
        self.assertEqual(len([u for u in requested if "versions/?" in u]), 2)
        self.assertEqual(row.state, "fail", row.text)  # 1.8, the oldest seen, is already 102 days old
        self.assertIn("for at least 102 days", row.text)
        # a release every day: two pages of five reach back 10 days, not to the pin; nothing is known to pass
        row, _ = self.stream_row(self.stream(40, every_days=1), at("2026-06-11T00:00:00Z"), pages=2)
        self.assertEqual(row.state, "error", row.text)
        self.assertIn("not read back to the pin", row.text)

    def test_only_listed_public_versions_after_the_pin_count(self):
        versions = self.stream(4)  # 1.4, 1.3, 1.2, 1.1, 1.0
        versions[3] = {**versions[3], "channel": "unlisted"}  # 1.1
        versions[2] = {**versions[2], "file": {**versions[2]["file"], "status": "disabled"}}  # 1.2
        row, _ = self.stream_row(versions, at("2026-06-15T00:00:00Z"))
        self.assertEqual(row.detail["newer"], "1.3", row.text)
        backport = {**versions[1], "version": "0.9.1"}  # made after the pin, numbered below it
        row, _ = self.stream_row([versions[0], backport, versions[-1]], at("2026-06-15T00:00:00Z"))
        self.assertEqual(row.detail["newer"], "1.4", row.text)

    # OCR round 2 on #820 -----------------------------------------------------------------------------------------

    def test_a_current_version_the_list_shows_disabled_is_not_counted(self):
        versions = self.stream(1)  # 1.1 (2026-05-11), AMO's current, and the pin
        versions[0] = {**versions[0], "file": {**versions[0]["file"], "status": "disabled"}}
        row, _ = self.stream_row(versions, at("2026-06-20T00:00:00Z"))
        self.assertEqual(row.state, "warn", row.text)
        self.assertIn("1.1 is not listed and public in AMO's versions list", row.text)

    def test_a_malformed_blocklist_entry_hides_no_other_failure(self):
        now = at("2026-11-26T20:00:00Z")
        block = "blocklist/block/uBlock0%40raymondhill.net/"
        pinned = UBLOCK + "versions/1.76.4/"
        reply = RecordedAmo(["ublock-origin"]).replies[pinned]
        replaced = {pinned: {**reply, "file": {**reply["file"], "hash": "sha256:" + "b" * 64}}}
        row = self.rows(RecordedAmo(["ublock-origin"], {**replaced, block: {"blocked": None, "soft_blocked": []}}), now)
        self.assertEqual(row["ublock-origin"].state, "fail", row["ublock-origin"].text)
        self.assertIn("different file", row["ublock-origin"].text)
        for entry in (
            [{"blocked": ["1.76.4"]}],  # a list, not an entry
            {"blocked": [], "soft_blocked": [], "is_all_versions": "false"},  # text, not a boolean
            {"blocked": [], "soft_blocked": [1], "is_all_versions": False},
            {"soft_blocked": [], "is_all_versions": False},  # no "blocked": not known to be unblocked
        ):
            row = self.rows(RecordedAmo(["ublock-origin"], {block: entry}), now)["ublock-origin"]
            self.assertEqual(row.state, "error", (entry, row.text))

    def test_a_lag_seen_before_the_list_failed_stands(self):
        versions = self.stream(17)  # 1.13 ... 1.17 on page one, the oldest of them 52 days old on 2026-10-30
        row, _ = self.stream_row(versions, at("2026-10-30T00:00:00Z"), down_pages=(2,))
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.13 for at least 52 days (current 1.17)", row.text)
        # the list down from its first page: AMO's current version, after the pin in number and date, is a lower bound
        row, _ = self.stream_row(versions, at("2026-12-15T00:00:00Z"), down_pages=(1,))
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.17 for at least 58 days", row.text)
        row, _ = self.stream_row(versions, at("2026-11-15T00:00:00Z"), down_pages=(1,))  # 28 days: nothing confirmed
        self.assertEqual(row.state, "error", row.text)
        # a malformed page counts for nothing: 1.14 (48 days) is on it, and 1.17 is 28 days old
        broken = [*versions[:4], {"version": 2}, *versions[4:]]
        row, _ = self.stream_row(broken, at("2026-11-15T00:00:00Z"))
        self.assertEqual(row.state, "error", row.text)

    def test_the_versions_list_judges_the_lag_when_the_summary_is_missing(self):
        net = RecordedAmo(["ublock-origin"], {UBLOCK: {"current_version": None}})  # a malformed summary
        row = self.rows(net, at("2026-12-22T20:00:00Z"))["ublock-origin"]
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.76.6 for 32 days", row.text)
        row = self.rows(RecordedAmo(["ublock-origin"], {UBLOCK: {"current_version": None}}), at("2026-11-26T20:00:00Z"))
        self.assertEqual(row["ublock-origin"].state, "error", row["ublock-origin"].text)

    def test_amo_timing_out_leaves_the_watch_time_for_the_other_checks(self):
        clock = [0.0]

        def urlopen(request, timeout):
            clock[0] += timeout  # every AMO request waits for its whole timeout
            raise TimeoutError("test: timed out")

        net = watch.Net(clock=lambda: clock[0], sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(watch.urllib.request, "urlopen", urlopen):
            rows = watch.extension_rows(net, at("2026-11-26T20:00:00Z"), RecordedAmo(self.KEYS).lock(Path(tmp)))
        self.assertEqual({r.state for r in rows}, {"error"})
        self.assertLessEqual(clock[0], 150)  # what main spent in that outage: one 30 s request per extension

    def test_a_lag_behind_a_backport_made_current_is_not_fixed_by_the_refresh_script(self):
        versions = self.stream(1)  # 1.1 (2026-05-11) and the pin
        backport = {**versions[0], "version": "0.9.1", "file": {**versions[0]["file"], "created": "2026-06-01T00:00:00Z"}}
        row, _ = self.stream_row([backport, *versions], at("2026-06-20T00:00:00Z"))
        self.assertEqual(row.state, "fail", row.text)
        self.assertIn("AMO has had 1.1 for 40 days (current 0.9.1)", row.text)
        self.assertNotIn("refresh_extensions_lock.py and review", row.text)  # it takes AMO's current one, a downgrade
        self.assertIn("update the lock to 1.1 by hand", row.text)

    def test_a_date_without_a_time_zone_is_malformed(self):
        with self.assertRaises(ValueError):
            watch.parse_time("2026-10-02")
        path = "addons/addon/keepassxc-browser%40keepassxc.org/versions/1.10.4.1/"
        net = RecordedAmo(["keepassxc-browser"])
        net.replies[path]["file"]["created"] = "2026-10-02T00:00:00"
        row = self.rows(net, at("2026-11-26T20:00:00Z"))["keepassxc-browser"]
        self.assertEqual(row.state, "error", row.text)


class GradleReviewTest(unittest.TestCase):
    """scripts/upstream/review_gradle_verification.py on fixture metadata, a fake cache and fake published checksums."""

    HEAD = '<?xml version="1.0"?><verification-metadata xmlns="https://schema.gradle.org/dependency-verification">'
    CONFIG = "<configuration><verify-metadata>true</verify-metadata><verify-signatures>false</verify-signatures></configuration>"

    def xml(self, components: dict, config: str = CONFIG) -> str:
        body = ""
        for (group, name, version), artifacts in components.items():
            body += f'<component group="{group}" name="{name}" version="{version}">'
            body += "".join(
                f'<artifact name="{a}"><sha256 value="{v}" origin="Generated by Gradle"/></artifact>'
                for a, v in artifacts.items()
            )
            body += "</component>"
        return f"{self.HEAD}{config}<components>{body}</components></verification-metadata>"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caches = [Path(self.tmp.name) / "caches"]
        self.jar = b"new jar"
        folder = self.caches[0] / "modules-2" / "files-2.1" / "org.example" / "lib" / "2.0" / "0123abcd"
        folder.mkdir(parents=True)
        (folder / "lib-2.0.jar").write_bytes(self.jar)
        self.sha256 = hashlib.sha256(self.jar).hexdigest()
        self.published = {
            "https://repo.maven.apache.org/maven2/org/example/lib/2.0/lib-2.0.jar.sha1": hashlib.sha1(self.jar).hexdigest(),  # noqa: S324
            "https://repo.maven.apache.org/maven2/org/example/lib/2.0/lib-2.0.jar.asc": "-----BEGIN PGP SIGNATURE-----",
        }
        self.old = {("org.example", "lib", "1.0"): {"lib-1.0.jar": "1" * 64}}
        self.locks = {"android/app/gradle.lockfile": "org.example:lib:2.0=releaseRuntimeClasspath\nempty=\n"}
        self.old_locks = {"android/app/gradle.lockfile": "org.example:lib:1.0=releaseRuntimeClasspath\nempty=\n"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_review(self, new: dict, config: str = CONFIG, locks: dict | None = None):
        return review.review(
            self.xml(self.old), self.xml(new, config), self.old_locks, locks or self.locks, self.caches, self.published.get
        )

    def test_a_reviewed_bump_passes_and_lists_what_to_remove(self):
        lines, problems = self.run_review({**self.old, ("org.example", "lib", "2.0"): {"lib-2.0.jar": self.sha256}})
        self.assertEqual(problems, 0, lines)
        self.assertIn("+ org.example:lib:2.0", lines)
        self.assertTrue(any("sha1 matches https://repo.maven.apache.org/maven2/; signed (.asc)" in line for line in lines), lines)
        self.assertIn("    org.example:lib:1.0", lines)  # stale version to remove
        self.assertIn("    + org.example:lib:2.0=releaseRuntimeClasspath", lines)

    def test_a_hash_that_disagrees_with_the_repository_or_cache_is_a_problem(self):
        _, problems = self.run_review({**self.old, ("org.example", "lib", "2.0"): {"lib-2.0.jar": "f" * 64}})
        self.assertGreaterEqual(problems, 1)
        self.published.pop("https://repo.maven.apache.org/maven2/org/example/lib/2.0/lib-2.0.jar.sha1")
        lines, problems = self.run_review({**self.old, ("org.example", "lib", "2.0"): {"lib-2.0.jar": self.sha256}})
        self.assertEqual(problems, 1)
        self.assertTrue(any("no published checksum" in line for line in lines))

    def test_rewriting_a_pinned_version_or_the_configuration_is_a_problem(self):
        lines, problems = self.run_review({("org.example", "lib", "1.0"): {"lib-1.0.jar": "2" * 64}}, locks=self.old_locks)
        self.assertEqual(problems, 1, lines)
        self.assertIn("already pinned", lines[0])
        loose = self.CONFIG.replace("<verify-metadata>true", "<verify-metadata>false")
        _, problems = self.run_review(self.old, config=loose, locks=self.old_locks)
        self.assertEqual(problems, 1)

    def test_a_locked_module_must_be_pinned(self):
        lines, problems = self.run_review(self.old)
        self.assertEqual(problems, 1)
        self.assertIn("locked but not pinned", lines[-2])


if __name__ == "__main__":
    unittest.main()
