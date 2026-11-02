"""UX3D / UX3E: explicit layout presets, safe D-UX2 Lateral adoption and first-run choice."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import harness
from contrast import ratio
from test_horizon import rgb
from test_horizon_groups import KEY
from test_profiles import chrome_async
from test_window_band import BAND_PROBE, assert_band, assert_layout_matrix

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
# A build of the previous release (5a98bd7) for the real upgrade check, from NULAVIO_REFERENCE_ENGINE.


@unittest.skipUnless(harness.nulavio_engine(), "layout presets need the built-in Shell on Gecko159")
class LayoutPresetsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Layout")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        locale = os.environ.get("NULAVIO_LAYOUT_LOCALE")
        if locale:
            self.m.chrome("Services.locale.requestedLocales = [arguments[0]];", [locale])
            self.m = self.session.restart()
            self.assertEqual(self.m.chrome("return Services.locale.appLocaleAsBCP47;"), locale)
        self.artifacts = harness.artifacts_dir() / "layout-presets"
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def state(self):
        result = chrome_async(self.m, f"return {LAYOUT}.state(window);")
        self.assertNotIn("error", result, result)
        return result["ok"]

    def apply(self, preset):
        result = chrome_async(self.m, f"return {LAYOUT}.apply(window,args[0]);", [preset])
        self.assertNotIn("error", result, result)
        self.assertEqual(result["ok"]["preset"], preset, result)
        return result["ok"]

    def shell_url(self, rel=""):
        base = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        return base + rel

    def settings(self):
        self.m.navigate(self.shell_url("settings/settings.html#layout"))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready==='true';"), 15))

    def newtab(self):
        self.m.navigate(self.shell_url("newtab/newtab.html"))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready==='true';"), 15))

    def selected(self):
        return self.m.execute("return document.querySelector('#layout input:checked')?.value || 'custom';")

    def ui_ready(self, preset):
        return self.m.execute(
            """
          return document.getElementById('layout-choices').getAttribute('aria-busy') !== 'true'
            && !document.querySelector('#layout input').disabled
            && (document.querySelector('#layout input:checked')?.value || 'custom') === arguments[0];
        """,
            [preset],
        )

    def newtab_ui_ready(self, preset):
        return self.m.execute(
            """
          const card = document.getElementById('layout-choice');
          return !card.hidden
            && document.getElementById('layout-choice-options').getAttribute('aria-busy') !== 'true'
            && !document.querySelector('#layout-choice input').disabled
            && (document.querySelector('#layout-choice input:checked')?.value || 'custom') === arguments[0];
        """,
            [preset],
        )

    def open_secondary_window(self, private=False):
        options = "{private:true}" if private else ""
        result = chrome_async(
            self.m,
            f"""
          const w=OpenBrowserWindow({options});
          await new Promise(resolve=>{{const obs=subject=>{{if(subject===w) {{
            Services.obs.removeObserver(obs,'browser-delayed-startup-finished');resolve();
          }}}};Services.obs.addObserver(obs,'browser-delayed-startup-finished');}});
          return String(w.browsingContext.id);
        """,
        )
        self.assertNotIn("error", result, result)
        target_id = result["ok"]

        def find_handle():
            for handle in self.m.window_handles():
                self.m.switch_to(handle)
                if self.m.chrome("return String(window.browsingContext.id)===arguments[0];", [target_id]):
                    return handle
            return None

        handle = harness.wait_until(find_handle, 15)
        self.assertTrue(handle, result)
        return handle, target_id

    def capture(self, name):
        self.m.set_context("chrome")
        try:
            (self.artifacts / f"{name}.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.set_context("content")

    def test_explicit_presets_move_real_tabs_and_survive_restart(self):
        measured = []
        for preset in ("lateral", "top", "focus"):
            with self.subTest(preset=preset):
                self.apply(preset)
                native = self.m.chrome("""
                  const s=SidebarController.getUIState(), tabs=gBrowser.tabContainer;
                  const r=tabs.getBoundingClientRect();
                  return {orientation:tabs.getAttribute('orient'),parent:tabs.parentElement.id,
                    expanded:s.launcherExpanded,visible:s.launcherVisible,w:r.width,h:r.height,
                    hover:document.documentElement.hasAttribute('sidebar-expand-on-hover')};
                """)
                self.assertEqual(native["orientation"], "horizontal" if preset == "top" else "vertical")
                self.assertGreater(native["w"], 0)
                self.assertGreater(native["h"], 0)
                self.assertEqual(native["expanded"], preset == "lateral")
                self.assertEqual(native["hover"], preset == "focus")
                self.m = self.session.restart()
                self.assertEqual(self.state()["preset"], preset)
                measured.append({"preset": preset, "native": native, "afterRestart": self.state()})
        (self.artifacts / "restart.json").write_text(json.dumps(measured, indent=2) + "\n")

    def test_native_controls_and_per_window_state_are_observed_and_cleanup_is_idempotent(self):
        self.apply("lateral")
        self.settings()
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        second, _ = self.open_secondary_window()
        self.m.switch_to(second)
        self.settings()
        self.assertEqual(self.selected(), "lateral")
        self.m.chrome("SidebarController.handleToolbarButtonClick();")
        self.assertTrue(harness.wait_until(lambda: self.selected() == "custom", 10))
        self.m.switch_to(first)
        self.assertEqual(self.selected(), "lateral")
        # Explicit choice applies to the profile's open windows, even when the
        # two pref values already match and would emit no preference change.
        self.apply("lateral")
        self.m.switch_to(second)
        self.assertTrue(harness.wait_until(lambda: self.selected() == "lateral", 10))
        self.m.chrome("SidebarController.toggleVerticalTabs();")
        self.assertTrue(harness.wait_until(lambda: self.selected() == "top", 10))
        self.m.switch_to(first)
        self.assertTrue(harness.wait_until(lambda: self.selected() == "top", 10))
        result = chrome_async(
            self.m,
            f"""
          window.nvLayoutEvents = 0;
          const off={LAYOUT}.subscribe(window,()=>window.nvLayoutEvents++);
          Services.prefs.setStringPref('sidebar.visibility','hide-launcher');
          await new Promise(resolve=>setTimeout(resolve,100));
          const count=window.nvLayoutEvents;
          off(); off();
          Services.prefs.setStringPref('sidebar.visibility','hide-on-close');
          await new Promise(resolve=>setTimeout(resolve,100));
          return {{count,after:window.nvLayoutEvents}};
        """,
        )
        self.assertGreater(result["ok"]["count"], 0)
        self.assertEqual(result["ok"]["count"], result["ok"]["after"])
        # Removing a Settings document removes its privileged EventManager subscription.
        self.m.navigate("about:blank")
        self.m.switch_to(second)
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(first)
        self.apply("focus")

    def test_refusals_preserve_preferences_and_the_queue_recovers(self):
        for value in ("custom", "__proto__", "constructor", "sidebar.revamp", None, {}):
            result = chrome_async(self.m, f"return {LAYOUT}.apply(window,args[0]);", [value])
            self.assertEqual(result, {"error": "layout-invalid"})
        self.apply("top")
        self.settings()
        # P3-4(a): cover all three watched sidebar prefs, including sidebar.revamp.
        for pref in ("sidebar.verticalTabs", "sidebar.visibility", "sidebar.revamp"):
            with self.subTest(locked_pref=pref):
                self.m.chrome("Services.prefs.lockPref(arguments[0]);", [pref])
                try:
                    result = chrome_async(self.m, f"return {LAYOUT}.apply(window,'focus');")
                    self.assertEqual(result, {"error": "layout-locked"})
                    st = self.state()
                    self.assertTrue(st["locked"])
                    self.assertFalse(st["choicePending"])
                    self.m.navigate("about:blank")
                    self.settings()
                    self.assertTrue(
                        harness.wait_until(
                            lambda: self.m.execute(
                                "return document.getElementById('layout-choices').getAttribute('aria-busy') !== 'true'"
                                " && [...document.querySelectorAll('#layout input')].every(e => e.disabled)"
                                " && Boolean(document.getElementById('layout-current').textContent.trim());"
                            ),
                            10,
                        )
                    )
                finally:
                    self.m.chrome("Services.prefs.unlockPref(arguments[0]);", [pref])
                self.m.navigate("about:blank")
                self.settings()
                self.assertTrue(harness.wait_until(lambda: self.ui_ready("top"), 10))
        self.assertEqual(self.state()["preset"], "top")
        self.m.chrome("Services.prefs.setBoolPref('sidebar.revamp',false);")
        self.assertFalse(self.state()["available"])
        self.assertEqual(chrome_async(self.m, f"return {LAYOUT}.apply(window,'focus');"), {"error": "layout-unavailable"})
        self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('sidebar.revamp');"))
        self.m.chrome("Services.prefs.setBoolPref('sidebar.revamp',true);")
        self.apply("focus")
        self.assertEqual(chrome_async(self.m, f"return {LAYOUT}.state(null);"), {"error": "layout-unavailable"})
        # P3-4(b): real secondary browser window closing inside apply's window loop.
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        _second, second_ctx = self.open_secondary_window()
        self.m.switch_to(first)
        closing_mid_apply = chrome_async(
            self.m,
            f"""
          const L={LAYOUT};
          const w2=[...Services.wm.getEnumerator('navigator:browser')].find(
            w=>String(w.browsingContext.id)===args[0]
          );
          const origWait=w2.SidebarController.waitUntilStable.bind(w2.SidebarController);
          let calls=0;
          w2.SidebarController.waitUntilStable=async()=>{{
            calls++;
            await origWait();
            // First call is pre-flight ready(w2); second call is inside apply's window loop.
            if (calls===2) {{
              w2.close();
            }}
          }};
          let code=null;
          try {{
            await L.apply(window,'lateral');
          }} catch(e) {{
            code=e.code;
          }}
          return {{code,calls,w2Closed:w2.closed}};
        """,
            [second_ctx],
        )
        self.assertNotIn("error", closing_mid_apply, closing_mid_apply)
        self.assertEqual(closing_mid_apply["ok"]["code"], "layout-failed", closing_mid_apply)
        self.assertGreaterEqual(closing_mid_apply["ok"]["calls"], 2, closing_mid_apply)
        self.assertTrue(closing_mid_apply["ok"]["w2Closed"], closing_mid_apply)
        # Queue recovers cleanly on the surviving window.
        self.apply("top")
        partial = chrome_async(
            self.m,
            f"""
          const L={LAYOUT}, original=L.state;
          L.state=()=>{{throw new Error('final-state-read fixture');}};
          let code;
          try {{ await L.apply(window,'lateral'); }} catch(e) {{code=e.code;}}
          finally {{L.state=original;}}
          return {{code,actual:await L.state(window)}};
        """,
        )
        self.assertEqual(partial["ok"]["code"], "layout-failed")
        self.assertEqual(partial["ok"]["actual"]["preset"], "lateral")
        self.apply("top")

    def test_preserves_position_width_tools_bookmarks_density_and_assistant(self):
        self.apply("lateral")
        self.m.chrome("""
          Services.prefs.setBoolPref('sidebar.position_start',false);
          Services.prefs.setIntPref('browser.uidensity',1);
          Services.prefs.setStringPref('browser.toolbars.bookmarks.visibility','always');
          Services.prefs.setStringPref('sidebar.main.tools','bookmarks,history,passwords');
          Services.prefs.setBoolPref('sidebar.expandOnHover',false);
          SidebarController._state.expandedLauncherWidth=264;
        """)
        opened = chrome_async(
            self.m,
            """
          await SidebarController.show('shell_nulavio_net-sidebar-action');
          return {command:SidebarController.currentID,expanded:SidebarController.getUIState().launcherExpanded};
        """,
        )
        self.assertTrue(opened["ok"]["expanded"])  # D-UX22
        for preset in ("focus", "top", "lateral"):
            self.apply(preset)
            native = self.m.chrome("""
              return {position:Services.prefs.getBoolPref('sidebar.position_start'),
                density:Services.prefs.getIntPref('browser.uidensity'),
                bookmarks:Services.prefs.getStringPref('browser.toolbars.bookmarks.visibility'),
                tools:Services.prefs.getStringPref('sidebar.main.tools'),
                hoverGate:Services.prefs.getBoolPref('sidebar.expandOnHover'),
                expandedWidth:SidebarController.getUIState().expandedLauncherWidth,
                panel:SidebarController.currentID,open:SidebarController.isOpen};
            """)
            self.assertEqual(
                native,
                {
                    "position": False,
                    "density": 1,
                    "bookmarks": "always",
                    "tools": "bookmarks,history,passwords",
                    "hoverGate": False,
                    "expandedWidth": 264,
                    "panel": "shell_nulavio_net-sidebar-action",
                    "open": True,
                },
            )
        self.assertTrue(self.m.chrome("return SidebarController.getUIState().launcherExpanded;"))

    def test_profile_preferences_do_not_cross_independent_profiles(self):
        self.apply("focus")
        self.assertFalse(self.state()["choicePending"])
        other = harness.GeckoProfileSession(name="Independent")
        self.addCleanup(other.cleanup)
        m = other.start()
        other_state = chrome_async(m, f"return {LAYOUT}.state(window);")["ok"]
        self.assertEqual(
            other_state,
            {"preset": "lateral", "available": True, "locked": False, "choicePending": True},
        )
        self.assertEqual(m.chrome("return Services.prefs.getIntPref('nulavio.layout.adoptionVersion', 0);"), 1)
        self.assertTrue(m.chrome("return Services.prefs.getBoolPref('sidebar.verticalTabs');"))
        self.assertEqual(self.state()["preset"], "focus")
        self.assertFalse(self.state()["choicePending"])

    def test_settings_keyboard_native_focus_and_error_recovery(self):
        self.settings()
        # D-UX2: a brand-new profile begins in Lateral with first-run choice pending.
        self.assertEqual(self.selected(), "lateral")
        self.assertTrue(self.state()["choicePending"])
        self.assertTrue(self.m.execute("return !!document.querySelector('#layout-choices legend').textContent;"))
        for preset in ("top", "focus", "lateral", "top"):
            radio = self.m.find_element(f'#layout input[value="{preset}"]')
            self.m.send("WebDriver:ElementClick", {"id": radio})
            self.assertTrue(harness.wait_until(lambda want=preset: self.ui_ready(want), 10))
            st = self.state()
            self.assertEqual(st["preset"], preset)
            self.assertFalse(st["choicePending"])
        # A trusted native arrow event changes a radio and the actual tab layout.
        self.m.execute("document.querySelector('#layout input[value=top]').focus();")
        self.m.chrome(KEY, ["ArrowDown", "ArrowDown", 40])
        self.assertTrue(harness.wait_until(lambda: self.state()["preset"] == "focus", 10))
        self.assertTrue(harness.wait_until(lambda: self.ui_ready("focus"), 10))
        self.assertTrue(self.m.execute("return document.activeElement.matches('#layout input[value=focus]');"))
        focus = self.m.execute("""
          const e=document.activeElement,s=getComputedStyle(e);
          return {style:s.outlineStyle,width:s.outlineWidth,color:s.outlineColor,
            bg:getComputedStyle(e.closest('.card')).backgroundColor};
        """)
        self.assertEqual(focus["style"], "solid", focus)
        self.assertGreaterEqual(float(focus["width"].removesuffix("px")), 2)
        self.assertGreaterEqual(ratio(rgb(focus["color"]), rgb(focus["bg"])), 3)
        # Foco retains the native keyboard route to the expanded tab list.
        self.m.chrome("ToolbarKeyboardNavigator._focusButton(SidebarController.toolbarButton);")
        self.assertTrue(self.m.chrome("return document.activeElement===SidebarController.toolbarButton;"))
        self.m.chrome(KEY, ["Enter", "Enter", 13])
        self.assertTrue(harness.wait_until(lambda: self.state()["preset"] == "custom", 10))
        self.assertTrue(self.m.chrome("return SidebarController.getUIState().launcherExpanded;"))
        self.assertTrue(harness.wait_until(lambda: self.selected() == "custom", 10))
        self.m.chrome(KEY, ["Enter", "Enter", 13])
        self.assertTrue(harness.wait_until(lambda: self.selected() == "focus", 10))
        self.m.chrome("Services.focus.setFocus(gBrowser.selectedTab,Ci.nsIFocusManager.FLAG_BYKEY);")
        self.assertTrue(self.m.chrome("return document.activeElement===gBrowser.selectedTab;"))
        # Inject a bridge-side operation failure; the UI must reread actual
        # state and never claim no change or a successful preset.
        self.m.chrome(f"window.nvLayoutApply={LAYOUT}.apply; {LAYOUT}.apply=()=>{{throw new Error('fixture');}};")
        try:
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#layout input[value=top]")})
            self.assertTrue(
                harness.wait_until(
                    lambda: bool(self.m.execute("return document.getElementById('layout-error').textContent;")), 10
                )
            )
            self.assertEqual(self.state()["preset"], "focus")
            self.assertTrue(harness.wait_until(lambda: self.ui_ready("focus"), 10))
        finally:
            self.m.chrome(f"{LAYOUT}.apply=window.nvLayoutApply; delete window.nvLayoutApply;")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#layout input[value=top]")})
        self.assertTrue(harness.wait_until(lambda: self.selected() == "top", 10))
        self.m.chrome(f"window.nvLayoutState={LAYOUT}.state; {LAYOUT}.state=()=>{{throw new Error('read fixture');}};")
        try:
            self.m.navigate("about:blank")
            self.settings()
            self.assertFalse(self.m.execute("return document.getElementById('layout-retry').hidden;"))
            self.assertTrue(self.m.execute("return [...document.querySelectorAll('#layout input')].every(e=>e.disabled);"))
        finally:
            self.m.chrome(f"{LAYOUT}.state=window.nvLayoutState;delete window.nvLayoutState;")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#layout-retry")})
        self.assertTrue(harness.wait_until(lambda: self.ui_ready("top"), 10))
        self.m.navigate("about:blank")
        self.apply("lateral")
        self.m.send("WebDriver:Back")
        self.assertTrue(harness.wait_until(lambda: self.ui_ready("lateral"), 10))
        self.apply("focus")
        self.assertTrue(harness.wait_until(lambda: self.ui_ready("focus"), 10))

    def test_focus_real_pointer_hover_and_custom_state_restore(self):
        self.apply("focus")
        self.settings()
        rect = self.m.chrome("""
          const r=SidebarController.sidebarContainer.getBoundingClientRect();
          return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
        """)
        self.m.set_context("chrome")
        self.m.send(
            "WebDriver:PerformActions",
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "layout-mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": [
                            {"type": "pointerMove", "origin": "viewport", "x": rect["x"], "y": rect["y"], "duration": 100}
                        ],
                    }
                ]
            },
        )
        self.m.set_context("content")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return SidebarController.getUIState().launcherExpanded;"), 10))
        self.assertEqual(self.state()["preset"], "focus")
        self.assertEqual(self.selected(), "focus")
        self.m.set_context("chrome")
        self.m.send("WebDriver:ReleaseActions")
        self.m.set_context("content")
        # P3-4(c): opening a second window after applying Foco starts collapsed with
        # sidebar-expand-on-hover active and expands on real pointer hover.
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        second, _ = self.open_secondary_window()
        try:
            self.m.switch_to(second)
            second_init = self.m.chrome("""
              const s=SidebarController.getUIState();
              return {hover:document.documentElement.hasAttribute('sidebar-expand-on-hover'),
                visible:s.launcherVisible,expanded:s.launcherExpanded,
                orient:gBrowser.tabContainer.getAttribute('orient')};
            """)
            self.assertEqual(
                second_init,
                {"hover": True, "visible": True, "expanded": False, "orient": "vertical"},
            )
            self.assertEqual(self.state()["preset"], "focus")
            rect2 = self.m.chrome("""
              const r=SidebarController.sidebarContainer.getBoundingClientRect();
              return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
            """)
            self.m.set_context("chrome")
            self.m.send(
                "WebDriver:PerformActions",
                {
                    "actions": [
                        {
                            "type": "pointer",
                            "id": "layout-mouse-2",
                            "parameters": {"pointerType": "mouse"},
                            "actions": [
                                {"type": "pointerMove", "origin": "viewport", "x": rect2["x"], "y": rect2["y"], "duration": 100}
                            ],
                        }
                    ]
                },
            )
            self.m.set_context("content")
            self.assertTrue(
                harness.wait_until(lambda: self.m.chrome("return SidebarController.getUIState().launcherExpanded;"), 10)
            )
            self.assertEqual(self.state()["preset"], "focus")
            self.m.set_context("chrome")
            self.m.send("WebDriver:ReleaseActions")
            self.m.set_context("content")
        finally:
            self.m.switch_to(second)
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(first)
        self.apply("lateral")
        self.assertNotIn("error", chrome_async(self.m, "await SidebarController.handleToolbarButtonClick();"))
        self.assertEqual(self.state()["preset"], "custom")
        self.m = self.session.restart()
        self.assertEqual(self.state()["preset"], "custom")
        self.settings()
        self.assertEqual(self.selected(), "custom")

    def test_settings_reflow_200_percent_themes_and_accessibility_preferences(self):
        self.settings()
        self.m.chrome("document.documentElement.style.minWidth='0px';")
        measured = []
        for preset in ("lateral", "top", "focus"):
            self.apply(preset)
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);", [dark])
                for width, font in ((1366, "100%"), (390, "100%"), (320, "200%")):
                    # Target the Settings viewport. A 320px *outer window*
                    # with expanded vertical tabs leaves only ~79px for content.
                    sidebar_width = self.m.chrome("return innerWidth-gBrowser.selectedBrowser.getBoundingClientRect().width;")
                    outer = width if width == 1366 else round(width + sidebar_width)
                    self.m.send("WebDriver:SetWindowRect", {"width": outer, "height": 900})
                    # Native sidebar max-widths can change after the resize.
                    # Converge on the requested content width, then assert it.
                    if width != 1366:
                        for _ in range(3):
                            time.sleep(0.2)
                            actual = self.m.execute("return innerWidth;")
                            if actual == width:
                                break
                            outer += width - actual
                            self.m.send("WebDriver:SetWindowRect", {"width": outer, "height": 900})
                    self.m.execute(
                        "document.documentElement.style.fontSize=arguments[0];document.getElementById('layout').scrollIntoView();",
                        [font],
                    )
                    time.sleep(0.2)
                    probe = self.m.execute("""
                      const section=document.getElementById('layout'),r=section.getBoundingClientRect();
                      return {viewport:innerWidth,w:r.width,scroll:section.scrollWidth,
                        rootScroll:document.documentElement.scrollWidth,
                        font:getComputedStyle(document.documentElement).fontSize,
                        labels:[...section.querySelectorAll('label')].map(e=>({w:e.clientWidth,scroll:e.scrollWidth,h:e.clientHeight}))};
                    """)
                    if width != 1366:
                        self.assertEqual(probe["viewport"], width, probe)
                    self.assertLessEqual(probe["scroll"], probe["w"] + 1, probe)
                    for label in probe["labels"]:
                        self.assertLessEqual(label["scroll"], label["w"] + 1, probe)
                        self.assertGreaterEqual(label["h"], 24, probe)
                    measured.append({"preset": preset, "dark": dark, "requestedWidth": width, "font": font, **probe})
                    self.capture(f"settings-{preset}-{'dark' if dark else 'light'}-{width}-{font.removesuffix('%')}")
                    if font == "200%":
                        name = f"section-{preset}-{'dark' if dark else 'light'}-{width}-{font.removesuffix('%')}.png"
                        (self.artifacts / name).write_bytes(self.m.screenshot_png(element=self.m.find_element("#layout")))
        self.m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 900})
        self.m.execute("document.documentElement.style.fontSize='100%';")
        for pref in ("ui.prefersReducedMotion", "ui.prefersReducedTransparency", "ui.useAccessibilityTheme"):
            self.m.chrome("Services.prefs.setIntPref(arguments[0],1);", [pref])
        self.m = self.session.restart()
        self.settings()
        self.apply("focus")
        self.assertTrue(self.m.execute("return matchMedia('(prefers-reduced-motion: reduce)').matches;"))
        native_media = self.m.chrome("""
          return {motion:matchMedia('(prefers-reduced-motion: reduce)').matches,
            contrast:matchMedia('(prefers-contrast: more)').matches,
            transparency:matchMedia('(prefers-reduced-transparency: reduce)').matches};
        """)
        self.assertTrue(all(native_media.values()), native_media)
        self.capture("settings-accessibility-preferences")
        (self.artifacts / "accessibility-media.json").write_text(json.dumps(native_media, indent=2) + "\n")
        (self.artifacts / "reflow.json").write_text(json.dumps(measured, indent=2) + "\n")

    def test_private_and_fullscreen_security_matrix(self):
        # Brand-new profile still has choicePending=true in normal windows; a private
        # window loading newtab must report choicePending=false and hide #layout-choice.
        self.assertTrue(self.state()["choicePending"])
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        _, _ = self.open_secondary_window(private=True)
        self.assertTrue(self.m.chrome("return PrivateBrowsingUtils.isWindowPrivate(window);"))
        self.assertFalse(self.state()["choicePending"])
        self.newtab()
        self.assertTrue(self.m.execute("return document.getElementById('layout-choice').hidden;"))
        assert_layout_matrix(self, self.m, "private")
        self.assertTrue(self.m.chrome("return document.querySelector('#nulavio-band .nv-band-row').dataset.private==='true';"))
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(first)
        rows = []
        for preset in ("lateral", "top", "focus"):
            self.apply(preset)
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);window.fullScreen=true;", [dark])
                self.assertTrue(
                    harness.wait_until(lambda: self.m.chrome("return document.documentElement.hasAttribute('inFullscreen');"), 10)
                )
                time.sleep(0.25)
                assert_band(self, self.m.chrome(f"return {BAND_PROBE};"))
                time.sleep(4.3)  # existing native safety-notice interval; no deadline changed
                line = self.m.chrome("""
                  const host=document.getElementById('nulavio-fullscreen'),e=host.querySelector('.nv-fullscreen-line');
                  const r=e.getBoundingClientRect(),s=getComputedStyle(e),hit=document.elementFromPoint(r.x+10,r.y+r.height/2);
                  return {notice:host.hasAttribute('notice'),h:r.height,w:r.width,opacity:s.opacity,hit:e.contains(hit)};
                """)
                self.assertFalse(line["notice"], line)
                self.assertEqual(line["h"], 3)
                self.assertEqual(line["opacity"], "1")
                self.assertTrue(line["hit"], line)
                self.capture(f"fullscreen-{preset}-{'dark' if dark else 'light'}")
                rows.append({"preset": preset, "dark": dark, **line})
                self.m.chrome("window.fullScreen=false;")
        (self.artifacts / "fullscreen.json").write_text(json.dumps(rows, indent=2) + "\n")

    def test_reading_settings_does_not_change_native_preferences(self):
        before = self.m.chrome("""
          return Object.fromEntries(Services.prefs.getChildList('sidebar.').map(k =>
            [k, [Services.prefs.getPrefType(k), Services.prefs.prefHasUserValue(k),
              Services.prefs.getPrefType(k) === 128 ? Services.prefs.getBoolPref(k) :
              Services.prefs.getPrefType(k) === 64 ? Services.prefs.getIntPref(k) : Services.prefs.getStringPref(k)]]));
        """)
        result = chrome_async(self.m, f"return {LAYOUT}.state(window);")
        self.assertNotIn("error", result, result)
        self.assertEqual(
            result["ok"],
            {"preset": "lateral", "available": True, "locked": False, "choicePending": True},
        )
        self.settings()
        after = self.m.chrome(
            """
          return Object.fromEntries(Object.keys(arguments[0]).map(k =>
            [k, [Services.prefs.getPrefType(k), Services.prefs.prefHasUserValue(k),
              Services.prefs.getPrefType(k) === 128 ? Services.prefs.getBoolPref(k) :
              Services.prefs.getPrefType(k) === 64 ? Services.prefs.getIntPref(k) : Services.prefs.getStringPref(k)]]));
        """,
            [before],
        )
        self.assertEqual(before, after)
        self.assertTrue(self.state()["choicePending"])

    def test_listener_registration_error_renders_retry_and_recovers(self):
        # P3-1: if api.onChanged.addListener throws on Settings or Newtab, the UI
        # must render unavailable + Retry instead of hanging on loading text.
        for page, card_sel, current_id, error_id, retry_id, radio_sel in (
            ("settings/settings.html#layout", "#layout", "layout-current", "layout-error", "layout-retry", "#layout input"),
            (
                "newtab/newtab.html",
                "#layout-choice",
                "layout-choice-current",
                "layout-choice-error",
                "layout-choice-retry",
                "#layout-choice input",
            ),
        ):
            with self.subTest(page=page):
                self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.choicePending', true);")
                self.m.navigate(self.shell_url(page))
                self.assertTrue(
                    harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready==='true';"), 15)
                )
                # Navigate away so pagehide detaches, wrap onChanged.addListener to throw once
                # on bfcache restore (pageshow persisted) AND also verify fresh setUpLayout/showLayoutChoice.
                probe = self.m.execute(
                    """
                  const [cardSel, currentId, errorId, retryId, radioSel] = arguments;
                  const api = browser.nulavioLayout;
                  const origAdd = api.onChanged.addListener.bind(api.onChanged);
                  let threw = false;
                  api.onChanged.addListener = fn => {
                    if (!threw) {
                      threw = true;
                      const err = new Error('layout-unavailable');
                      throw err;
                    }
                    return origAdd(fn);
                  };
                  window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
                  window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
                  return {
                    threw,
                    cardHidden: document.querySelector(cardSel).hidden,
                    current: document.getElementById(currentId).textContent,
                    error: document.getElementById(errorId).textContent,
                    retryHidden: document.getElementById(retryId).hidden,
                    allDisabled: [...document.querySelectorAll(radioSel)].every(e => e.disabled),
                  };
                """,
                    [card_sel, current_id, error_id, retry_id, radio_sel],
                )
                # In newtab, listen() awaits state() on throw before surfacing; wait briefly for that microtask.
                self.assertTrue(
                    harness.wait_until(
                        lambda rid=retry_id: not self.m.execute("return document.getElementById(arguments[0]).hidden;", [rid]),
                        10,
                    ),
                    probe,
                )
                rendered = self.m.execute(
                    """
                  const [cardSel, currentId, errorId, retryId, radioSel] = arguments;
                  return {
                    cardHidden: document.querySelector(cardSel).hidden,
                    current: document.getElementById(currentId).textContent,
                    error: document.getElementById(errorId).textContent,
                    retryHidden: document.getElementById(retryId).hidden,
                    allDisabled: [...document.querySelectorAll(radioSel)].every(e => e.disabled),
                  };
                """,
                    [card_sel, current_id, error_id, retry_id, radio_sel],
                )
                self.assertFalse(rendered["cardHidden"], rendered)
                self.assertTrue(bool(rendered["current"]), rendered)
                self.assertTrue(bool(rendered["error"]), rendered)
                self.assertFalse(rendered["retryHidden"], rendered)
                self.assertTrue(rendered["allDisabled"], rendered)
                # Clicking Retry re-subscribes and restores interactive Lateral state + live updates.
                self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"#{retry_id}")})
                self.assertTrue(
                    harness.wait_until(
                        lambda rsel=radio_sel, rid=retry_id: self.m.execute(
                            """
                          return document.getElementById(arguments[1]).hidden
                            && ![...document.querySelectorAll(arguments[0])].some(e => e.disabled)
                            && document.querySelector(arguments[0] + ':checked')?.value === 'lateral';
                        """,
                            [rsel, rid],
                        ),
                        10,
                    )
                )

    def test_moving_tab_between_windows_rebinds_layout_state_apply_and_onchanged(self):
        # P3-2: moving Settings and Newtab tabs to another window via adoptTab
        # (SwapDocShells -> EndSwapDocShells) updates state, apply and onChanged
        # to the new host window and survives closing the original window.
        self.apply("lateral")
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.choicePending', true);")
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.settings()
        self.assertEqual(self.selected(), "lateral")
        # Open a second tab in Window 1 with newtab.html so both surfaces are tested across window swap.
        newtab_url = self.shell_url("newtab/newtab.html")
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [newtab_url])
        newtab_handle = harness.wait_until(
            lambda: next(
                (
                    h
                    for h in self.m.window_handles()
                    if h != first and (self.m.switch_to(h) or True) and self.m.execute("return location.href;") == newtab_url
                ),
                None,
            ),
            15,
        )
        self.assertTrue(newtab_handle)
        self.m.switch_to(newtab_handle)
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("lateral"), 15))

        second, second_ctx = self.open_secondary_window()
        self.m.switch_to(second)
        # Collapse Window 2's launcher so Window 2 is Custom while Window 1 stays Lateral.
        self.m.chrome("SidebarController.handleToolbarButtonClick();")
        self.assertEqual(self.state()["preset"], "custom")

        # Move both tabs from Window 1 into Window 2 via native gBrowser.adoptTab.
        moved = chrome_async(
            self.m,
            """
          const w2 = window;
          const w1 = [...Services.wm.getEnumerator('navigator:browser')].find(w => w !== w2);
          // Give w1 a spare blank tab so adopting both Shell tabs does not auto-close w1 yet.
          w1.gBrowser.addTrustedTab('about:blank');
          const toMove = w1.gBrowser.tabs.filter(t => t.linkedBrowser.currentURI.spec.startsWith(args[0]));
          for (const tab of toMove) {
            w2.gBrowser.adoptTab(tab, { selectTab: true });
          }
          return { movedCount: toMove.length, w1Closed: w1.closed };
        """,
            [self.shell_url("")],
        )
        self.assertNotIn("error", moved, moved)
        self.assertEqual(moved["ok"]["movedCount"], 2, moved)
        self.assertFalse(moved["ok"]["w1Closed"], moved)

        # Find the adopted Settings and Newtab handles now hosted in Window 2.
        def handle_for(suffix):
            for h in self.m.window_handles():
                self.m.switch_to(h)
                if self.m.chrome("return String(window.browsingContext.id)===arguments[0];", [second_ctx]) and self.m.execute(
                    "return location.href;"
                ).endswith(suffix):
                    return h
            return None

        moved_settings = harness.wait_until(lambda: handle_for("settings/settings.html#layout"), 10)
        moved_newtab = harness.wait_until(lambda: handle_for("newtab/newtab.html"), 10)
        self.assertTrue(moved_settings and moved_newtab)

        self.m.switch_to(moved_settings)
        self.assertTrue(harness.wait_until(lambda: self.selected() == "custom", 10))
        self.m.switch_to(moved_newtab)
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("custom"), 10))

        # Now close Window 1 completely: subscriptions on the moved tabs must stay alive!
        closed_w1 = chrome_async(
            self.m,
            """
          const w2 = window;
          const w1 = [...Services.wm.getEnumerator('navigator:browser')].find(w => w !== w2);
          w1.close();
          await new Promise(resolve => setTimeout(resolve, 250));
          return w1.closed;
        """,
        )
        self.assertTrue(closed_w1["ok"], closed_w1)

        # Toggling Window 2's sidebar back open emits onChanged on Window 2 to both moved tabs.
        self.m.chrome("SidebarController.handleToolbarButtonClick();")
        self.m.switch_to(moved_settings)
        self.assertTrue(harness.wait_until(lambda: self.selected() == "lateral", 10))
        self.m.switch_to(moved_newtab)
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("lateral"), 10))

        # Applying Foco from the moved Settings tab acts on Window 2 and updates Newtab.
        self.m.switch_to(moved_settings)
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#layout input[value=focus]")})
        self.assertTrue(harness.wait_until(lambda: self.ui_ready("focus"), 10))
        self.assertEqual(self.state()["preset"], "focus")

    def test_first_run_newtab_choice_keyboard_sync_persistence_and_reflow(self):
        # D-UX2: brand-new profile begins in Lateral with honest, non-blocking first-run choice.
        st = self.state()
        self.assertEqual(st, {"preset": "lateral", "available": True, "locked": False, "choicePending": True})
        self.assertEqual(self.m.chrome("return gBrowser.tabContainer.getAttribute('orient');"), "vertical")
        self.assertTrue(self.m.chrome("return SidebarController.getUIState().launcherExpanded;"))

        # Open two Newtab tabs to prove live cross-tab synchronization.
        first_tab = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.newtab()
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("lateral"), 10))
        newtab_url = self.shell_url("newtab/newtab.html")
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [newtab_url])
        second_tab = harness.wait_until(
            lambda: next((h for h in self.m.window_handles() if h != first_tab), None),
            10,
        )
        self.assertTrue(second_tab)
        self.m.switch_to(second_tab)
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("lateral"), 10))

        # Verify localized button label matches Lateral ("Manter Lateral" / "Keep Lateral").
        locale = self.m.chrome("return Services.locale.appLocaleAsBCP47;")
        expected_keep_lateral = "Keep Lateral" if locale.startswith("en") else "Manter Lateral"
        expected_keep_focus = "Keep Focus" if locale.startswith("en") else "Manter Foco"
        self.assertEqual(
            self.m.execute("return document.getElementById('layout-choice-done').textContent.trim();"),
            expected_keep_lateral,
        )

        # Keyboard arrowing on the active Newtab changes real window chrome immediately
        # without collapsing #layout-choice mid-navigation, while hiding it in other tabs!
        self.m.execute("document.querySelector('#layout-choice input[value=lateral]').focus();")
        ring = self.m.execute("""
          const e=document.activeElement,s=getComputedStyle(e);
          return {style:s.outlineStyle,width:s.outlineWidth,color:s.outlineColor,
            bg:getComputedStyle(e.closest('.card')).backgroundColor};
        """)
        self.assertEqual(ring["style"], "solid", ring)
        self.assertGreaterEqual(float(ring["width"].removesuffix("px")), 2)
        self.assertGreaterEqual(ratio(rgb(ring["color"]), rgb(ring["bg"])), 3)

        self.m.chrome(KEY, ["ArrowDown", "ArrowDown", 40])
        self.assertTrue(harness.wait_until(lambda: self.state()["preset"] == "top", 10))
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("top"), 10))
        self.assertEqual(self.m.chrome("return gBrowser.tabContainer.getAttribute('orient');"), "horizontal")
        self.assertFalse(self.state()["choicePending"])
        self.assertTrue(self.m.execute("return document.activeElement.matches('#layout-choice input[value=top]');"))
        # Background Newtab already hid #layout-choice via onChanged because choicePending is now false.
        self.m.switch_to(first_tab)
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.getElementById('layout-choice').hidden;"), 10))

        # Continue keyboard navigation in the active tab to Foco, inspect 320px @ 200% reflow, then confirm.
        self.m.switch_to(second_tab)
        self.m.execute("document.querySelector('#layout-choice input[value=top]').focus();")
        self.m.chrome(KEY, ["ArrowDown", "ArrowDown", 40])
        self.assertTrue(harness.wait_until(lambda: self.state()["preset"] == "focus", 10))
        self.assertTrue(harness.wait_until(lambda: self.newtab_ui_ready("focus"), 10))
        self.assertEqual(
            self.m.execute("return document.getElementById('layout-choice-done').textContent.trim();"),
            expected_keep_focus,
        )

        # Check WCAG 1.4.10 reflow (320px @ 200%) & light/dark themes on #layout-choice before dismissing.
        self.m.chrome("document.documentElement.style.minWidth='0px';")
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            sidebar_w = self.m.chrome("return innerWidth - gBrowser.selectedBrowser.getBoundingClientRect().width;")
            outer = round(320 + sidebar_w)
            self.m.send("WebDriver:SetWindowRect", {"width": outer, "height": 900})
            for _ in range(3):
                time.sleep(0.2)
                actual = self.m.execute("return innerWidth;")
                if actual == 320:
                    break
                outer += 320 - actual
                self.m.send("WebDriver:SetWindowRect", {"width": outer, "height": 900})
            self.m.execute(
                "document.documentElement.style.fontSize='200%'; document.getElementById('layout-choice').scrollIntoView();"
            )
            time.sleep(0.2)
            reflow = self.m.execute("""
              const card=document.getElementById('layout-choice'), r=card.getBoundingClientRect();
              const done=document.getElementById('layout-choice-done').getBoundingClientRect();
              return {viewport:innerWidth, w:r.width, scroll:card.scrollWidth, doneH:done.height,
                labels:[...card.querySelectorAll('label')].map(e=>({w:e.clientWidth,scroll:e.scrollWidth,h:e.clientHeight}))};
            """)
            self.assertEqual(reflow["viewport"], 320, reflow)
            self.assertLessEqual(reflow["scroll"], reflow["w"] + 1, reflow)
            self.assertGreaterEqual(reflow["doneH"], 24, reflow)
            for lbl in reflow["labels"]:
                self.assertLessEqual(lbl["scroll"], lbl["w"] + 1, reflow)
                self.assertGreaterEqual(lbl["h"], 24, reflow)
        self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")
        self.m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 900})
        self.m.execute("document.documentElement.style.fontSize='100%';")

        # Confirm via #layout-choice-done with keyboard focus inside the card -> focus moves to #search-input.
        self.m.execute("document.getElementById('layout-choice-done').focus();")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#layout-choice-done")})
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.getElementById('layout-choice').hidden;"), 10))
        self.assertEqual(self.m.execute("return document.activeElement?.id;"), "search-input")

        # Restart browser: Foco persists and first-run choice stays dismissed.
        self.m = self.session.restart()
        self.assertEqual(self.state(), {"preset": "focus", "available": True, "locked": False, "choicePending": False})
        self.newtab()
        self.assertTrue(self.m.execute("return document.getElementById('layout-choice').hidden;"))

        # Also verify explicit confirmation of the default Lateral without changing radios,
        # and verify Settings selection dismissing an open Newtab card live via onChanged.
        fresh = harness.GeckoProfileSession(name="KeepDefault")
        self.addCleanup(fresh.cleanup)
        m2 = fresh.start()
        base2 = m2.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        m2.navigate(base2 + "newtab/newtab.html")
        self.assertTrue(harness.wait_until(lambda: m2.execute("return document.documentElement.dataset.ready==='true';"), 15))
        self.assertFalse(m2.execute("return document.getElementById('layout-choice').hidden;"))
        m2.send("WebDriver:ElementClick", {"id": m2.find_element("#layout-choice-done")})
        self.assertTrue(harness.wait_until(lambda: m2.execute("return document.getElementById('layout-choice').hidden;"), 10))
        self.assertEqual(
            chrome_async(m2, f"return {LAYOUT}.state(window);")["ok"],
            {"preset": "lateral", "available": True, "locked": False, "choicePending": False},
        )

    def test_upgraded_5a98bd7_and_custom_profiles_preserve_layout_without_prompt(self):
        # 1. Real upgrade from immutable 5a98bd7 reference binary (when available) -> UX3E:
        #    a profile created before UX3E that never touched sidebar.* MUST stay in Abas no topo ("top")
        #    and MUST NOT show the first-run layout prompt.
        reference = os.environ.get("NULAVIO_REFERENCE_ENGINE", "")
        ref_path = Path(reference) if reference else Path("/nonexistent")
        if reference:
            self.assertTrue(ref_path.is_file(), f"NULAVIO_REFERENCE_ENGINE does not exist: {reference}")
        tmp = Path(tempfile.mkdtemp(prefix="nulavio-ux3e-upgrade-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home = tmp / "home"
        run_dir = tmp / "run"
        run_dir.mkdir(mode=0o700)
        env = {  # nosemgrep: nulavio-py-engine-sandbox-env -- disposable upgrade verification profile
            harness.SYSTEM_ACCESS_ENV: "1",
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_RUNTIME_DIR": str(run_dir),
            "PATH": "/usr/bin:/bin",
            "LANG": os.environ.get("NULAVIO_TEST_LANG", "pt_BR.UTF-8"),
            "MOZ_MARIONETTE": "1",
            "MOZ_HEADLESS": "1",
        }
        prof_5a9 = tmp / "profiles" / "upgraded-default"
        prof_5a9.parent.mkdir(parents=True)
        subprocess.run(
            [str(self.session.engine.path), "--headless", "-CreateProfile", f"Upgraded {prof_5a9}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        harness.GeckoProfileSession.enable_marionette(prof_5a9)

        if ref_path.is_file():
            proc_old = subprocess.Popen(
                [str(ref_path), "-P", "Upgraded"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=lambda: os.umask(0o077),
                start_new_session=True,
            )
            try:
                m_old = harness.GeckoProfileSession.connect(prof_5a9, proc_old)
                self.assertTrue(
                    harness.wait_until(
                        lambda: m_old.chrome("return Services.prefs.getIntPref('nulavio.privacy.seeded', 0);") >= 1,
                        15,
                    )
                )
                before_upgrade = m_old.chrome("""
                  return {
                    orient: gBrowser.tabContainer.getAttribute('orient'),
                    seeded: Services.prefs.getIntPref('nulavio.privacy.seeded', 0),
                    migration: Services.prefs.getIntPref('browser.migration.version', -1),
                    hasVerticalUser: Services.prefs.prefHasUserValue('sidebar.verticalTabs'),
                    hasAdoption: Services.prefs.prefHasUserValue('nulavio.layout.adoptionVersion'),
                  };
                """)
                self.assertEqual(before_upgrade["orient"], "horizontal", before_upgrade)
                self.assertEqual(before_upgrade["seeded"], 1, before_upgrade)
                self.assertGreater(before_upgrade["migration"], 0, before_upgrade)
                self.assertFalse(before_upgrade["hasVerticalUser"], before_upgrade)
                self.assertFalse(before_upgrade["hasAdoption"], before_upgrade)
                m_old.chrome("Services.prefs.savePrefFile(null);")
                m_old.quit()
            finally:
                try:
                    proc_old.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc_old.kill()
                    proc_old.wait(timeout=10)
            (prof_5a9 / "MarionetteActivePort").unlink(missing_ok=True)
        else:
            # Deterministic pre-UX3E persisted profile fixture if no reference binary is installed.
            (prof_5a9 / "prefs.js").write_text(
                'user_pref("nulavio.privacy.seeded", 1);\nuser_pref("browser.migration.version", 183);\n',
                encoding="utf-8",
            )

        proc_new = subprocess.Popen(
            [str(self.session.engine.path), "-P", "Upgraded"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=lambda: os.umask(0o077),
            start_new_session=True,
        )
        try:
            m_new = harness.GeckoProfileSession.connect(prof_5a9, proc_new)
            after_state = chrome_async(m_new, f"return {LAYOUT}.state(window);")["ok"]
            self.assertEqual(
                after_state,
                {"preset": "top", "available": True, "locked": False, "choicePending": False},
            )
            after_prefs = m_new.chrome("""
              return {
                orient: gBrowser.tabContainer.getAttribute('orient'),
                hasVerticalUser: Services.prefs.prefHasUserValue('sidebar.verticalTabs'),
                adoption: Services.prefs.getIntPref('nulavio.layout.adoptionVersion', 0),
                pending: Services.prefs.getBoolPref('nulavio.layout.choicePending', true),
              };
            """)
            self.assertEqual(
                after_prefs,
                {"orient": "horizontal", "hasVerticalUser": False, "adoption": 1, "pending": False},
            )
            base_u = m_new.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
            m_new.navigate(base_u + "newtab/newtab.html")
            self.assertTrue(
                harness.wait_until(lambda: m_new.execute("return document.documentElement.dataset.ready==='true';"), 15)
            )
            self.assertTrue(m_new.execute("return document.getElementById('layout-choice').hidden;"))
            (self.artifacts / "upgrade-5a98bd7-to-ux3e.json").write_text(
                json.dumps(
                    {
                        "reference_engine_used": str(ref_path) if ref_path.is_file() else "persisted-prefs-fixture",
                        "state": after_state,
                        "prefs": after_prefs,
                    },
                    indent=2,
                )
                + "\n"
            )
            m_new.quit()
        finally:
            try:
                proc_new.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc_new.kill()
                proc_new.wait(timeout=10)

        # 2. Pre-existing custom profile (vertical + hide-sidebar) keeps Custom without prompt.
        prof_custom = tmp / "profiles" / "upgraded-custom"
        subprocess.run(
            [str(self.session.engine.path), "--headless", "-CreateProfile", f"CustomPre {prof_custom}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        (prof_custom / "prefs.js").write_text(
            'user_pref("sidebar.verticalTabs", true);\nuser_pref("sidebar.visibility", "hide-sidebar");\n',
            encoding="utf-8",
        )
        harness.GeckoProfileSession.enable_marionette(prof_custom)
        proc_custom = subprocess.Popen(
            [str(self.session.engine.path), "-P", "CustomPre"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=lambda: os.umask(0o077),
            start_new_session=True,
        )
        try:
            m_custom = harness.GeckoProfileSession.connect(prof_custom, proc_custom)
            custom_state = chrome_async(m_custom, f"return {LAYOUT}.state(window);")["ok"]
            self.assertEqual(
                custom_state,
                {"preset": "custom", "available": True, "locked": False, "choicePending": False},
            )
            self.assertEqual(m_custom.chrome("return Services.prefs.getStringPref('sidebar.visibility');"), "hide-sidebar")
            base_c = m_custom.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
            m_custom.navigate(base_c + "newtab/newtab.html")
            self.assertTrue(
                harness.wait_until(lambda: m_custom.execute("return document.documentElement.dataset.ready==='true';"), 15)
            )
            self.assertTrue(m_custom.execute("return document.getElementById('layout-choice').hidden;"))
            m_custom.quit()
        finally:
            try:
                proc_custom.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc_custom.kill()
                proc_custom.wait(timeout=10)

        # 3. Brand-new AI Workspace adopts Lateral without nagging non-interactive sessions.
        prof_ai = tmp / "profiles" / "ai-workspace"
        subprocess.run(
            [str(self.session.engine.path), "--headless", "-CreateProfile", f"AIWork {prof_ai}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        harness.GeckoProfileSession.enable_marionette(prof_ai)
        with open(prof_ai / "user.js", "a", encoding="utf-8") as handle:
            handle.write('user_pref("nulavio.ai.workspace", "claude-code");\n')
        proc_ai = subprocess.Popen(
            [str(self.session.engine.path), "-P", "AIWork"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=lambda: os.umask(0o077),
            start_new_session=True,
        )
        try:
            m_ai = harness.GeckoProfileSession.connect(prof_ai, proc_ai)
            ai_state = chrome_async(m_ai, f"return {LAYOUT}.state(window);")["ok"]
            self.assertEqual(
                ai_state,
                {"preset": "lateral", "available": True, "locked": False, "choicePending": False},
            )
            base_ai = m_ai.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
            m_ai.navigate(base_ai + "newtab/newtab.html")
            self.assertTrue(
                harness.wait_until(lambda: m_ai.execute("return document.documentElement.dataset.ready==='true';"), 15)
            )
            self.assertTrue(m_ai.execute("return document.getElementById('layout-choice').hidden;"))
            m_ai.quit()
        finally:
            try:
                proc_ai.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc_ai.kill()
                proc_ai.wait(timeout=10)
