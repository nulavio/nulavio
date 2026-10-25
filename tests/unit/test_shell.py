"""Nulavio Shell built-in add-on: manifest, privacy, i18n and packaging."""

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

import make_shell  # noqa: E402

SHELL = ROOT / "browser" / "shell"
ALLOWED_PERMISSIONS = {"downloads", "management", "privacy", "search"}
FLOW_E_TYPES = {".appimage", ".sh", ".run", ".desktop", ".deb", ".rpm", ".flatpakref"}  # docs/brand/ux-flows.md


def locale(name: str) -> dict:
    return json.loads((SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8"))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = make_shell.manifest()

    def test_identity(self):
        self.assertEqual(self.manifest["manifest_version"], 3)
        self.assertEqual(self.manifest["browser_specific_settings"]["gecko"]["id"], "shell@nulavio.net")
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_least_privilege(self):
        self.assertEqual(set(self.manifest["permissions"]), ALLOWED_PERMISSIONS)
        for key in (
            "host_permissions",
            "optional_permissions",
            "optional_host_permissions",
            "content_scripts",
            "web_accessible_resources",
            "externally_connectable",
            "content_security_policy",
        ):
            self.assertNotIn(key, self.manifest, f"{key} widens the Shell's reach or relaxes its CSP")

    def test_no_remote_resources_or_inline_code(self):
        for page in SHELL.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertNotRegex(text, r"""(src|href)=["']https?:""", "remote resource")
                self.assertNotRegex(text, r"<script(?![^>]*\bsrc=)", "inline script")
                self.assertNotIn("style=", text, "inline style")
        for script in SHELL.rglob("*.js"):
            text = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertNotRegex(
                    text, r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", "HTML injection sink"
                )
                self.assertNotRegex(text, r"\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon", "the Shell makes no network requests")
                self.assertNotRegex(text, r"\beval\(|new Function\(")

    def test_flow_e_has_no_open_action(self):
        warning = (SHELL / "warning" / "warning.js").read_text(encoding="utf-8")
        self.assertNotIn("downloads.open", warning)
        self.assertNotIn("downloads.open", json.dumps(self.manifest))

    def test_risky_types_cover_flow_e(self):
        source = (SHELL / "lib" / "risky.js").read_text(encoding="utf-8")
        listed = set(re.findall(r'"(\.[a-z0-9]+)"', source))
        self.assertTrue(listed >= FLOW_E_TYPES, FLOW_E_TYPES - listed)


class LocaleTest(unittest.TestCase):
    def test_same_keys_and_placeholders(self):
        en, pt = locale("en"), locale("pt_BR")
        self.assertEqual(set(en), set(pt))
        for key in en:
            with self.subTest(key=key):
                self.assertEqual(set(en[key].get("placeholders", {})), set(pt[key].get("placeholders", {})))
                self.assertTrue(pt[key]["message"].strip())

    def test_every_referenced_key_exists(self):
        keys = set(locale("en"))
        referenced = set()
        for page in SHELL.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            referenced |= set(re.findall(r'data-i18n="([A-Za-z0-9]+)"', text))
            referenced |= {pair.split(":")[1] for pair in re.findall(r'data-i18n-attr="([^"]+)"', text)}
        for script in SHELL.rglob("*.js"):
            referenced |= set(re.findall(r'\bt\("([A-Za-z0-9]+)"', script.read_text(encoding="utf-8")))
        referenced |= {m[6:-2] for m in re.findall(r"__MSG_[A-Za-z0-9]+__", json.dumps(make_shell.manifest()))}
        self.assertEqual(referenced - keys, set())


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assembled_pages_resolve_every_local_reference(self):
        out = self.tmp / "shell"
        files = set(make_shell.assemble(out))
        for page in out.rglob("*.html"):
            for ref in re.findall(r'(?:src|href|srcset)="([^"]+)"', page.read_text(encoding="utf-8")):
                target = (page.parent / ref).resolve()
                with self.subTest(page=page.name, ref=ref):
                    self.assertTrue(target.is_file(), f"{ref} missing")
                    self.assertIn(str(target.relative_to(out.resolve())), files)
        for icon in make_shell.manifest()["icons"].values():
            self.assertIn(icon, files)

    def test_build_files_list_every_file_under_builtin_addons(self):
        branding = self.tmp / "branding"
        branding.mkdir()
        shell = make_shell.install(branding)
        generated = {"jar.mn", "moz.build"}
        files = sorted(str(p.relative_to(shell)) for p in shell.rglob("*") if p.is_file() and p.name not in generated)
        jar = (shell / "jar.mn").read_text(encoding="utf-8").splitlines()
        self.assertIn("browser.jar:", jar)
        entries = [line.strip() for line in jar if line.startswith("    ")]
        self.assertEqual(entries, [f"builtin-addons/nulavio-shell/{f} ({f})" for f in files])
        self.assertIn('JAR_MANIFESTS += ["jar.mn"]', (shell / "moz.build").read_text(encoding="utf-8"))

    def test_branding_builds_the_shell(self):
        moz_build = (ROOT / "browser" / "branding" / "nulavio" / "moz.build").read_text(encoding="utf-8")
        self.assertRegex(moz_build, r'DIRS \+= \[[^\]]*"shell"')


if __name__ == "__main__":
    unittest.main()
