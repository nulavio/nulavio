"""Brand assets, design tokens and documentation hygiene."""

from __future__ import annotations

import json
import re
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "brand"))

import build_logo  # noqa: E402
import build_tokens  # noqa: E402
import contrast  # noqa: E402

ASSETS = ROOT / "docs" / "brand" / "assets"
SVG_NS = "{http://www.w3.org/2000/svg}"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


class TokensTest(unittest.TestCase):
    def test_all_contrast_pairs_pass(self):
        rows = contrast.check(json.loads(contrast.TOKENS.read_text()))
        failures = [r for r in rows if not r[-1]]
        self.assertEqual(failures, [])
        self.assertGreaterEqual(len(rows), 25)

    def test_generated_css_is_current(self):
        data = json.loads(build_tokens.TOKENS.read_text())
        for generate, output in (
            (build_tokens.build, build_tokens.OUTPUT),
            (build_tokens.build_chrome, build_tokens.CHROME_OUTPUT),
            (build_tokens.build_identity, build_tokens.IDENTITY_OUTPUT),
            (build_tokens.build_sidebar_focus, build_tokens.SIDEBAR_OUTPUT),
        ):
            with self.subTest(output=output):
                self.assertEqual(generate(data), output.read_text(), "run scripts/brand/build_tokens.py")

    def test_drawing_palette_preserves_ink_and_excludes_old_identity_names(self):
        js = build_tokens.build_identity(json.loads(build_tokens.TOKENS.read_text()))
        colors = dict(re.findall(r'  (\w+): "(#[A-F0-9]+)"', js))
        self.assertEqual(
            colors,
            {
                "lima": "#C5E384",
                "sky": "#8CCBF5",
                "violet": "#C2B0F7",
                "coral": "#F4A8BD",
                "sand": "#FDCF8B",
                "slate": "#BFD0D6",
                "on": "#070F18",
            },
        )

    def test_frost_floor_and_solid_fallback_are_enforced(self):
        data = json.loads(build_tokens.TOKENS.read_text())
        data["color"]["light"]["surface"]["frost"]["$value"] = "rgba(255,255,255,0.5)"
        with self.assertRaisesRegex(build_tokens.TokenError, "frost opacity"):
            build_tokens.build(data)
        data = json.loads(build_tokens.TOKENS.read_text())
        data["color"]["dark"]["surface"]["frostFallback"]["$value"] = "rgba(17,36,50,0.88)"
        with self.assertRaisesRegex(build_tokens.TokenError, "fallback must be solid"):
            build_tokens.build(data)

    def test_generator_refuses_a_colour_defined_for_one_theme(self):
        data = json.loads(build_tokens.TOKENS.read_text())
        self.assertEqual(build_tokens.one_theme_tokens(data), [])
        data["color"]["dark"]["status"]["onlyDark"] = {"$type": "color", "$value": "{color.primitive.red.300}"}
        self.assertEqual(build_tokens.one_theme_tokens(data), ["color.light.status.onlyDark"])
        for build in (build_tokens.build, build_tokens.build_chrome):
            with self.subTest(build=build.__name__), self.assertRaises(build_tokens.TokenError):
                build(data)

    def test_every_token_the_pages_use_exists_in_both_themes(self):
        css = build_tokens.OUTPUT.read_text()
        light = css[css.index(":root {") : css.index("@media (prefers-color-scheme: dark)")]
        dark = css[css.index('[data-theme="dark"] {') : css.index('[data-theme="light"] {')]
        defined_light = set(re.findall(r"(--nv-[\w-]+)\s*:", light))
        defined_dark = set(re.findall(r"(--nv-[\w-]+)\s*:", dark))
        sheets = [*sorted((ROOT / "browser" / "shell").rglob("*.css")), ROOT / "browser" / "startpage" / "startpage.css"]
        for sheet in sheets:
            used = set(re.findall(r"var\((--nv-[\w-]+)", sheet.read_text(encoding="utf-8")))
            with self.subTest(sheet=str(sheet.relative_to(ROOT))):
                self.assertEqual(used - defined_light, set(), "not defined in the light tokens")
                colours = {name for name in used if name.startswith("--nv-color-")}
                self.assertEqual(colours - defined_dark, set(), "colour not defined in the dark tokens")

    def test_secure_state_is_not_green(self):
        tokens = contrast.flatten(json.loads(contrast.TOKENS.read_text()))
        for theme in ("light", "dark"):
            secure = contrast.resolve(tokens, f"color.{theme}.status.secure")
            accent = contrast.resolve(tokens, f"color.{theme}.accent.default")
            self.assertNotEqual(secure, accent, "secure state must not rely on the mint/green accent")

    def test_known_contrast_values(self):
        self.assertAlmostEqual(contrast.ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(contrast.ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2)


class AssetsTest(unittest.TestCase):
    def test_icon_sizes_exist_with_exact_dimensions(self):
        for size in (16, 24, 32, 48, 64, 128, 256, 512):
            path = ASSETS / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "nulavio.png"
            with self.subTest(size=size):
                self.assertEqual(png_size(path), (size, size))
        for path in (
            ASSETS / "icons" / "hicolor" / "scalable" / "apps" / "nulavio.svg",
            ASSETS / "icons" / "hicolor" / "symbolic" / "apps" / "nulavio-symbolic.svg",
            ASSETS / "favicon" / "favicon.ico",
            ASSETS / "favicon" / "favicon.svg",
            ASSETS / "logo" / "nulavio-lockup-horizontal.svg",
            ASSETS / "logo" / "nulavio-mono-black.svg",
        ):
            self.assertTrue(path.is_file(), path)

    def test_svgs_are_static_and_self_contained(self):
        svgs = list(ASSETS.rglob("*.svg"))
        self.assertGreaterEqual(len(svgs), 15)
        for svg in svgs:
            with self.subTest(svg=svg.name):
                text = svg.read_text()
                ET.fromstring(text)  # well-formed
                self.assertNotRegex(text, r"<script|on\w+=|javascript:|<foreignObject|href=\"(https?:|//)|@import")
                root = ET.fromstring(text)
                self.assertEqual(root.tag, f"{SVG_NS}svg")
                self.assertIsNotNone(root.find(f"{SVG_NS}title"), "accessible <title> missing")

    def test_symbolic_icon_follows_desktop_colour(self):
        text = (ASSETS / "icons" / "hicolor" / "symbolic" / "apps" / "nulavio-symbolic.svg").read_text()
        self.assertIn("ColorScheme-Text", text)
        self.assertIn("currentColor", text)
        self.assertNotRegex(text, r"#6FE0C5|#0B1623")

    def test_logo_generator_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(build_logo, "ASSETS", Path(tmp)):
                build_logo.studies()
                build_logo.logo_family()
                build_logo.icon_masters()
            for generated in Path(tmp).rglob("*.svg"):
                committed = ASSETS / generated.relative_to(tmp)
                with self.subTest(svg=str(committed.relative_to(ROOT))):
                    self.assertEqual(generated.read_text(), committed.read_text(), "run scripts/brand/build_logo.py")


class DocsTest(unittest.TestCase):
    REQUIRED = (
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",  # OpenSSF Best Practices looks for it (release_notes)
        "CODE_OF_CONDUCT.md",
        "GOVERNANCE.md",
        "LICENSES.md",
        "LICENSE",
        "docs/adr/0001-engine-selection.md",
        "docs/product/vision.md",
        "docs/product/requirements.md",
        "docs/product/roadmap.md",
        "docs/product/release-criteria.md",
        "docs/architecture/overview.md",
        "docs/architecture/trust-boundaries.md",
        "docs/architecture/password-providers.md",
        "docs/architecture/extension-model.md",
        "docs/architecture/update-policy.md",
        "docs/architecture/build.md",
        "docs/security/threat-model.md",
        "docs/security/threat-matrix.md",
        "docs/security/hardening.md",
        "docs/security/residual-risks.md",
        "docs/security/assurance-case.md",
        "docs/brand/strategy.md",
        "docs/brand/explorations.md",
        "docs/brand/guidelines.md",
        "docs/brand/ux-flows.md",
        "docs/research/compatibility-matrix.md",
    )

    def test_required_documents_exist(self):
        missing = [p for p in self.REQUIRED if not (ROOT / p).is_file()]
        self.assertEqual(missing, [])

    def test_relative_links_resolve(self):
        broken = []
        for md in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text()):
                if re.match(r"^[a-z]+:", target):
                    continue
                if not (md.parent / target).resolve().exists():
                    broken.append(f"{md.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_adr_has_required_sections(self):
        text = (ROOT / "docs" / "adr" / "0001-engine-selection.md").read_text()
        for heading in ("Status", "Decision", "Evidence", "Risks", "Reversal criteria", "Open items"):
            self.assertRegex(text, rf"(?m)^(#+ .*|- \*\*){heading}", heading)

    def test_no_absolute_security_claims(self):
        pattern = re.compile(
            r"(?i)\b(100\s?% (secure|safe|protected|blocking)|unhackable|immune to|imunidade total|bloqueio 100)"
        )
        offenders = []
        for path in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")) + [ROOT / "browser/startpage/strings.json"]:
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                line = re.sub(r"~~.*?~~", "", line)  # struck-through = documented anti-example
                if (
                    pattern.search(line)
                    and "never claim" not in line.lower()
                    and "nunca" not in line.lower()
                    and "não" not in line.lower()
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
