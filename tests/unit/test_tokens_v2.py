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
