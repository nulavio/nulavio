"""Token generation and compositing contracts, using disposable in-memory fixtures."""

import unittest

import build_tokens
import contrast


class ThemeGenerationTest(unittest.TestCase):
    def test_shadow_switches_without_color_function(self):
        data = {
            "elevation": {
                t: {"1": {"$type": "shadow", "$value": v}}
                for t, v in (("light", "0 1px 2px #000000"), ("dark", "0 2px 4px #000000"))
            }
        }
        page = build_tokens.build(data)
        chrome = build_tokens.build_chrome(data)
        for css in (page, chrome):
            self.assertIn("--nv-elevation-1: 0 1px 2px #000000", css)
            self.assertIn("--nv-elevation-1: 0 2px 4px #000000", css)
            self.assertNotIn("light-dark(0", css)
        del data["elevation"]["dark"]["1"]
        with self.assertRaisesRegex(ValueError, "elevation.dark.1"):
            build_tokens.build(data)


class CompositeContrastTest(unittest.TestCase):
    def fixture(self):
        return {
            "fg": {"$value": "#000000"},
            "surface": {"$value": "rgba(255,255,255,0.5)"},
            "backdrop": {"$value": "#000000"},
            "$extensions": {"nulavio.contrast": [{"fg": "fg", "bg": "surface", "backdrops": ["backdrop"], "min": 4.5}]},
        }

    def test_half_white_over_black_uses_srgb_composite_before_luminance(self):
        row = contrast.check(self.fixture())[0]
        # 127.5 in each sRGB channel; independent WCAG result (no 8-bit rounding).
        self.assertAlmostEqual(row[4], 5.2808228096, places=8)
        self.assertTrue(row[-1])
        self.assertIn("backdrop", row[1])

    def test_missing_backdrop_and_malformed_alpha_are_rejected(self):
        for value in ("rgba(255,255,255,2)", "rgba(255,255,255,nan)", "rgba(256,0,0,0.5)"):
            data = self.fixture()
            data["surface"]["$value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                contrast.check(data)
        data = self.fixture()
        del data["backdrop"]
        with self.assertRaisesRegex(ValueError, "backdrop"):
            contrast.check(data)

    def test_below_minimum_is_a_failure(self):
        data = self.fixture()
        data["surface"]["$value"] = "rgba(255,255,255,0.1)"
        self.assertFalse(contrast.check(data)[0][-1])


class TokenValidationTest(unittest.TestCase):
    def test_invalid_and_cyclic_aliases_include_the_reference(self):
        for value, error in (("{missing}", "missing"), ("{a}", "cycle.*a"), ("prefix {a}", "invalid alias.*a")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, error):
                build_tokens.build({"a": {"$value": value}})

    def test_long_acyclic_chain_is_valid(self):
        data = {str(i): {"$value": "{" + str(i + 1) + "}"} for i in range(20)}
        data["20"] = {"$value": "1rem"}
        self.assertIn("--nv-0: 1rem", build_tokens.build(data))

    def test_all_themed_generators_reject_missing_non_color_counterpart(self):
        data = {"size": {"light": {"body": {"$type": "dimension", "$value": "1rem"}}}}
        for generate in (
            build_tokens.build,
            build_tokens.build_chrome,
            build_tokens.build_identity,
            build_tokens.build_sidebar_focus,
        ):
            with self.subTest(generate=generate.__name__), self.assertRaisesRegex(ValueError, "size.dark.body"):
                generate(data)

    def test_explicit_opacity_and_translucent_foreground_composite(self):
        data = CompositeContrastTest().fixture()
        data["surface"]["$value"] = "#FFFFFF"
        data["$extensions"]["nulavio.contrast"][0]["opacity"] = 0.5
        self.assertAlmostEqual(contrast.check(data)[0][4], 5.2808228096, places=8)
        data["fg"]["$value"] = "rgba(0,0,0,0.5)"
        # Gray 63.75 on gray 127.5, calculated independently in sRGB/WCAG.
        self.assertAlmostEqual(contrast.check(data)[0][4], 2.6174799724, places=8)

    def test_invalid_pairs_fail_closed(self):
        for patch in (
            {"fg": "missing"},
            {"bg": "missing"},
            {"min": float("nan")},
            {"min": 0},
            {"opacity": -1},
            {"opacity": True},
            {"opacity": "missing"},
            {"backdrops": []},
            {"backdrops": [None]},
            {"backdrops": ["missing"]},
            {"typo": 1},
        ):
            data = CompositeContrastTest().fixture()
            data["$extensions"]["nulavio.contrast"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                contrast.check(data)
        data = CompositeContrastTest().fixture()
        del data["$extensions"]["nulavio.contrast"][0]["backdrops"]
        with self.assertRaisesRegex(ValueError, "backdrop"):
            contrast.check(data)

    def test_report_preserves_exact_composite_channels_and_every_backdrop(self):
        data = CompositeContrastTest().fixture()
        data["white"] = {"$value": "#FFFFFF"}
        data["$extensions"]["nulavio.contrast"][0]["backdrops"].append("white")
        rows = contrast.checked_pairs(data)
        self.assertEqual([r["backdrop"] for r in rows], ["backdrop", "white"])
        self.assertEqual(rows[0]["backgroundRGBA"], (127.5, 127.5, 127.5, 1.0))
        self.assertEqual(rows[1]["backgroundRGBA"], (255.0, 255.0, 255.0, 1.0))
        self.assertEqual(rows[1]["ratio"], 21.0)


class AppearanceVariantTest(unittest.TestCase):
    """UX6: the accent and "Mais contraste" variants, checked over the real tokens."""

    @classmethod
    def setUpClass(cls):
        import json

        cls.data = json.loads(contrast.TOKENS.read_text(encoding="utf-8"))
        cls.specs = build_tokens.variant_specs(cls.data)

    def fixture(self, dimension, name, tokens):
        data = contrast.with_overrides(self.data, {})
        data["$extensions"]["nulavio.variants"][dimension]["values"][name] = {"prefValue": name, "tokens": tokens}
        return data

    def test_the_declared_variants(self):
        self.assertEqual(set(self.specs), {"accent", "contrast"})
        self.assertEqual(set(self.specs["accent"]["values"]), {"blue"})
        self.assertEqual(set(self.specs["contrast"]["values"]), {"more"})
        self.assertEqual(self.specs["accent"]["pref"], "nulavio.appearance.accent")
        self.assertEqual(self.specs["contrast"]["pref"], "nulavio.appearance.moreContrast")

    def test_every_variant_combination_passes_every_pair(self):
        base = contrast.checked_pairs(self.data)
        rows = contrast.variant_rows(self.data)
        combos = contrast.variant_combinations(self.data)
        self.assertEqual(len(combos), 4)
        self.assertEqual(len(rows), len(combos) * len(base))
        self.assertEqual([(r["variant"], r["fg"], r["bg"], round(r["ratio"], 2)) for r in rows if not r["pass"]], [])

    def test_variants_never_reach_protected_tokens(self):
        build_tokens.validate_variants(self.data)
        for spec in self.specs.values():
            for name, value in spec["values"].items():
                changed = build_tokens.changed_paths(self.data, value["tokens"])
                with self.subTest(variant=name):
                    self.assertTrue(changed)
                    self.assertEqual([p for p in changed if build_tokens.is_protected(p)], [])
                    for path in changed:
                        self.assertNotRegex(path, r"\.(security|status|focus|identity\w*|group|fullscreen|band|downloads)\.")
                        self.assertNotIn(".chrome.private.", path)

    def test_security_and_private_tokens_look_the_same_and_never_follow_a_variant(self):
        tokens = contrast.flatten(self.data)
        r = lambda path: contrast.resolve(tokens, path)  # noqa: E731
        # Re-pointed to primitives with the values they had through the accent (no visual change).
        for theme in ("light", "dark"):
            self.assertEqual(r(f"color.{theme}.security.acting.edge"), r(f"color.{theme}.accent.default"))
            self.assertEqual(r(f"color.{theme}.security.acting.fill"), r(f"color.{theme}.accent.tint"))
            self.assertEqual(r(f"color.{theme}.chrome.private.accent"), r("color.dark.accent.default"))
        for _labels, overrides in contrast.variant_combinations(self.data):
            after = contrast.flatten(contrast.with_overrides(self.data, overrides))
            for path in tokens:
                if ".security." in path or ".chrome.private." in path:
                    self.assertEqual(contrast.resolve(after, path), r(path), path)

    def test_accents_stay_as_distinct_as_mint(self):
        choices = [{}] + [v["tokens"] for v in self.specs["accent"]["values"].values()]
        for tokens in choices:
            for theme, nearest, distance in contrast.accent_separation(contrast.with_overrides(self.data, tokens)):
                with self.subTest(theme=theme, nearest=nearest):
                    self.assertGreaterEqual(distance, build_tokens.SEPARATION_MIN)

    def test_more_contrast_reaches_7_for_text_and_3_for_borders(self):
        more = contrast.flatten(contrast.with_overrides(self.data, self.specs["contrast"]["values"]["more"]["tokens"]))
        r = lambda path: contrast.resolve(more, path)  # noqa: E731
        for theme in ("light", "dark"):
            for surface in ("canvas", "surface", "raised", "sunken"):
                bg = r(f"color.{theme}.bg.{surface}")
                for text in ("primary", "secondary", "muted"):
                    self.assertGreaterEqual(contrast.ratio(r(f"color.{theme}.text.{text}"), bg), 7, (theme, surface, text))
                for border in ("subtle", "separator", "control"):
                    self.assertGreaterEqual(contrast.ratio(r(f"color.{theme}.border.{border}"), bg), 3, (theme, surface, border))
            self.assertEqual(contrast.rgba(r(f"color.{theme}.surface.frost"))[3], 1, "frost is solid under more contrast")

    def test_variant_generation_fails_closed(self):
        bad = {
            "protected": (
                "accent",
                "x",
                {"color.light.security.acting.fill": "#000000", "color.dark.security.acting.fill": "#000000"},
            ),
            "one theme": ("accent", "x", {"color.light.accent.default": "#2D64B5"}),
            "too close": (
                "accent",
                "x",
                {
                    "color.light.accent.default": "{color.light.identity.sky}",
                    "color.dark.accent.default": "{color.dark.identity.sky}",
                },
            ),
            "both dimensions": ("contrast", "x", {"color.light.accent.tint": "#FFFFFF", "color.dark.accent.tint": "#000000"}),
            "primitive": ("accent", "x", {"color.primitive.mint.700": "#000000"}),
        }
        for case, (dimension, name, tokens) in bad.items():
            with self.subTest(case=case), self.assertRaises(build_tokens.TokenError):
                build_tokens.validate_variants(self.fixture(dimension, name, tokens))

    def test_the_window_and_about_pages_follow_the_pref_and_the_private_page_does_not(self):
        chrome = build_tokens.build_chrome(self.data)
        self.assertIn('@media -moz-pref("nulavio.appearance.accent", "blue")', chrome)
        self.assertIn('@media -moz-pref("nulavio.appearance.moreContrast")', chrome)
        about = build_tokens.build_in_content(self.data)
        self.assertIn('-moz-pref("nulavio.appearance.accent", "blue")', about)
        self.assertEqual(about.count(":root:not([lwtheme], .private)"), 3)
        page = build_tokens.build(self.data)
        self.assertIn(':root[data-accent="blue"]', page)
        self.assertIn(':root[data-contrast="more"]', page)
