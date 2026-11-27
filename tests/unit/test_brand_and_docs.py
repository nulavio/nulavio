"""Brand assets, design tokens and documentation hygiene."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
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


# Colours and near-colours that the status illustrations do not take, because they write #RRGGBB only.
NOT_WRITTEN_AS_HEX = (
    "rgba(226, 235, 238, 1)",
    "rgba(226,\x0b235, 238, 1)",
    "rgba(\u0662\u0662\u0666, 235, 238, 1)",
    "rgba(226., 235, 238, 1)",
    "rgba(226, 235, 238, 0.5)",
    "#E2EBEE\n",
    "#E2EBEEFF",
    "#\uff25\uff12EBEE",
)


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

    def test_the_status_illustrations_refuse_a_value_that_is_not_a_colour(self):
        # The value goes into the SVG as it is: one the engine cannot read would leave the shield without
        # its outline or its mark, and the generator would still succeed. Only #RRGGBB is taken: the
        # rgba() form contrast.py reads allows a vertical tab (not XML), digits outside ASCII and "226."
        # (not CSS), and every one of the spellings below is a colour to contrast.rgba.
        for value in NOT_WRITTEN_AS_HEX[:4]:
            self.assertEqual(contrast.rgba(value), (226.0, 235.0, 238.0, 1.0), value)
        cases = (
            (build_tokens.build_shield_ok, "secure"),
            (build_tokens.build_shield_ok, "secureTint"),
            (build_tokens.build_shield_alert, "warning"),
            (build_tokens.build_shield_alert, "warningTint"),
        )
        for build, name in cases:
            for theme in ("light", "dark"):
                for value in ("#GGGGGG", "#ABC", "navy", 5, None, "", *NOT_WRITTEN_AS_HEX):
                    data = json.loads(build_tokens.TOKENS.read_text())
                    data["color"][theme]["status"][name]["$value"] = value
                    refused = self.assertRaisesRegex(build_tokens.TokenError, rf"color\.{theme}\.status\.{name}")
                    with self.subTest(build=build.__name__, theme=theme, name=name, value=value), refused:
                        build(data)
        data = json.loads(build_tokens.TOKENS.read_text())
        data["color"]["light"]["status"]["secure"]["$value"] = "#123abc"
        self.assertIn("stroke: #123ABC;", build_tokens.build_shield_ok(data))

    def test_known_contrast_values(self):
        self.assertAlmostEqual(contrast.ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(contrast.ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2)


class DatedReviewTest(unittest.TestCase):
    """docs/brand/review-2026-11.md is the record of 2026-11-20. Its sheets and tables were made from that
    day's brand; scripts/brand/build_review.py now reads the applied one."""

    def test_the_sheets_and_tables_are_not_made_again_from_the_applied_brand(self):
        import build_review

        for flag in ("--render", "--report"):
            # The functions that write and print are replaced: a missing refusal fails here instead of
            # rendering over the committed sheets.
            with self.subTest(flag=flag), contextlib.ExitStack() as stack:
                names = ("render", "write_proposals", "mark_report")
                replaced = [stack.enter_context(mock.patch.object(build_review, name)) for name in names]
                stack.enter_context(mock.patch.object(sys, "argv", ["build_review.py", flag]))
                said = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                with self.assertRaises(SystemExit) as stopped:
                    build_review.main()
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn("532ef2d0", said.getvalue())  # where they can still be made
                for function in replaced:
                    function.assert_not_called()

    def test_the_proposals_stay_as_drawn(self):
        import build_review

        # The files are the record; the generator reads A's geometry from build_logo.py, the applied brand.
        # The day that changes on purpose this fails, and the files are not what gives way.
        stale = (
            "the proposal files are the review's record and are not made again: give build_review.py the "
            "value it drew them with on 2026-11-27 instead of build_logo.py's new one"
        )
        committed = sorted(p.name for p in (build_review.OUT / "proposals").glob("*.svg"))
        generated = build_review.proposal_svgs()
        self.assertEqual(committed, sorted(generated))
        for name, text in generated.items():
            with self.subTest(svg=name):
                self.assertEqual((build_review.OUT / "proposals" / name).read_text(encoding="utf-8"), text, stale)
                self.assertIn("a proposal, not an approved asset", text)

    def test_writing_the_proposals_touches_nothing_else(self):
        import build_review

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_review, "OUT", Path(tmp) / "review"):
            written = build_review.write_proposals()
            self.assertEqual({p.parent for p in written}, {Path(tmp) / "review" / "proposals"})
            self.assertEqual(sorted(p.name for p in Path(tmp).rglob("*") if p.is_file()), sorted(p.name for p in written))

    def test_a_proposal_drawn_differently_is_never_replaced(self):
        import build_review

        def files(folder: Path) -> dict[str, str]:
            return {p.name: p.read_text(encoding="utf-8") for p in folder.iterdir()}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_review, "OUT", Path(tmp) / "review"):
            proposals = Path(tmp) / "review" / "proposals"
            build_review.write_proposals()
            as_reviewed = files(proposals)
            # The applied lockup's spacing and the icon's scale change, as a later revision of the brand may
            # (ROUTE_SCALE is build_logo.ICON_SCALE as this script read it when it was loaded).
            self.assertEqual(build_review.ROUTE_SCALE, build_logo.ICON_SCALE)
            with mock.patch.object(build_logo, "A_GAP", 21.0), mock.patch.object(build_review, "ROUTE_SCALE", 1.3):
                moved = build_review.proposal_svgs()
                self.assertNotEqual(moved["a-lockup-initial.svg"], as_reviewed["a-lockup-initial.svg"])
                self.assertNotEqual(moved["ab-icon.svg"], as_reviewed["ab-icon.svg"])
                (proposals / "c-icon.svg").unlink()  # a missing file is not written either, once one is refused
                with self.assertRaisesRegex(ValueError, "a-lockup-initial-on-dark.svg, a-lockup-initial.svg, ab-icon.svg"):
                    build_review.write_proposals()
                self.assertEqual(files(proposals), {k: v for k, v in as_reviewed.items() if k != "c-icon.svg"})
                with mock.patch.object(sys, "argv", ["build_review.py"]), contextlib.redirect_stderr(io.StringIO()) as said:
                    self.assertEqual(build_review.main(), 1)
                self.assertIn("stay as they were shown", said.getvalue())
            build_review.write_proposals()  # with the brand as it was, the missing file comes back
            self.assertEqual(files(proposals), as_reviewed)

    def test_a_proposal_that_is_there_is_not_written_again(self):
        import build_review

        # A run with every file there and as drawn opened each one for writing and listed it as written.
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_review, "OUT", Path(tmp) / "review"):
            proposals = Path(tmp) / "review" / "proposals"
            first = build_review.write_proposals()
            self.assertEqual(sorted(p.name for p in first), sorted(build_review.proposal_svgs()))
            (proposals / "c-icon.svg").unlink()
            for path in proposals.iterdir():
                path.chmod(0o444)  # the record, read-only: a file opened for writing would fail here
                os.utime(path, ns=(1, 1))
            self.assertEqual(build_review.write_proposals(), [proposals / "c-icon.svg"])  # only the missing one
            self.assertEqual(
                [p.name for p in proposals.iterdir() if p.stat().st_mtime_ns != 1], ["c-icon.svg"]
            )  # and no other was touched
            self.assertEqual(build_review.write_proposals(), [])

    def test_every_mark_pair_meets_its_minimum(self):
        import build_review

        # What the marks need of the palette that was kept: 3:1 for a graphic (WCAG 1.4.11), 4.5:1 for the name.
        self.assertEqual(sorted({minimum for _what, _fg, _bg, minimum in build_review.MARK_PAIRS}), [3.0, 4.5])
        self.assertEqual(len(build_review.MARK_PAIRS), 9)
        for what, fg, bg, minimum in build_review.MARK_PAIRS:
            with self.subTest(pair=what):
                self.assertGreaterEqual(contrast.ratio(fg, bg), minimum)


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

    def test_readme_status_names_the_published_release_and_its_systems(self):
        # #857: the status names packaging/release.json's version (release_metadata.py keeps it there), and Ubuntu's
        # steps check the sources file the site serves.
        release = json.loads((ROOT / "packaging" / "release.json").read_text(encoding="utf-8"))
        tag = f"v{release['version']}"
        link = f"<!--release-->[{tag}](https://github.com/nulavio/nulavio/releases/tag/{tag})<!--/release-->"
        digest = hashlib.sha256((ROOT / "site" / "apt" / "nulavio.sources").read_bytes()).hexdigest()
        for readme, ubuntu in (("README.md", "On Ubuntu 24.04 or later"), ("README.pt-BR.md", "No Ubuntu 24.04 ou mais novo")):
            with self.subTest(readme=readme):
                text = (ROOT / readme).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"<!--release-->.*?<!--/release-->", text), [link])
                self.assertIsNotNone(release.get("apt_sources"))
                self.assertIn(ubuntu, text)
                # The checksum gates the install when the block is pasted whole (OCR on #878).
                self.assertIn(
                    f"curl -fsSLO --proto '=https' {release['apt_sources']} &&\n"
                    f"  echo '{digest}  nulavio.sources' | sha256sum --check &&\n"
                    "  sudo install -m 0644 nulavio.sources /etc/apt/sources.list.d/ &&\n",
                    text,
                )
                # A test count goes stale with the next test; the README names none.
                self.assertNotRegex(text, r"\b\d+ (tests|testes)\b")

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
