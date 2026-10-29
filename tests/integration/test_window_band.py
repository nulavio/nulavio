"""Farol's trusted chrome, driven through real Gecko/Shell backends. Headless, disposable homes only."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brand"))

import harness
from contrast import ratio
from test_horizon import rgb
from test_profiles import chrome_async
from nulavio_launcher.vault import sodium, storage

WINDOW = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWindow.sys.mjs").NulavioWindow'
BAND_PROBE = """(() => {
  const full = document.documentElement.matches('[inFullscreen], [inDOMFullscreen]');
  const row = document.querySelector(full ? '#nulavio-fullscreen' : '#nulavio-band .nv-band-row');
  if (!row) return null;
  const rect = e => {const r=e.getBoundingClientRect(), s=getComputedStyle(e);
    const hit=document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
    return {x:r.x,y:r.y,w:r.width,h:r.height,opacity:s.opacity,visibility:s.visibility,
      hit:!!hit && (hit === e || e.contains(hit)),hitNode:hit?.id || hit?.localName,bg:s.backgroundColor,color:s.color,
      border:s.borderTopStyle,outline:s.outlineStyle,outlineWidth:s.outlineWidth,
      animation:s.animationName,transition:s.transitionDuration};};
  const nodes = [...row.querySelectorAll('button, .nv-band-seal')].filter(e => !e.hidden && e.checkVisibility());
  return {full, text:nodes.map(e => e.textContent).join(" | "), rect:rect(row), viewport:[innerWidth,innerHeight],
    bg:getComputedStyle(row).backgroundColor, overflow:row.scrollWidth>row.clientWidth,
    cues:nodes.map(e => ({kind:e.className,text:e.textContent,label:e.getAttribute('aria-label'),...rect(e)}))};
})()"""


def assert_band(test, state):
    test.assertIsNotNone(state)
    test.assertFalse(state["overflow"], state)
    test.assertGreaterEqual(state["rect"]["h"], 3 if state["full"] else 30)
    for cue in state["cues"]:
        test.assertGreaterEqual(cue["h"], 20, cue)  # text seals; interactive targets below are >=24
        test.assertGreater(cue["w"], 0, cue)
        test.assertGreaterEqual(cue["x"], 0, cue)
        test.assertLessEqual(cue["x"] + cue["w"], state["viewport"][0] + 1, cue)
        test.assertLessEqual(cue["y"] + cue["h"], state["viewport"][1], cue)
        test.assertEqual(
            (cue["opacity"], cue["visibility"], cue["animation"], cue["transition"]), ("1", "visible", "none", "0s"), cue
        )
        test.assertTrue(cue["hit"], cue)
        test.assertTrue(cue["label"], cue)
        if any(c in cue["kind"] for c in ("identity", "protection", "guard", "pause", "stop")):
            test.assertGreaterEqual(cue["h"], 24, cue)
            test.assertGreaterEqual(cue["w"], 24, cue)


def assert_layout_matrix(test, m, label):
    """Exercise UX3D on the existing real security-state owners/fixtures.

    The raw composition fixture remains explicitly synthetic; this helper
    does not manufacture any security state or weaken its original assertions.
    """
    layout = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
    saved = m.chrome("""
      const keys=['sidebar.verticalTabs','sidebar.visibility','ui.systemUsesDarkTheme'];
      return {ui:SidebarController.getUIState(),prefs:keys.map(k=>
        ({k,user:Services.prefs.prefHasUserValue(k),value:Services.prefs.getPrefType(k)===128 ? Services.prefs.getBoolPref(k) :
          Services.prefs.getPrefType(k)===64 ? Services.prefs.getIntPref(k):Services.prefs.getStringPref(k,'')}))};
    """)
    out = harness.artifacts_dir() / "layout-security"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        with harness.FixtureServer() as server:
            m.navigate(server.url("/page/Layout"))
            m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 900})
            for preset in ("lateral", "top", "focus"):
                applied = chrome_async(m, f"return {layout}.apply(window,args[0]);", [preset])
                test.assertNotIn("error", applied, applied)
                test.assertEqual(applied["ok"]["preset"], preset)
                for dark in (0, 1):
                    m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);", [dark])
                    time.sleep(0.25)
                    band = m.chrome(f"return {BAND_PROBE};")
                    assert_band(test, band)
                    native = m.chrome("""
                      const rect=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                        const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
                        return {w:r.width,h:r.height,opacity:s.opacity,visibility:s.visibility,
                          hit:!!hit&&(e===hit||e.contains(hit))};};
                      return {url:gURLBar.value,actual:gBrowser.currentURI.spec,
                        input:{scroll:gURLBar.inputField.scrollWidth,client:gURLBar.inputField.clientWidth},
                        controls:['back-button','forward-button','stop-reload-button','urlbar','trust-icon-container'].map(id=>
                          ({id,...rect(document.getElementById(id))}))};
                    """)
                    test.assertIn("127.0.0.1", native["url"], native)
                    test.assertIn("/page/Layout", native["actual"], native)
                    test.assertLessEqual(native["input"]["scroll"], native["input"]["client"], native)
                    for control in native["controls"]:
                        test.assertGreater(control["w"], 0, control)
                        test.assertGreater(control["h"], 0, control)
                        test.assertEqual(control["visibility"], "visible", control)
                        test.assertTrue(control["hit"], control)
                    rows.append({"preset": preset, "dark": dark, "band": band, "native": native})
                    m.set_context("chrome")
                    try:
                        (out / f"{label}-{preset}-{'dark' if dark else 'light'}.png").write_bytes(m.screenshot_png())
                    finally:
                        m.set_context("content")
            (out / f"{label}.json").write_text(json.dumps(rows, indent=2) + "\n")
    finally:
        result = chrome_async(
            m,
            """
          for (const {k,user,value} of args[0].prefs) {
            if (!user) Services.prefs.clearUserPref(k);
            else if(typeof value==='boolean') Services.prefs.setBoolPref(k,value);
            else if(typeof value==='number') Services.prefs.setIntPref(k,value);
            else Services.prefs.setStringPref(k,value);
          }
          await SidebarController.updateUIState(args[0].ui);
        """,
            [saved],
        )
        test.assertNotIn("error", result, result)


@unittest.skipUnless(harness.nulavio_engine(), "Farol needs the built-in Shell")
class WindowBandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Farol")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def message(self, key):
        return self.m.chrome(
            "return WebExtensionPolicy.getByID('shell@nulavio.net').extension.localizeMessage(arguments[0]);", [key]
        )

    def test_01_identity_is_above_native_controls_and_cannot_be_hidden(self):
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return !!document.getElementById('nulavio-band');"), 10))
        result = chrome_async(
            self.m,
            """
          const C = ChromeUtils.importESModule('moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs').CustomizableUI;
          const bar = document.getElementById('nulavio-band');
          const native = [...gNavToolbox.children].filter(e => e !== bar).map(e => e.id);
          C.removeWidgetFromArea('nulavio-band-widget');
          C.setToolbarVisibility('nulavio-band', false);
          await new Promise(resolve => requestAnimationFrame(resolve));
          const r = bar.getBoundingClientRect(), cs = getComputedStyle(bar);
          return {name: bar.textContent, height: r.height, width: r.width, opacity: cs.opacity,
            visibility: cs.visibility, placement: C.getPlacementOfWidget('nulavio-band-widget')?.area,
            aboveTabs: !!(bar.compareDocumentPosition(document.getElementById('TabsToolbar')) & Node.DOCUMENT_POSITION_FOLLOWING),
            aboveNav: !!(bar.compareDocumentPosition(document.getElementById('nav-bar')) & Node.DOCUMENT_POSITION_FOLLOWING),
            nativeUnchanged: native.join() === [...gNavToolbox.children].filter(e => e !== bar).map(e => e.id).join()};
        """,
        )
        self.assertNotIn("error", result, result)
        r = result["ok"]
        self.assertIn("Farol", r["name"])
        self.assertGreaterEqual(r["height"], 30)
        self.assertGreater(r["width"], 400)
        self.assertEqual((r["opacity"], r["visibility"], r["placement"]), ("1", "visible", "nulavio-band"))
        self.assertTrue(r["aboveTabs"] and r["aboveNav"] and r["nativeUnchanged"], r)
        assert_layout_matrix(self, self.m, "ordinary")

    def test_02_only_a_selected_top_level_shell_principal_names_the_header(self):
        base = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

        def header():
            return self.m.chrome("return document.querySelector('#nulavio-band .nv-band-header').textContent;")

        self.m.navigate(base + "vault/unlock.html?p=0&label=FAKE#FAKE")
        self.assertTrue(harness.wait_until(lambda: self.message("bandSurfaceUnlock") in header(), 10), header())
        self.assertNotIn("FAKE", header())
        self.m.execute("document.title = 'FAKE title';")
        self.assertNotIn("FAKE", header())
        self.m.navigate("data:text/html,<title>Nulavio · Desbloqueio</title><h1>Nulavio · Desbloqueio</h1>")
        self.assertTrue(harness.wait_until(lambda: header() == "", 10), header())
        self.m.navigate(base + "dev/gallery/index.html?surface=vault/unlock.html")
        self.assertEqual(header(), "")  # Shell origin alone does not admit an unknown path
        self.m.chrome("""
          const p = WebExtensionPolicy.getByID('shell@nulavio.net');
          const tab = gBrowser.addTrustedTab(p.getURL('guard/review.html'), {inBackground: true});
          window.nvTestTab = tab;
        """)
        self.assertEqual(header(), "")
        with tempfile.TemporaryDirectory(prefix="farol-spoof-") as directory:
            addon = Path(directory)
            (addon / "vault").mkdir()
            (addon / "manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": 3,
                        "name": "Nulavio · Desbloqueio",
                        "version": "1.0",
                        "browser_specific_settings": {"gecko": {"id": "farol-spoof@example.invalid"}},
                    }
                )
            )
            (addon / "vault" / "unlock.html").write_text("<!doctype html><title>Nulavio · Desbloqueio</title>")
            self.m.install_addon(str(addon), temporary=True)
            url = self.m.chrome("return WebExtensionPolicy.getByID('farol-spoof@example.invalid').getURL('vault/unlock.html');")
            self.m.navigate(url)
            self.assertEqual(header(), "")  # correct path and extension principal, wrong add-on
        with harness.FixtureServer() as server:
            route = server.route

            def slow(path):
                time.sleep(0.4)
                return route(path)

            server.route = slow
            self.m.navigate(base + "vault/unlock.html?p=0")
            self.assertTrue(harness.wait_until(lambda: self.message("bandSurfaceUnlock") in header(), 10))
            self.m.chrome("openTrustedLinkIn(arguments[0], 'current');", [server.url("/page/race")])
            self.assertEqual(
                self.m.chrome("""
              const e = document.querySelector('#nulavio-band .nv-band-header');
              return [e.textContent,e.getAttribute('aria-label'),e.title];
            """),
                ["", "", ""],
            )
            self.assertNotIn("error", chrome_async(self.m, f"await {WINDOW}.refresh();"))
            self.assertEqual(header(), "")  # refresh cannot restore the old Shell header during navigation
        self.m.chrome("gBrowser.selectedTab = window.nvTestTab;")
        self.assertTrue(harness.wait_until(lambda: self.message("bandSurfaceGuard") in header(), 10), header())
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0]; gBrowser.removeTab(window.nvTestTab); delete window.nvTestTab;")
        self.assertEqual(header(), "")

    def test_03_teardown_restart_and_new_windows(self):
        result = chrome_async(
            self.m,
            f"""
          const ui = {WINDOW};
          ui.start(); ui.start();
          const win = OpenBrowserWindow();
          await new Promise(resolve => {{
            const obs = subject => {{ if(subject === win) {{
              Services.obs.removeObserver(obs, 'browser-delayed-startup-finished'); resolve();
            }} }};
            Services.obs.addObserver(obs, 'browser-delayed-startup-finished');
          }});
          const count = () => [...Services.wm.getEnumerator('navigator:browser')].map(w =>
            w.document.querySelectorAll('#nulavio-band').length);
          const before = count();
          ui.stop(); const stopped = count();
          ui.start(); await ui.refresh(); const restarted = count();
          win.close();
          return {{before, stopped, restarted}};
        """,
        )
        self.assertEqual(result, {"ok": {"before": [1, 1], "stopped": [0, 0], "restarted": [1, 1]}})

    def test_04_themes_orientation_density_narrow_scaling_and_fullscreen(self):
        shots = harness.artifacts_dir() / "window-band"
        shots.mkdir(parents=True, exist_ok=True)
        rows = []
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            for vertical in (False, True):
                self.m.chrome("Services.prefs.setBoolPref('sidebar.verticalTabs', arguments[0]);", [vertical])
                for width, scale in ((1366, "1.0"), (630, "1.25"), (630, "1.5")):
                    self.m.chrome("Services.prefs.setCharPref('layout.css.devPixelsPerPx',arguments[0]);", [scale])
                    self.m.send("WebDriver:SetWindowRect", {"width": width, "height": 768})
                    self.m.chrome("Services.prefs.setIntPref('browser.uidensity', 1);")
                    time.sleep(0.25)
                    state = self.m.chrome(f"return {BAND_PROBE};")
                    assert_band(self, state)
                    self.assertEqual(state["bg"], "rgb(4, 8, 13)" if dark else "rgb(191, 208, 214)")
                    rows.append({"dark": dark, "vertical": vertical, "width": width, "scale": scale, **state})
                    self.m.set_context("chrome")
                    try:
                        (
                            shots / f"{'dark' if dark else 'light'}-{'vertical' if vertical else 'top'}-{width}-{scale}.png"
                        ).write_bytes(self.m.screenshot_png())
                    finally:
                        self.m.set_context("content")
            self.m.chrome("window.fullScreen = true;")
            self.assertTrue(
                harness.wait_until(lambda: self.m.chrome("return document.documentElement.hasAttribute('inFullscreen');"), 10)
            )
            time.sleep(0.3)
            full = self.m.chrome(f"return {BAND_PROBE};")
            assert_band(self, full)
            self.assertTrue(full["full"])
            self.m.chrome("window.fullScreen = false;")
        self.m.chrome(
            "Services.prefs.clearUserPref('layout.css.devPixelsPerPx'); Services.prefs.clearUserPref('browser.uidensity');"
        )
        self.m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
        (shots / "geometry.json").write_text(json.dumps(rows, indent=2) + "\n")

    def test_05_guard_count_survives_dismissal_and_private_windows(self):
        guard = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard'
        self.assertNotIn("error", chrome_async(self.m, f"return await {guard}.check();"))
        self.session.stop()
        with (self.session.profile_dir / "user.js").open("a") as out:
            out.write('user_pref("browser.startup.homepage", "about:blank#farol-fixture");\n')
        self.m = self.__class__.m = self.session.restart()

        def text():
            return self.m.chrome(
                "const e=document.querySelector('#nulavio-band .nv-band-guard');return e && !e.hidden ? e.textContent : '';"
            )

        self.assertTrue(harness.wait_until(lambda: "Guard" in text(), 30), text())
        count = chrome_async(self.m, f"return {guard}.findings().length;")["ok"]
        self.assertGreater(count, 0)
        self.m.chrome("gNotificationBox.getNotificationWithValue('nulavio-guard')?.close();")
        self.assertIn(str(count), text())
        assert_band(self, self.m.chrome(f"return {BAND_PROBE};"))
        assert_layout_matrix(self, self.m, "guard")
        result = chrome_async(
            self.m,
            """
          const win = OpenBrowserWindow({private: true});
          await new Promise(resolve => {
            const obs = subject => {if(subject === win) {
              Services.obs.removeObserver(obs,'browser-delayed-startup-finished');resolve();
            }};
            Services.obs.addObserver(obs,'browser-delayed-startup-finished');
          });
          await new Promise(resolve => win.requestAnimationFrame(resolve));
          const row = win.document.querySelector('#nulavio-band .nv-band-row');
          const result = {text:row.textContent, private:row.dataset.private, guard:row.querySelector('.nv-band-guard').hidden};
          win.close(); return result;
        """,
        )
        self.assertEqual(result["ok"]["private"], "true")
        self.assertFalse(result["ok"]["guard"])
        self.assertIn(self.message("bandPrivate"), result["ok"]["text"])

    def test_06_customization_reset_keeps_native_order_and_safety_targets(self):
        result = chrome_async(
            self.m,
            f"""
          const C = ChromeUtils.importESModule('moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs').CustomizableUI;
          const ids = ['back-button','forward-button','stop-reload-button','urlbar-container','PanelUI-menu-button'];
          const parents = () => ids.map(id => [id, document.getElementById(id)?.parentNode.id]);
          const before = parents();
          C.addWidgetToArea('nulavio-band-widget','nav-bar');
          await new Promise(resolve => {{
            gNavToolbox.addEventListener('customizationready', resolve, {{once:true}});
            gCustomizeMode.enter();
          }});
          const during = {BAND_PROBE};
          await gCustomizeMode.reset();
          await new Promise(resolve => {{
            gNavToolbox.addEventListener('aftercustomization', resolve, {{once:true}});
            gCustomizeMode.exit();
          }});
          await {WINDOW}.refresh();
          return {{during, after:{BAND_PROBE}, before, parents:parents(),
            area:C.getPlacementOfWidget('nulavio-band-widget')?.area}};
        """,
        )
        self.assertNotIn("error", result, result)
        state = result["ok"]
        assert_band(self, state["during"])
        assert_band(self, state["after"])
        self.assertEqual(state["parents"], state["before"])
        self.assertEqual(state["area"], "nulavio-band")

    def test_07_page_fullscreen_keeps_a_flow_safety_line_and_native_exit_warning(self):
        self.m.navigate("data:text/html,<button id=f onclick='document.documentElement.requestFullscreen()'>Fullscreen</button>")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#f")})
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return document.documentElement.hasAttribute('inDOMFullscreen');"), 10)
        )
        time.sleep(0.5)
        state = self.m.chrome(f"return {BAND_PROBE};")
        assert_band(self, state)
        native = self.m.chrome("""
          const e = document.getElementById('fullscreen-warning'), r = e.getBoundingClientRect();
          const b = e.querySelector('#fullscreen-exit-button'), br = b.getBoundingClientRect();
          const hit = document.elementFromPoint(br.x+br.width/2, br.y+br.height/2);
          return {open:e.matches(':popover-open'),w:r.width,h:r.height,hit:!!hit && (b === hit || b.contains(hit)),
            contentY:document.getElementById('browser').getBoundingClientRect().y,
            bandBottom:document.getElementById('nulavio-fullscreen').getBoundingClientRect().bottom};
        """)
        self.assertTrue(native["open"] and native["hit"], native)
        self.assertGreater(native["w"], 0)
        self.assertGreaterEqual(native["contentY"], native["bandBottom"])
        self.m.execute("document.exitFullscreen();")
        self.assertTrue(
            harness.wait_until(lambda: not self.m.chrome("return document.documentElement.hasAttribute('inDOMFullscreen');"), 10)
        )

    def test_08_cosmetic_preferences_contrast_keyboard_and_real_profile_identity(self):
        profiles = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles'
        long_name = "Pesquisa internacional e documentos com nomes bem compridos"
        result = chrome_async(
            self.m,
            f"""
          const P = {profiles};
          if (!(await P.current())?.id) await P.create({{name:'Other',avatar:'heart',color:'coral'}});
          await P.update((await P.current()).id, {{name:args[0],color:'sky',avatar:'book'}});
          await {WINDOW}.refresh();
        """,
            [long_name],
        )
        self.assertNotIn("error", result, result)
        self.m.send("WebDriver:SetWindowRect", {"width": 630, "height": 768})
        for contrast in (0, 1):
            self.m.chrome(
                """
              Services.prefs.setBoolPref('nulavio.horizon.enabled', false);
              Services.prefs.setIntPref('ui.prefersContrast', arguments[0]);
              Services.prefs.setIntPref('ui.prefersReducedMotion', 1);
              Services.prefs.setIntPref('ui.prefersReducedTransparency', 1);
              const e=document.querySelector('#nulavio-band .nv-band-identity');
              Services.focus.setFocus(e,Ci.nsIFocusManager.FLAG_BYKEY);
              InspectorUtils.addPseudoClassLock(e, ':focus-visible');
            """,
                [contrast],
            )
            time.sleep(0.3)
            state = self.m.chrome(f"return {BAND_PROBE};")
            assert_band(self, state)
            self.assertIn(long_name, state["text"])
            identity = next(c for c in state["cues"] if c["kind"] == "nv-band-identity")
            self.assertEqual(identity["outline"], "solid")
            self.assertGreaterEqual(float(identity["outlineWidth"].removesuffix("px")), 2)
            self.assertEqual(
                self.m.chrome("return document.querySelector('#nulavio-band .nv-band-avatar')?.getAttribute('src');"),
                "chrome://browser/content/profiles/assets/16_book.svg",
            )
        self.m.chrome("""
          for(const key of ['nulavio.horizon.enabled','ui.prefersContrast',
            'ui.prefersReducedMotion','ui.prefersReducedTransparency'])
            Services.prefs.clearUserPref(key);
        """)

    def test_09_profile_selector_is_reached_by_keyboard_and_opens_the_real_popup(self):
        result = self.m.chrome("""
          const e = document.querySelector('#nulavio-band .nv-band-identity');
          Services.focus.setFocus(e, Ci.nsIFocusManager.FLAG_BYKEY);
          Services.focus.moveFocus(window, null, Ci.nsIFocusManager.MOVEFOCUS_FORWARD, Ci.nsIFocusManager.FLAG_BYKEY);
          const next = document.activeElement.className;
          Services.focus.setFocus(e, Ci.nsIFocusManager.FLAG_BYKEY);
          const tip = Cc['@mozilla.org/text-input-processor;1'].createInstance(Ci.nsITextInputProcessor);
          if (!tip.beginInputTransactionForTests(window)) throw new Error('no input transaction');
          const event = new KeyboardEvent('',{key:'Enter',code:'Enter',keyCode:13});
          tip.keydown(event); tip.keyup(event);
          return next;
        """)
        self.assertEqual(result, "nv-band-protection")
        opened = lambda: self.m.chrome("""
          return [...document.querySelectorAll('panel')].some(p => p.state === 'open' &&
            [...p.querySelectorAll('browser')].some(b => b.currentURI?.spec.includes('/profiles/popup.html')));
        """)  # noqa: E731
        self.assertTrue(harness.wait_until(opened, 10))
        self.m.chrome("for (const p of document.querySelectorAll('panel')) if(p.state === 'open') p.hidePopup();")
        before = set(self.m.window_handles())
        self.m.chrome("""
          const C=ChromeUtils.importESModule('moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs').CustomizableUI;
          C.removeWidgetFromArea('shell_nulavio_net-browser-action');
          document.querySelector('#nulavio-band .nv-band-identity').click();
        """)
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 10))
        self.m.switch_to((set(self.m.window_handles()) - before).pop())
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 10)
        )
        self.assertIn("/profiles/popup.html", self.m.current_url())
        self.assertFalse(self.m.execute("return document.getElementById('others-section').hidden;"))
        self.m.set_context("chrome")
        try:
            (harness.artifacts_dir() / "window-band" / "selector-without-action.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.set_context("content")
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(next(iter(before)))
        self.m.chrome("""
          const C=ChromeUtils.importESModule('moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs').CustomizableUI;
          C.addWidgetToArea('shell_nulavio_net-browser-action','nav-bar');
        """)

    def test_09_theme_and_forced_colors_keep_the_safety_surface(self):
        changed = chrome_async(
            self.m,
            """
          const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
          const theme = await AddonManager.getAddonByID('firefox-alpenglow@mozilla.org');
          if (!theme) return false;
          await theme.enable(); return true;
        """,
        )
        self.assertEqual(changed, {"ok": True})
        try:
            time.sleep(0.3)
            assert_band(self, self.m.chrome(f"return {BAND_PROBE};"))
        finally:
            chrome_async(
                self.m,
                """
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              await (await AddonManager.getAddonByID('default-theme@mozilla.org')).enable();
            """,
            )
        result = chrome_async(
            self.m,
            """
          const P=ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs').NulavioProfiles;
          if (!(await P.current())?.id) await P.create({name:'ContrastOther',avatar:'heart',color:'sky'});
          await P.update((await P.current()).id,{avatar:'book'});
        """,
        )
        self.assertNotIn("error", result, result)
        self.m.chrome("Services.prefs.setIntPref('ui.useAccessibilityTheme',1);")
        self.m = self.__class__.m = self.session.restart()
        self.m.chrome("Services.prefs.setIntPref('browser.display.document_color_use',2);")
        time.sleep(0.4)
        state = self.m.chrome(f"return {BAND_PROBE};")
        assert_band(self, state)
        # Gecko exempts chrome from document forced-colour overrides on some platforms;
        # increased-contrast still selects the explicit system-colour fallback.
        self.assertTrue(self.m.chrome("return matchMedia('(prefers-contrast: more)').matches;"))
        self.m.chrome("document.documentElement.style.colorScheme='dark';")
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return !!document.querySelector('#nulavio-band .nv-band-avatar');"), 10)
        )
        icon = self.m.chrome("""
          const e=document.querySelector('#nulavio-band .nv-band-identity'), i=e.querySelector('img');
          return {bg:getComputedStyle(e).backgroundColor,stroke:getComputedStyle(i).stroke};
        """)
        self.assertGreaterEqual(ratio(rgb(icon["stroke"]), rgb(icon["bg"])), 3, icon)
        self.m.chrome("document.documentElement.style.removeProperty('color-scheme');")
        self.m.chrome(
            "Services.prefs.clearUserPref('ui.useAccessibilityTheme');"
            "Services.prefs.clearUserPref('browser.display.document_color_use');"
        )

    def test_10_authoritative_agent_and_raw_latches_compose_with_retained_guard_findings(self):
        # Like the existing AI UI fixture: a real registry entry and workspace preference.
        # The marker is synthetic (a live test PID), read/latched by the real AI owner;
        # test_ai_bridge independently exercises actual endpoint handover and stop.
        result = chrome_async(
            self.m,
            f"""
          const A = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs').NulavioAI;
          const {{agent}} = await A.add({{name:'Farol composition fixture',client:'other',
            autonomy:'full_control',acceptFullControl:true}});
          await A.change(agent.id,'raw-automation',{{enabled:true,acceptRawAutomation:true}});
          Services.prefs.setStringPref('nulavio.ai.workspace',agent.id);
          const t = (key,subs=[]) => WebExtensionPolicy.getByID('shell@nulavio.net').extension.localizeMessage(key,subs);
          const W = {WINDOW};
          await W.refresh();
          const status = A.windowState;
          let release;
          A.windowState = () => new Promise(resolve => release = resolve);
          let retained;
          try {{
            const pending = W.refresh();
            await A.markWorkspace({{text:t('aiWorkspaceBar',[agent.name,t('aiLevel_full_control')]),
              rawText:t('aiWorkspaceBarRaw'),stopLabel:t('aiStopAgent'),pausedText:t('aiWorkspaceBarPaused',[agent.name])}});
            release(null); // stale pre-markWorkspace idle snapshot
            await pending;
            retained = !document.querySelector('#nulavio-band .nv-band-agent').hidden;
          }} finally {{ A.windowState = status; }}
          await {WINDOW}.refresh();
          return {{id:agent.id,retained}};
        """,
        )
        self.assertNotIn("error", result, result)
        self.assertTrue(result["ok"]["retained"], result)
        agent_id = result["ok"]["id"]
        assert_layout_matrix(self, self.m, "agent-guard-registry-fixture")
        state = self.m.chrome(f"return {BAND_PROBE};")
        assert_band(self, state)
        self.assertTrue(any("nv-band-agent" in c["kind"] for c in state["cues"]))
        self.assertTrue(any("nv-band-guard" in c["kind"] for c in state["cues"]))
        self.assertNotIn(
            "error",
            chrome_async(
                self.m,
                """
          await IOUtils.writeJSON(PathUtils.join(Services.dirsvc.get('ProfD',Ci.nsIFile).path,'nulavio-raw.json'),
            {agent:args[0],pid:Services.appinfo.processID});
        """,
                [agent_id],
            ),
        )
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return !document.querySelector('#nulavio-band .nv-band-raw').hidden;"), 10)
        )
        assert_layout_matrix(self, self.m, "raw-guard-synthetic-live-pid")
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);", [dark])
            time.sleep(0.3)
            for fullscreen in (False, True):
                self.m.chrome("window.fullScreen = arguments[0];", [fullscreen])
                time.sleep(0.3)
                state = self.m.chrome(f"return {BAND_PROBE};")
                assert_band(self, state)
                for kind in ("agent", "guard", "raw"):
                    self.assertTrue(any(f"nv-band-{kind}" in c["kind"] for c in state["cues"]), state)
                self.m.set_context("chrome")
                try:
                    name = f"raw-guard-{'dark' if dark else 'light'}-{'fullscreen' if fullscreen else 'window'}.png"
                    (harness.artifacts_dir() / "window-band" / name).write_bytes(self.m.screenshot_png())
                finally:
                    self.m.set_context("content")
                if fullscreen:
                    time.sleep(4.3)
                    line = self.m.chrome("""
                      const host = document.getElementById('nulavio-fullscreen');
                      const line = host.querySelector('.nv-fullscreen-line');
                      const r = line.getBoundingClientRect(), hit = document.elementFromPoint(r.x+10,r.y+r.height/2);
                      return {notice:host.hasAttribute('notice'),h:r.height,w:r.width,hit:line.contains(hit),
                        kinds:[...line.children].filter(e=>!e.hidden).map(e=>e.className)};
                    """)
                    self.assertFalse(line["notice"], line)
                    self.assertEqual(line["h"], 3)
                    self.assertTrue(line["hit"], line)
                    self.assertIn("nv-fullscreen-raw", line["kinds"])
                    self.assertIn("nv-fullscreen-guard", line["kinds"])
                    self.m.set_context("chrome")
                    try:
                        (harness.artifacts_dir() / "window-band" / f"compact-line-{dark}.png").write_bytes(
                            self.m.screenshot_png()
                        )
                    finally:
                        self.m.set_context("content")
                    self.m.chrome("""
                      Services.focus.setFocus(document.getElementById('nulavio-fullscreen'), Ci.nsIFocusManager.FLAG_BYKEY);
                    """)
                    state = self.m.chrome(f"return {BAND_PROBE};")
                    assert_band(self, state)
                    self.assertTrue(any("nv-band-stop" in c["kind"] for c in state["cues"]))
                    self.m.chrome("gBrowser.selectedBrowser.focus();")


@unittest.skipUnless(harness.nulavio_engine() and sodium.available() and storage.tools_available(), "needs Vault and Track B")
class ProtectedWindowBandTest(unittest.TestCase):
    def test_real_unlocked_profile_is_named_protected_and_current_lock_is_not_invented(self):
        session = harness.GeckoProfileSession(name="Owner")
        self.addCleanup(session.cleanup)
        m = session.start()
        body = """
          const V = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs');
          const P = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs').NulavioProfiles;
          const SPS = ChromeUtils.importESModule('resource:///modules/profiles/SelectableProfileService.sys.mjs').SelectableProfileService;
          const {id} = await V.NulavioVault.createProtected({name:'Farol Vault',avatar:'diamond',color:'sand',password:args[0]});
          const path = (await SPS.getProfile(id)).path;
          await V.vaultHelper({op:'unlock',path,method:'password',secret:args[0]});
          return {id,path};
        """
        result = chrome_async(m, body, ["synthetic farol vault password"])
        self.assertNotIn("error", result, result)
        profile_id, path = result["ok"]["id"], Path(result["ok"]["path"])
        harness.GeckoProfileSession.enable_marionette(path)
        launched = chrome_async(
            m,
            """
          return ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs')
            .NulavioProfiles.switchTo(args[0]);
        """,
            [profile_id],
        )
        self.assertEqual(launched, {"ok": {"action": "launched"}})
        child = harness.GeckoProfileSession.connect(path)
        try:
            self.assertTrue(
                harness.wait_until(lambda: "Farol Vault" in (child.chrome(f"return {BAND_PROBE};") or {}).get("text", ""), 15)
            )
            for dark in (0, 1):
                child.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);", [dark])
                time.sleep(0.3)
                state = child.chrome(f"return {BAND_PROBE};")
                assert_band(self, state)
                self.assertIn(
                    child.chrome(
                        "return WebExtensionPolicy.getByID('shell@nulavio.net').extension.localizeMessage('bandProtected');"
                    ),
                    state["text"],
                )
            assert_layout_matrix(self, child, "protected-unlocked")
            lock = chrome_async(
                child,
                """
              return ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs')
                .NulavioVault.lock(args[0]);
            """,
                [profile_id],
            )
            self.assertEqual(lock, {"error": "is-current"})
        finally:
            child.quit()
        self.assertTrue(harness.wait_until(lambda: not storage.Container(path).mounted(), 30))
        self.assertEqual(list(path.iterdir()), [])
