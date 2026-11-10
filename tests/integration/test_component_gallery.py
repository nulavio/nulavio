"""UX2 production Shell CSS, rendered in Track B with disposable profiles.

Baselines deliberately exclude window chrome, profile state and remote fonts.
To propose new baselines: NULAVIO_UPDATE_GALLERY_BASELINES=1 (review PNGs).
Stock Firefox cannot prove built-in packaging; this suite follows Track B gates.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import contrast
import harness
import pngdiff

BASELINES = Path(__file__).resolve().parents[1] / "baselines" / "component-gallery"
LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
# Repeated captures in one pinned Linux engine are identical. Allow only small
# rasterisation drift, not structural changes; dimensions are separately exact.
MAX_MEAN = 0.1
MAX_CHANGED = 0.001


@unittest.skipUnless(harness.nulavio_engine(), "Track B built-in Shell gallery requires NULAVIO_ENGINE")
class ComponentGalleryTest(unittest.TestCase):
    @staticmethod
    def _exclude_sidebar_launcher(m, *, assert_initial_lateral=False):
        """Exclude window-chrome launcher width so SetWindowRect sets exact content innerWidth."""
        m.set_context("chrome")
        try:
            state = m.execute_async(
                f"const done = arguments[arguments.length - 1];"
                f"const checkInitial = arguments[0];"
                f"(async () => {{"
                f"  const initial = await {LAYOUT}.state(window);"
                f"  if (checkInitial && initial.preset !== 'lateral') {{"
                f"    done({{ error: 'expected initial lateral, got ' + initial.preset }});"
                f"    return;"
                f"  }}"
                f"  const applied = await {LAYOUT}.apply(window, 'top');"
                f"  SidebarController._state.updateVisibility(false, false);"
                f"  await SidebarController.waitUntilStable();"
                f"  document.documentElement.style.minWidth = '0px';"
                f"  done({{ applied: applied.preset, launcherVisible: SidebarController._state.launcherVisible }});"
                f"}})().catch(err => done({{ error: String(err) }}));",
                [assert_initial_lateral],
            )
        finally:
            m.set_context("content")
        assert state == {"applied": "top", "launcherVisible": False}, state

    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Gallery")
        cls.m = cls.session.start()
        cls._exclude_sidebar_launcher(cls.m, assert_initial_lateral=True)
        cls.artifacts = harness.artifacts_dir() / "component-gallery"
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        url = cls.m.chrome('return ChromeUtils.importESModule("resource:///modules/AboutNewTab.sys.mjs").AboutNewTab.newTabURL;')
        cls.url = url.rsplit("/newtab/", 1)[0] + "/dev/gallery/index.html"

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def open_gallery(self):
        self.m.navigate(self.url)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement?.dataset.ready === 'true';"), timeout=15),
            "gallery localisation did not complete",
        )

    def pin_states(self):
        """Lock real production pseudo-classes, without gallery-only state CSS."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                """
                const done = arguments[arguments.length - 1];
                const mm = gBrowser.selectedBrowser.messageManager;
                const topic = 'nv-gallery:pinned';
                const listener = msg => { mm.removeMessageListener(topic, listener); done(msg.data); };
                mm.addMessageListener(topic, listener);
                const code = `
                  const doc = content.document;
                  const states = [['sample-hover', ':hover'], ['sample-focus', ':focus-visible'],
                    ['sample-active', ':active'], ['sample-danger-active', ':active']];
                  for (const [id, state] of states) {
                    InspectorUtils.addPseudoClassLock(doc.getElementById(id), state);
                  }
                  sendAsyncMessage('nv-gallery:pinned', true);
                `;
                mm.loadFrameScript('data:,' + encodeURIComponent(code), false);
                """
            )
        finally:
            self.m.set_context("content")

    def test_gallery_matrix_and_baselines(self):
        measurements = []
        for width in (1280, 390):
            self.m.send("WebDriver:SetWindowRect", {"width": width, "height": 1000})
            for theme in ("light", "dark"):
                with self.subTest(width=width, theme=theme):
                    self.open_gallery()
                    self.m.execute("document.documentElement.dataset.theme = arguments[0];", [theme])
                    self.assertTrue(self.pin_states())
                    self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
                    time.sleep(0.3)
                    state = self.m.execute("""
                        const css = s => getComputedStyle(document.querySelector(s));
                        return {width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
                          primary: css('.button--primary').borderRadius, secondary: css('.button--secondary').borderRadius,
                          focus: css('#sample-focus').outlineStyle, focusWidth: css('#sample-focus').outlineWidth,
                          hover: css('#sample-hover').boxShadow, active: css('#sample-active').boxShadow,
                          invalid: css('[aria-invalid]').borderTopWidth,
                          critical: css('.callout--critical').borderRadius,
                          opaque: css('.callout--critical').opacity,
                          animated: getComputedStyle(document.querySelector('.status[data-level="progress"]'),
                            '::before').animationName,
                          safeFirst: document.querySelector('.dialog .button').classList.contains('button--primary'),
                          inert: [...document.querySelectorAll('button, input, select')].every(e => e.closest('[inert]'))};
                    """)
                    self.assertEqual(state["width"], width, state)
                    self.assertFalse(state["overflow"], state)
                    self.assertEqual(state["primary"], state["secondary"], state)
                    self.assertEqual(state["primary"], "10px", state)
                    self.assertEqual(state["critical"], "4px", state)
                    self.assertEqual(state["focus"], "solid", state)
                    self.assertGreaterEqual(float(state["focusWidth"].removesuffix("px")), 2)
                    self.assertNotEqual(state["hover"], "none", state)
                    self.assertNotEqual(state["active"], "none", state)
                    self.assertEqual(state["invalid"], "2px")
                    self.assertEqual(state["opaque"], "1", state)
                    self.assertEqual(state["animated"], "none", state)
                    self.assertTrue(state["safeFirst"] and state["inert"], state)
                    # Measure actual composited pixels, including the inset overlay, not only background-color.
                    state["primaryContrast"] = {}
                    for sample in ("sample-hover", "sample-active", "sample-danger-active"):
                        foreground = self.m.execute(
                            "const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');"
                            "ctx.fillStyle = getComputedStyle(document.getElementById(arguments[0])).color;"
                            "ctx.fillRect(0,0,1,1); return Array.from(ctx.getImageData(0,0,1,1).data);",
                            [sample],
                        )
                        _, _, bpp, rows = pngdiff.decode(self.m.screenshot_png(element=self.m.find_element(f"#{sample}")))
                        background = (*rows[8][8 * bpp : 8 * bpp + 3], 1)
                        value = contrast.ratio((*foreground[:3], 1), background)
                        state["primaryContrast"][sample] = value
                        self.assertGreaterEqual(value, 4.5, f"{sample} in {theme} has insufficient rendered text contrast")
                    capture = self.m.screenshot_png(full=True)
                    name = f"gallery-{width}-{theme}.png"
                    (self.artifacts / name).write_bytes(capture)
                    repeated = self.m.screenshot_png(full=True)
                    stability = pngdiff.difference(capture, repeated, step=1)
                    self.assertEqual(stability, {"mean": 0.0, "changed": 0.0})
                    baseline = BASELINES / name
                    if os.environ.get("NULAVIO_UPDATE_GALLERY_BASELINES") == "1":
                        BASELINES.mkdir(parents=True, exist_ok=True)
                        baseline.write_bytes(capture)
                    self.assertTrue(baseline.exists(), f"Missing reviewed baseline: {baseline}")
                    expected = baseline.read_bytes()
                    self.assertEqual(pngdiff.decode(expected)[:2], pngdiff.decode(capture)[:2])
                    delta = pngdiff.difference(expected, capture, step=1)
                    self.assertLessEqual(delta["mean"], MAX_MEAN, delta)
                    self.assertLessEqual(delta["changed"], MAX_CHANGED, delta)
                    # A local crop prevents a missing security glyph from being diluted
                    # by the rest of the page, especially on the dark narrow surface.
                    critical = self.m.find_element(".callout--critical")
                    region = self.m.screenshot_png(element=critical)
                    region_name = f"critical-{width}-{theme}.png"
                    (self.artifacts / region_name).write_bytes(region)
                    region_baseline = BASELINES / region_name
                    if os.environ.get("NULAVIO_UPDATE_GALLERY_BASELINES") == "1":
                        region_baseline.write_bytes(region)
                    self.assertTrue(region_baseline.exists(), str(region_baseline))
                    expected_region = region_baseline.read_bytes()
                    self.assertEqual(pngdiff.decode(expected_region)[:2], pngdiff.decode(region)[:2])
                    region_delta = pngdiff.difference(expected_region, region, step=1)
                    self.assertLessEqual(region_delta["mean"], MAX_MEAN, region_delta)
                    self.assertLessEqual(region_delta["changed"], MAX_CHANGED, region_delta)
                    self.m.execute("document.querySelector('.callout--critical .callout__icon').style.visibility = 'hidden';")
                    missing_icon = pngdiff.difference(expected_region, self.m.screenshot_png(element=critical), step=1)
                    self.assertTrue(missing_icon["mean"] > MAX_MEAN or missing_icon["changed"] > MAX_CHANGED, missing_icon)
                    self.m.execute("document.querySelector('.callout--critical .callout__icon').style.visibility = ''; ")
                    # A missing critical signal must be caught by the same image oracle.
                    self.m.execute("document.querySelector('.callout--critical').style.visibility = 'hidden';")
                    negative = pngdiff.difference(expected, self.m.screenshot_png(full=True), step=1)
                    self.assertTrue(negative["mean"] > MAX_MEAN or negative["changed"] > MAX_CHANGED, negative)
                    measurements.append(
                        {
                            "name": name,
                            **state,
                            "stability": stability,
                            "delta": delta,
                            "negative": negative,
                            "missing_icon": missing_icon,
                        }
                    )
        (self.artifacts / "measurements.json").write_text(json.dumps(measurements, indent=2) + "\n")

    def test_narrow_font_scaling_and_contrast_modes(self):
        self.m.send("WebDriver:SetWindowRect", {"width": 390, "height": 1000})
        self.open_gallery()
        self.m.execute("document.documentElement.style.fontSize = '200%';")
        for width in (320, 390):
            self.m.send("WebDriver:SetWindowRect", {"width": width, "height": 1000})
            self.assertEqual(self.m.execute("return innerWidth;"), width)
            self.assertFalse(self.m.execute("return document.documentElement.scrollWidth > innerWidth;"))
        self.m.chrome("Services.prefs.setIntPref('ui.useAccessibilityTheme', 1);")
        self.m = type(self).m = self.session.restart()
        self._exclude_sidebar_launcher(self.m, assert_initial_lateral=False)
        self.m.send("WebDriver:SetWindowRect", {"width": 390, "height": 1000})
        self.open_gallery()
        self.m.execute("document.documentElement.style.fontSize = '200%';")
        self.assertTrue(self.m.execute("return matchMedia('(prefers-contrast: more)').matches;"))
        self.assertTrue(self.pin_states())
        self.assertGreaterEqual(
            float(
                self.m.execute("return getComputedStyle(document.getElementById('sample-focus')).outlineWidth;").removesuffix(
                    "px"
                )
            ),
            3,
        )
        self.m.chrome("Services.prefs.setIntPref('browser.display.document_color_use', 2);")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return matchMedia('(forced-colors: active)').matches;")))
        self.assertEqual(
            self.m.execute("return getComputedStyle(document.querySelector('input[role=switch]')).appearance;"), "auto"
        )
        (self.artifacts / "gallery-forced-colors-200percent.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.chrome(
            "Services.prefs.clearUserPref('ui.useAccessibilityTheme');"
            "Services.prefs.clearUserPref('browser.display.document_color_use');"
        )


if __name__ == "__main__":
    unittest.main()
