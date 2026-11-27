"""Brand assets, design tokens and documentation hygiene."""

from __future__ import annotations

import json
import re
import subprocess
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
            (build_tokens.build_shield_ok, build_tokens.SHIELD_OK_OUTPUT),
            (build_tokens.build_shield_alert, build_tokens.SHIELD_ALERT_OUTPUT),
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

    def test_the_secure_status_illustration_is_neutral_not_mint(self):
        # #175 (finding 8): the Settings privacy status drew its "on guard" shield in the mint scale,
        # so mint read as "safe". It takes status.secure on status.secureTint, the same shape.
        tokens = contrast.flatten(json.loads(contrast.TOKENS.read_text()))
        mint = {contrast.resolve(tokens, f"color.primitive.mint.{s}").upper() for s in ("100", "200", "400", "700", "900")}
        shield = build_tokens.SHIELD_OK_OUTPUT.read_text()
        used = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", shield)}
        self.assertEqual(used & mint, set())
        for theme in ("light", "dark"):
            for name in ("secure", "secureTint"):
                self.assertIn(contrast.resolve(tokens, f"color.{theme}.status.{name}").upper(), used)
        alert = build_tokens.SHIELD_ALERT_OUTPUT.read_text()
        outline = 'd="M50 10 L84 22 V50 C84 72 70 88 50 96 C30 88 16 72 16 50 V22 Z"'
        self.assertIn(outline, shield)
        self.assertIn(outline, alert)
        checked = {(p["fg"], p["bg"]) for p in contrast.checked_pairs(json.loads(contrast.TOKENS.read_text()))}
        for theme in ("light", "dark"):
            self.assertIn((f"color.{theme}.status.secure", f"color.{theme}.status.secureTint"), checked)

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

    def test_android_adaptive_icon_is_generated_and_centred(self):
        # #175 (finding 6): the foreground was hand-written and 1.2 units off centre.
        text = build_logo.ANDROID_FOREGROUND.read_text()
        self.assertEqual(text, build_logo.android_foreground(), "run scripts/brand/build_logo.py")
        group = dict(re.findall(r'android:(\w+)="([^"]*)"', re.search(r"<group\b[^>]*>", text).group(0)))
        scale = float(group["scaleX"])
        self.assertEqual(scale, float(group["scaleY"]))
        px, py, tx, ty = (float(group[k]) for k in ("pivotX", "pivotY", "translateX", "translateY"))
        # The route's box on the 96 grid (x 25..71, y 21..75.1, stroke and points included), mapped as a
        # VectorDrawable group maps it: scaled about the pivot, then moved.
        box = [((x - px) * scale + px + tx, (y - py) * scale + py + ty) for x in (25, 71) for y in (21, 75.1)]
        centre = (sum(x for x, _ in box) / 4, sum(y for _, y in box) / 4)
        self.assertAlmostEqual(centre[0], 54, places=1)
        self.assertAlmostEqual(centre[1], 54, places=1)
        for x, y in box:  # every corner inside the 66-unit circle a launcher's mask always keeps
            self.assertLessEqual(((x - 54) ** 2 + (y - 54) ** 2) ** 0.5, build_logo.ANDROID_SAFE_RADIUS)
        background = (ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_background.xml").read_text()
        self.assertIn(f'android:color="{build_logo.NAVY}"', background)

    def test_no_lockup_shows_the_initial_twice(self):
        # #175, proposal A (chosen 2026-11-27): the route is the name's initial, then "ulavio".
        wordmark = build_logo.wordmark_paths()[0]
        lowercase_n = wordmark[: wordmark.index(" M41.0 ")]
        lockups = sorted((ASSETS / "logo").glob("nulavio-lockup-*.svg"))
        self.assertEqual(
            [p.name for p in lockups],
            [
                "nulavio-lockup-horizontal-mono-black.svg",
                "nulavio-lockup-horizontal-mono-white.svg",
                "nulavio-lockup-horizontal-on-dark.svg",
                "nulavio-lockup-horizontal.svg",
            ],
        )
        for path in lockups:
            text = path.read_text()
            with self.subTest(lockup=path.name):
                self.assertEqual(text.count(f'd="{build_logo.initial_route()}"'), 1)
                self.assertNotIn(lowercase_n, text)
                self.assertNotIn(f'd="{build_logo.ROUTE}"', text, "the symbol beside the name")
                self.assertIn(wordmark[len(lowercase_n) + 1 :], text, '"ulavio" follows the initial')

    def test_the_initial_keeps_the_symbols_trail(self):
        dots = build_logo.initial_dots()
        self.assertEqual(len(dots), len(build_logo.DOTS))
        radii = [r for _cx, _cy, r in dots]
        self.assertEqual(radii, sorted(radii, reverse=True), "the points shrink away from the stem")
        self.assertEqual(radii[0], build_logo.W_STROKE / 2, "the first point is as wide as the wordmark's stroke")
        self.assertGreater(dots[0][1] - radii[0], build_logo.A_STEM_END + build_logo.W_STROKE / 2, "clear of the stem's cap")

    def test_the_app_icon_draws_the_route_larger_and_the_small_masters_stay(self):
        scalable = (ASSETS / "icons" / "hicolor" / "scalable" / "apps" / "nulavio.svg").read_text()
        self.assertIn(f"scale({build_logo.n(build_logo.ICON_SCALE)})", scalable)
        self.assertAlmostEqual(46 * build_logo.ICON_SCALE / 96, 0.55, places=2)  # 55 % of the tile's width
        for path in (ASSETS / "favicon" / "favicon.svg", ASSETS / "logo" / "nulavio-tile.svg"):
            self.assertIn(f"scale({build_logo.n(build_logo.ICON_SCALE)})", path.read_text(), path.name)
        for size in (16, 24):  # hand-tuned, one point (guidelines §1)
            master = (ASSETS / "icons" / "masters" / f"nulavio-{size}.svg").read_text()
            self.assertEqual(master.count("<circle"), 1, size)
            self.assertNotIn("scale(", master, size)

    def test_about_dialog_name_is_the_lockup_with_an_adaptive_initial(self):
        sys.path.insert(0, str(ROOT / "scripts" / "build"))
        import make_branding

        text = make_branding.context_fill_wordmark()
        ET.fromstring(text)
        self.assertIn(f'd="{build_logo.initial_route()}" class="nv-mark"', text)
        self.assertIn('stroke="context-fill light-dark(#0B1623, #F1F7F5)"', text)  # the letters follow the chrome
        # The initial: Mint 700 by default, mint only where the scheme is dark (never mint on light).
        default, dark = text.split("@media (prefers-color-scheme: dark)")
        self.assertIn(build_logo.MINT_DARK, default)
        self.assertNotIn(build_logo.MINT, default)
        self.assertIn(build_logo.MINT, dark)

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
        # In a sparse checkout (agents' worktrees leave out docs/design/screenshots/: see
        # docs/process/pull-requests.md), a file git tracks but did not write to disk still resolves.
        # CI checks out everything, so there every target must exist on disk.
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-t", "-z"], capture_output=True, check=False)
        left_out = {name[2:] for name in listed.stdout.decode().split("\0") if name.startswith("S ")}
        broken = []
        for md in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text()):
                if re.match(r"^[a-z]+:", target):
                    continue
                path = (md.parent / target).resolve()
                if path.exists():
                    continue
                relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else None
                if relative and any(name == relative or name.startswith(relative + "/") for name in left_out):
                    continue
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
