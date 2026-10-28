"""Every pinned dependency stays pinned by version and hash, in a form the update tooling can maintain,
and the daily watcher (scripts/release/watch_dependencies.py) reaches the right verdicts. No network:
the watcher's and the Gradle review's network calls are replaced by fakes."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
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
RELEASE_SCRIPTS = ("make_rpm.sh", "make_deb.sh", "check_rpm.sh", "check_deb.sh", "sign_repo.sh", "test_signed_repo.sh")
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
        text = (ROOT / "requirements" / "dev.txt").read_text()
        requirements = [r for r in re.sub(r"\\\n\s*", " ", text).splitlines() if r.strip() and not r.lstrip().startswith("#")]
        self.assertTrue(requirements)
        for requirement in requirements:
            self.assertRegex(requirement, r"^[A-Za-z0-9_.\-]+==\S+ .*--hash=sha256:[0-9a-f]{64}", requirement)

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
        self.assertEqual(len(refs), 3)
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
                                     ("docker", "/ci/containers")]:  # fmt: skip
            self.assertRegex(config, rf'package-ecosystem: "{ecosystem}"\n\s+directory: "{re.escape(directory)}"')
        self.assertEqual(config.count("cooldown:"), 3)  # all but docker, whose registries give no release dates
        self.assertNotIn("insecure-external-code-execution", config)
        self.assertNotRegex(config, r"(?m)^\s*registries:")  # no credentials handed to Dependabot

    def test_vulnerability_exceptions_name_one_version_with_a_reason_and_an_expiry(self):
        data = json.loads((ROOT / "docs" / "security" / "vulnerability-exceptions.json").read_text())
        seen = set()
        for item in data["exceptions"]:
            self.assertEqual(set(item), {"id", "ecosystem", "package", "version", "reason", "until"}, item)
            self.assertRegex(item["id"], r"^(GHSA|CVE|PYSEC|OSV|BIT)-[\w-]+$", item)
            self.assertIn(item["ecosystem"], ("Maven", "PyPI", "GitHub Actions", "Bitnami"), item)
            self.assertGreater(len(item["reason"]), 40, item)
            until = datetime.date.fromisoformat(item["until"])
            self.assertLessEqual((until - datetime.date.today()).days, 366, f"{item['id']}: at most a year ahead")
            key = (item["id"], item["package"], item["version"])
            self.assertNotIn(key, seen)
            seen.add(key)


class FakeNet:
    """Stands in for watch_dependencies.Net: OSV, AMO and the registries answer from fixtures."""

    def __init__(self, vulns=None, action_vulns=None, details=None, digests=None, amo=None, blocks=None, down=()):
        self.down = down  # URL prefixes that fail as if the service were unreachable
        self.vulns = vulns or {}  # (ecosystem, name, version) -> [ids]
        self.action_vulns = action_vulns or {}  # name -> [OSV records]
        self.details = details or {}
        self.digests = digests or {}  # manifest URL -> digest (default: the pinned one)
        self.amo = amo or {}  # extension id -> current_version override
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
        guid = urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[1])
        if "/blocklist/block/" in url:
            if not missing_ok:
                raise AssertionError("a 404 from the blocklist means: not blocked")
            return self.blocks.get(guid)
        if "/addons/addon/" in url:
            entry = next(e for e in self.lock["extensions"] if e["id"] == guid)
            current = {
                "version": entry["version"],
                "file": {"hash": "sha256:" + entry["sha256"], "created": "2026-10-01T00:00:00Z"},
            }
            return {"current_version": self.amo.get(guid, current)}
        raise AssertionError(f"unexpected URL {url}")

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

    def test_clean_run_has_nothing_to_act_on(self):
        deps, rows = watch.run(FakeNet(), NOW, exceptions=[])
        self.assertGreater(len(deps), 200)
        self.assertEqual([r.text for r in rows if r.state != "ok"], [])
        self.assertEqual(watch.exit_status(rows), 0)
        self.assertEqual({r.check for r in rows}, {"extension", "image"})

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
        entry = {"key": "x", "id": "x@y", "version": "1.0", "sha256": "a" * 64}
        same = {"version": "1.0", "sha256": "a" * 64, "created": "2026-01-01T00:00:00Z"}
        now = watch.parse_time("2026-03-01T00:00:00Z")
        self.assertEqual(watch.extension_verdict(entry, same, None, now)[0], "ok")
        self.assertEqual(watch.extension_verdict(entry, {**same, "sha256": "b" * 64}, None, now)[0], "fail")
        self.assertEqual(watch.extension_verdict(entry, same, {"blocked": ["1.0"], "soft_blocked": []}, now)[0], "fail")
        self.assertEqual(watch.extension_verdict(entry, same, {"blocked": [], "soft_blocked": ["1.0"]}, now)[0], "fail")
        self.assertEqual(watch.extension_verdict(entry, same, {"is_all_versions": True}, now)[0], "fail")
        self.assertEqual(watch.extension_verdict(entry, same, {"blocked": ["0.9"], "soft_blocked": []}, now)[0], "ok")
        newer = {**same, "version": "1.1", "created": "2026-02-25T00:00:00Z"}
        self.assertEqual(watch.extension_verdict(entry, newer, None, now)[0], "warn")
        self.assertEqual(watch.extension_verdict(entry, {**newer, "created": "2026-01-02T00:00:00Z"}, None, now)[0], "fail")

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
