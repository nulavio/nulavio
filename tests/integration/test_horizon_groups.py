"""Native group presentation and colour navigation, on a disposable registered Track B profile."""

from __future__ import annotations

import json
import os
import time
import unittest

import harness
import test_horizon
from test_horizon import rgb
from test_profiles import chrome_async

ALLOWED = ["blue", "cyan", "yellow", "pink", "green", "gray"]
LEGACY = ["orange", "purple", "red"]
WINDOW = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWindow.sys.mjs").NulavioWindow'

KEY = """
const [key, code, keyCode] = arguments;
const tip = Cc['@mozilla.org/text-input-processor;1'].createInstance(Ci.nsITextInputProcessor);
if (!tip.beginInputTransactionForTests(window)) throw new Error('no native keyboard transaction');
const e = new KeyboardEvent('', {key, code, keyCode});
const ctrl = new KeyboardEvent('', {key:'Control',code:'ControlLeft',keyCode:17});
const shift = new KeyboardEvent('', {key:'Shift',code:'ShiftLeft',keyCode:16});
if (arguments[3]) tip.keydown(ctrl);
if (arguments[4]) tip.keydown(shift);
tip.keydown(e); tip.keyup(e);
if (arguments[4]) tip.keyup(shift);
if (arguments[3]) tip.keyup(ctrl);
"""

EDITOR = """
const editor = document.getElementById('tab-group-editor');
const a11y = Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService);
return [...editor.querySelectorAll('input[name=tab-group-color]')].map(e => {
  const label=e.nextElementSibling, s=getComputedStyle(label), r=label.getBoundingClientRect();
  const a=a11y.getAccessibleFor(e), state={}, extra={};
  a?.getState(state, extra);
  return {value:e.value, checked:e.checked, visible:s.display!=='none' && r.width>0,
    inputDisplay:getComputedStyle(e).display, focus:document.activeElement===e,
    focusVisible:e.matches(':focus-visible'), outline:s.outlineStyle, outlineWidth:s.outlineWidth,
    name:a?.name, accessibleChecked:!!(state.value & Ci.nsIAccessibleStates.STATE_CHECKED),
    text:label.textContent, title:label.title, l10n:label.dataset.l10nId, color:s.backgroundColor};
});
"""

SCENE = """
const base=arguments[0];
window.nvGroups=[];
for (const [label,color] of [['Research','blue'],['Reference','cyan'],['Legacy','red']]) {
  const tabs=[gBrowser.addTrustedTab(base+label),gBrowser.addTrustedTab(base+label+' notes')];
  nvGroups.push(gBrowser.addTabGroup(tabs,{label,color}));
}
gBrowser.selectedTab=nvGroups[0].tabs[0];
"""


@unittest.skipUnless(harness.nulavio_engine(), "native groups need the built-in Shell")
class HorizonGroupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locale = os.environ.get("NULAVIO_GROUP_LOCALE", "pt-BR")
        cls.old_prefs = dict(harness.PROFILE_TEST_PREFS)
        harness.PROFILE_TEST_PREFS.update({"intl.locale.requested": cls.locale, "ui.systemUsesDarkTheme": 0})
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Groups")
        cls.m = cls.session.start()
        assert harness.wait_until(lambda: cls.m.chrome("return !!document.getElementById('nulavio-band');"), 15)
        assert cls.m.chrome("return Services.locale.appLocaleAsBCP47;") == cls.locale

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()
        cls.server.__exit__(None, None, None)
        harness.PROFILE_TEST_PREFS.clear()
        harness.PROFILE_TEST_PREFS.update(cls.old_prefs)

    def setUp(self):
        self.m.chrome(SCENE, [self.server.url("/page/")])
        time.sleep(0.4)

    def tearDown(self):
        self.m.chrome("""
          document.getElementById('tab-group-editor').panel.hidePopup();
          for(const group of [...gBrowser.getAllTabGroups()]) gBrowser.removeTabGroup(group);
          for(const key of ['sidebar.verticalTabs','ui.systemUsesDarkTheme','nulavio.horizon.enabled',
            'ui.prefersReducedMotion','ui.useAccessibilityTheme']) Services.prefs.clearUserPref(key);
        """)

    def pref(self, key, value):
        kind = {bool: "Bool", int: "Int", str: "String"}[type(value)]
        self.m.chrome(f"Services.prefs.set{kind}Pref(arguments[0],arguments[1]);", [key, value])
        time.sleep(0.3)

    def open_editor(self, index=0, create=False):
        r = chrome_async(
            self.m,
            """
          const [index, create] = arguments;
          const editor=document.getElementById('tab-group-editor');
          const shown=new Promise(r=>editor.panel.addEventListener('popupshown',r,{once:true}));
          if(create) editor.openCreateModal(nvGroups[index]); else editor.openEditModal(nvGroups[index]);
          await shown; await document.l10n.translateFragment(editor);
          return {mode:editor.createMode, color:editor.activeGroup.color};
        """,
            [index, create],
        )
        self.assertNotIn("error", r, r)
        return r["ok"]

    def key(self, name, ctrl=False, shift=False):
        codes = {"ArrowRight": 39, "ArrowLeft": 37, "ArrowDown": 40, "ArrowUp": 38, "Tab": 9, "Enter": 13, " ": 32}
        self.m.chrome(KEY, [name, "Space" if name == " " else name, codes[name], ctrl, shift])

    def focus_color(self, color):
        self.m.chrome(
            "Services.focus.setFocus(document.getElementById('tab-group-editor-swatch-'+arguments[0]),"
            "Ci.nsIFocusManager.FLAG_BYKEY);",
            [color],
        )

    def editor(self):
        # Gecko builds its accessibility tree asynchronously after a native popup
        # or radio change. Wait for the checked accessible, not just DOM checked.
        latest = []

        def ready():
            nonlocal latest
            latest = self.m.chrome(EDITOR)
            return any(s["checked"] and s["name"] and s["accessibleChecked"] for s in latest)

        self.assertTrue(harness.wait_until(ready, 5), latest)
        return latest

    def click_label(self, selector):
        self.m.chrome(
            """
          const e=document.querySelector(arguments[0]), r=e.getBoundingClientRect();
          const x=r.x+r.width/2,y=r.y+r.height/2;
          window.synthesizeMouseEvent('mousedown',x,y,{button:0,clickCount:1},{});
          window.synthesizeMouseEvent('mouseup',x,y,{button:0,clickCount:1},{});
        """,
            [selector],
        )

    def test_01_native_default_skips_reserved_including_exhaustion(self):
        self.assertEqual(self.m.chrome("return document.getElementById('tab-group-editor').nextUnusedColor;"), "yellow")
        colors = self.m.chrome("""
          const out=[];
          for(let i=0;i<12;i++) out.push(gBrowser.addTabGroup([gBrowser.addTrustedTab('about:blank')]).color);
          return out;
        """)
        self.assertTrue(all(c in ALLOWED for c in colors), colors)
        self.assertEqual(self.m.chrome("return nvGroups[2].color;"), "red")

    def test_02_create_edit_native_keyboard_and_pointer(self):
        for dark in (0, 1):
            self.pref("ui.systemUsesDarkTheme", dark)
            for vertical in (False, True):
                self.pref("sidebar.verticalTabs", vertical)
                with self.subTest(dark=dark, vertical=vertical):
                    self.m.chrome("nvGroups[0].color='blue';")
                    self.exercise_editor()
                    self.m.chrome("document.getElementById('tab-group-editor').close();")
                    time.sleep(0.15)

    def exercise_editor(self):
        self.assertTrue(self.open_editor(create=True)["mode"])
        self.assertEqual([s["value"] for s in self.editor() if s["visible"]], ALLOWED)
        self.focus_color("blue")
        for direction, sequence in (
            ("ArrowRight", ["cyan", "yellow", "pink", "green", "gray", "blue"]),
            ("ArrowLeft", ["gray", "green", "pink", "yellow", "cyan", "blue"]),
            ("ArrowDown", ["cyan"]),
            ("ArrowUp", ["blue"]),
        ):
            for want in sequence:
                self.key(direction)
                states = self.editor()
                current = next(s for s in states if s["checked"])
                self.assertEqual(current["value"], want, states)
                self.assertTrue(current["visible"] and current["focus"] and current["focusVisible"], current)
                self.assertNotEqual(current["outline"], "none", current)
                self.assertTrue(current["accessibleChecked"] and current["name"], current)
                self.assertEqual(current["name"], current["text"])
                self.assertEqual(current["title"], current["text"])
        self.click_label('label[for="tab-group-editor-swatch-green"]')
        self.assertEqual(self.m.chrome("return nvGroups[0].color;"), "green")
        self.key("Enter")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('tab-group-editor').panel.state;") == "closed", 5
            )
        )
        self.assertFalse(self.open_editor()["mode"])
        self.assertEqual(next(s["value"] for s in self.editor() if s["checked"]), "green")
        for color in ALLOWED:
            self.click_label(f'label[for="tab-group-editor-swatch-{color}"]')
            current = next(s for s in self.editor() if s["checked"])
            self.assertEqual(current["value"], color)
            self.assertEqual(self.m.chrome("return nvGroups[0].color;"), color)
        self.focus_color("gray")
        self.key("ArrowRight")
        self.assertEqual(next(s["value"] for s in self.editor() if s["checked"]), "blue")
        state = self.m.chrome(
            "return [matchMedia('(prefers-color-scheme:dark)').matches,gBrowser.tabContainer.getAttribute('orient')];"
        )
        (self.capture_dir() / f"editor-{state[0]}-{state[1]}.json").write_text(json.dumps(self.editor(), indent=2) + "\n")

    def test_03_legacy_current_is_visible_named_checked_and_retained(self):
        for color in LEGACY:
            with self.subTest(color=color):
                self.m.chrome("nvGroups[2].color=arguments[0];", [color])
                self.open_editor(2)
                states = self.editor()
                current = next(s for s in states if s["checked"])
                self.assertEqual(current["value"], color)
                self.assertTrue(current["visible"] and current["accessibleChecked"] and current["name"], current)
                self.assertEqual(current["text"], current["name"])
                self.assertEqual(current["title"], current["text"])
                (self.capture_dir() / f"legacy-{color}.json").write_text(json.dumps(states, indent=2) + "\n")
                self.m.chrome("document.getElementById('tab-group-editor').close();")
                time.sleep(0.15)
                self.assertEqual(self.m.chrome("return nvGroups[2].color;"), color)
                stored = self.m.chrome("return SessionStore.getWindowState(window).windows[0].groups;")
                self.assertIn(color, [g["color"] for g in stored], stored)
                self.open_editor(2)
                # The native panel initially focuses its name field. Enter the
                # radio group through the real tab order (Nova puts it before it).
                if self.m.chrome("return Services.prefs.getBoolPref('browser.nova.enabled',false);"):
                    self.key("Tab", shift=True)
                else:
                    self.key("Tab")
                self.assertTrue(next(s for s in self.editor() if s["checked"])["focus"])
                self.focus_color(color)
                self.assertTrue(next(s for s in self.editor() if s["checked"])["focusVisible"])
                self.key("ArrowRight")
                states = self.editor()
                current = next(s for s in states if s["checked"])
                self.assertIn(current["value"], ALLOWED)
                self.assertTrue(current["visible"] and current["focus"] and current["accessibleChecked"], current)
                self.assertEqual([s["value"] for s in states if s["visible"]], ALLOWED)
                self.m.chrome("document.getElementById('tab-group-editor').close();")
                time.sleep(0.15)

    def test_04_groups_both_themes_orientations_and_collapsed(self):
        measurements = []
        for dark in (0, 1):
            self.pref("ui.systemUsesDarkTheme", dark)
            for vertical in (False, True):
                self.pref("sidebar.verticalTabs", vertical)
                for collapsed in (False, True):
                    self.m.chrome("nvGroups[0].collapsed=arguments[0];", [collapsed])
                    time.sleep(0.4)  # native collapse animation must settle before measuring/capturing
                    self.assertTrue(
                        harness.wait_until(
                            lambda: self.m.chrome(
                                "return !!Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService)"
                                ".getAccessibleFor(nvGroups[0].labelElement);"
                            ),
                            5,
                        )
                    )
                    r = self.m.chrome("""
                      const group=nvGroups[0], label=group.labelElement, s=getComputedStyle(label);
                      const mark=getComputedStyle(group.tabs[0].querySelector('.tab-background'),'::after');
                      const swatch=getComputedStyle(label,'::before');
                      const line=getComputedStyle(group.tabs[0].querySelector('.tab-group-line'));
                      const a=Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService)
                        .getAccessibleFor(label);
                      return {dark:matchMedia('(prefers-color-scheme:dark)').matches,
                        orient:gBrowser.tabContainer.getAttribute('orient'),
                        expanded:label.getAttribute('aria-expanded'),role:label.getAttribute('role'),name:a?.name,
                        bg:s.backgroundColor,text:s.color,swatch:swatch.backgroundColor,swatchContent:swatch.content,
                        line:line.backgroundColor,lineWidth:line.width,lineHeight:line.height,
                        mark:{content:mark.content,w:mark.width,h:mark.height,color:mark.backgroundColor},
                        hidden:group.tabs.map(t=>t.hasAttribute('aria-hidden'))};
                    """)
                    self.assertEqual(r["dark"], bool(dark))
                    self.assertEqual(r["orient"], "vertical" if vertical else "horizontal")
                    self.assertEqual((r["role"], r["name"], r["expanded"]), ("button", "Research", str(not collapsed).lower()))
                    self.assertEqual(r["bg"], "rgba(0, 0, 0, 0)")
                    self.assertEqual(r["swatchContent"], '""')
                    self.assertNotEqual(rgb(r["swatch"]), rgb(r["mark"]["color"]))
                    self.assertEqual((r["mark"]["w"], r["mark"]["h"]), ("3px", "20px") if vertical else ("16px", "2px"))
                    self.assertEqual(r["hidden"], [False, collapsed])
                    measurements.append({"collapsed": collapsed, **r})
                    self.capture(
                        f"{'dark' if dark else 'light'}-{'vertical' if vertical else 'horizontal'}-"
                        f"{'collapsed' if collapsed else 'expanded'}"
                    )
        (self.capture_dir() / "measurements.json").write_text(json.dumps(measurements, indent=2) + "\n")

    def test_08_native_label_keyboard_collapse_and_focus(self):
        for vertical in (False, True):
            self.pref("sidebar.verticalTabs", vertical)
            self.m.chrome(
                "nvGroups[0].collapsed=false; gBrowser.selectedTab=nvGroups[0].tabs[0];"
                "gBrowser.tabContainer.ariaFocusedItem=null;"
                "Services.focus.setFocus(nvGroups[0].tabs[0],Ci.nsIFocusManager.FLAG_BYKEY);"
                "gBrowser.tabContainer.ariaFocusedItem=nvGroups[0].tabs[0];"
            )
            self.key("ArrowLeft", ctrl=True)
            r = self.m.chrome("""
              const label=nvGroups[0].labelElement, s=getComputedStyle(label);
              return {focused:gBrowser.tabContainer.ariaFocusedItem===label,
                outline:s.outlineStyle, width:s.outlineWidth};
            """)
            self.assertTrue(r["focused"], r)
            self.assertNotEqual(r["outline"], "none", r)
            self.key(" ")
            self.assertTrue(self.m.chrome("return nvGroups[0].collapsed;"))
            self.key(" ")
            self.assertFalse(self.m.chrome("return nvGroups[0].collapsed;"))
            self.click_label("tab-group .tab-group-label")
            self.assertTrue(self.m.chrome("return nvGroups[0].collapsed;"))

    def test_09_rendered_palette_contrast(self):
        from contrast import ratio

        results = []
        for dark in (0, 1):
            self.pref("ui.systemUsesDarkTheme", dark)
            for color in ALLOWED + LEGACY:
                self.m.chrome("nvGroups[0].color=arguments[0];", [color])
                r = self.m.chrome("""
                  const label=nvGroups[0].labelElement;
                  const el=document.createElementNS('http://www.w3.org/1999/xhtml','div');
                  el.style.color='var(--toolbox-background-color)';document.documentElement.append(el);
                  const bg=getComputedStyle(el).color;el.remove();
                  return {swatch:getComputedStyle(label,'::before').backgroundColor,
                    text:getComputedStyle(label).color,bg};
                """)
                self.assertGreaterEqual(ratio(rgb(r["swatch"]), rgb(r["bg"])), 3, r)
                self.assertGreaterEqual(ratio(rgb(r["text"]), rgb(r["bg"])), 4.5, r)
                results.append({"dark": dark, "color": color, **r})
        (self.capture_dir() / "contrast.json").write_text(json.dumps(results, indent=2) + "\n")

    def capture_dir(self):
        out = harness.artifacts_dir() / "horizon-groups" / self.locale
        out.mkdir(parents=True, exist_ok=True)
        return out

    def capture(self, name):
        self.m.set_context("chrome")
        (self.capture_dir() / f"{name}.png").write_bytes(self.m.screenshot_png())
        self.m.set_context("content")

    def test_05_guards_restore_native_choices_and_default(self):
        for guard in ("pref", "contrast", "theme"):
            with self.subTest(guard=guard):
                if guard == "pref":
                    self.pref("nulavio.horizon.enabled", False)
                elif guard == "contrast":
                    self.pref("ui.useAccessibilityTheme", 1)
                else:
                    self.assertTrue(test_horizon.HorizonTest.enable_theme(self, "firefox-alpenglow@mozilla.org"))
                try:
                    self.open_editor()
                    self.assertEqual(len([s for s in self.editor() if s["visible"]]), 9)
                    self.assertEqual(
                        self.m.chrome("return getComputedStyle(nvGroups[0].labelElement,'::before').content;"), "none"
                    )
                    self.assertEqual(
                        self.m.chrome("return document.getElementById('tab-group-editor').nextUnusedColor;"), "purple"
                    )
                    self.focus_color("blue")
                    self.key("ArrowRight")
                    self.assertEqual(self.m.chrome("return nvGroups[0].color;"), "purple")
                    (self.capture_dir() / f"guard-{guard}.json").write_text(json.dumps(self.editor(), indent=2) + "\n")
                finally:
                    self.m.chrome("document.getElementById('tab-group-editor').close(); nvGroups[0].color='blue';")
                    if guard == "pref":
                        self.pref("nulavio.horizon.enabled", True)
                    elif guard == "contrast":
                        self.pref("ui.useAccessibilityTheme", 0)
                    else:
                        test_horizon.HorizonTest.enable_theme(self, "default-theme@mozilla.org")
                self.assertEqual(self.m.chrome("return document.getElementById('tab-group-editor').nextUnusedColor;"), "yellow")

    def test_06_lifecycle_restores_getter(self):
        self.m.chrome(f"{WINDOW}.stop();")
        try:
            self.assertFalse(
                self.m.chrome("return Object.hasOwn(document.getElementById('tab-group-editor'),'nextUnusedColor');")
            )
            self.assertEqual(self.m.chrome("return document.getElementById('tab-group-editor').nextUnusedColor;"), "purple")
        finally:
            self.m.chrome(f"{WINDOW}.start();")
        self.assertEqual(self.m.chrome("return document.getElementById('tab-group-editor').nextUnusedColor;"), "yellow")

    def test_07_trust_indicators_band_and_motion_preserved(self):
        probe = """
          return ['trust-icon-container','tracking-protection-icon-container','identity-permission-box',
            'remote-control-box','notification-popup-box'].map(id=>{
              const e=document.getElementById(id),s=e&&getComputedStyle(e);
              return e&&[id,s.display,s.visibility];
            });
        """
        on = self.m.chrome(probe)
        self.pref("nulavio.horizon.enabled", False)
        self.assertEqual(on, self.m.chrome(probe))
        self.pref("nulavio.horizon.enabled", True)
        self.pref("ui.prefersReducedMotion", 1)
        self.assertEqual(
            self.m.chrome(
                "return getComputedStyle(gBrowser.selectedTab.querySelector('.tab-background'),'::after').animationName;"
            ),
            "none",
        )
        self.assertGreater(self.m.chrome("return document.getElementById('nulavio-band').getBoundingClientRect().height;"), 0)
        self.assertTrue(self.m.chrome("return document.documentElement.hasAttribute('remotecontrol');"))

    def test_10_native_group_list_uses_the_same_palette(self):
        for dark in (0, 1):
            self.pref("ui.systemUsesDarkTheme", dark)
            result = chrome_async(
                self.m,
                """
              const view=PanelMultiView.getViewNode(document,'toolbar-tabGroupsListView');
              const shown=new Promise(r=>view.addEventListener('ViewShown',r,{once:true}));
              await PanelUI.showSubView('toolbar-tabGroupsListView',document.getElementById('PanelUI-menu-button'));
              await shown;await view.querySelector('tab-groups-list').updateComplete;
              return [...view.querySelectorAll('.tab-group-row')].map(row=>({
                name:row.querySelector('.tab-group-row-label').textContent,
                color:getComputedStyle(row.querySelector('.tab-group-row-icon')).fill,
                expected:getComputedStyle(nvGroups.find(g=>g.id===row.dataset.tabGroupId).labelElement,'::before').backgroundColor
              }));
            """,
            )
            try:
                self.assertNotIn("error", result, result)
                rows = result["ok"]
                self.assertEqual({r["name"] for r in rows}, {"Research", "Reference", "Legacy"})
                for row in rows:
                    self.assertEqual(row["color"], row["expected"], row)
                (self.capture_dir() / f"list-{dark}.json").write_text(json.dumps(rows, indent=2) + "\n")
            finally:
                self.m.chrome("document.getElementById('customizationui-widget-panel')?.hidePopup();")
                self.assertTrue(
                    harness.wait_until(
                        lambda: self.m.chrome("return !document.getElementById('customizationui-widget-panel');"), 5
                    )
                )

    def test_11_native_urlbar_group_actions_keep_text_and_icon_contrast(self):
        from contrast import ratio

        original = self.m.chrome("""
          return {had:Services.prefs.prefHasUserValue('browser.nova.enabled'),
            value:Services.prefs.getBoolPref('browser.nova.enabled',false)};
        """)
        results = []
        self.m.chrome("""
          nvGroups[0].collapsed=true;
          window.nvUrlbarTestTab=gBrowser.addTrustedTab('about:robots');
          gBrowser.selectedTab=nvUrlbarTestTab;
        """)
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.chrome("""
          return nvUrlbarTestTab.linkedBrowser.currentURI.spec==='about:robots'
            && !nvUrlbarTestTab.linkedBrowser.webProgress.isLoadingDocument;
        """),
                10,
            )
        )
        try:
            for nova in (False, True):
                self.pref("browser.nova.enabled", nova)
                for dark in (0, 1):
                    self.pref("ui.systemUsesDarkTheme", dark)
                    for color in ALLOWED + LEGACY:
                        result = chrome_async(
                            self.m,
                            """
                          gURLBar.view.close();
                          nvGroups[0].color=args[0]; nvGroups[0].label='Research '+args[0];
                          gURLBar.focus(); gURLBar.search(nvGroups[0].label);
                          for(let i=0;i<100;i++) {
                            const button=document.querySelector('.urlbarView-action-btn[data-action^="tabgroup-"]');
                            if(button && button.style.getPropertyValue('--tab-group-color')
                              .includes('--tab-group-'+args[0]+')')) return true;
                            await new Promise(resolve=>setTimeout(resolve,50));
                          }
                          throw new Error('native group action did not resolve the current colour: '+JSON.stringify(
                            [...document.querySelectorAll('.urlbarView-row')].map(row=>({text:row.textContent,
                              buttons:[...row.querySelectorAll('.urlbarView-action-btn')].map(button=>({
                                action:button.dataset.action,color:button.style.getPropertyValue('--tab-group-color')}))}))));
                        """,
                            [color],
                        )
                        self.assertEqual(result, {"ok": True})
                        for state in ("normal", "hover", "active"):
                            current = self.m.chrome(
                                """
                              const button=document.querySelector('.urlbarView-action-btn[data-action^="tabgroup-"]');
                              for(const name of [':hover',':active']) InspectorUtils.removePseudoClassLock(button,name);
                              if(arguments[0]!=='normal') InspectorUtils.addPseudoClassLock(button,':hover');
                              if(arguments[0]==='active') InspectorUtils.addPseudoClassLock(button,':active');
                              const label=button.querySelector('.urlbarView-action-btn-label'),icon=button.querySelector('img');
                              const s=getComputedStyle(button),r=button.getBoundingClientRect();
                              return {text:label.textContent,fg:getComputedStyle(label).color,bg:s.backgroundColor,
                                icon:getComputedStyle(icon).fill,opacity:s.opacity,w:r.width,h:r.height};
                            """,
                                [state],
                            )
                            results.append({"nova": nova, "dark": dark, "color": color, "state": state, **current})
                            if color == "blue" and state == "normal":
                                self.capture(f"urlbar-{'nova' if nova else 'proton'}-{'dark' if dark else 'light'}")
                            self.assertIn("Research", current["text"])
                            self.assertGreater(current["w"], 0)
                            self.assertGreater(current["h"], 0)
                            self.assertEqual(current["opacity"], "1", current)
                            self.assertGreaterEqual(ratio(rgb(current["fg"]), rgb(current["bg"])), 4.5, current)
                            self.assertGreaterEqual(ratio(rgb(current["icon"]), rgb(current["bg"])), 3, current)
                        self.m.chrome("""
                          const button=document.querySelector('.urlbarView-action-btn[data-action^="tabgroup-"]');
                          for(const name of [':hover',':active']) InspectorUtils.removePseudoClassLock(button,name);
                        """)
        finally:
            self.m.chrome("""
              gURLBar.view.close();gURLBar.blur();
              gBrowser.removeTab(nvUrlbarTestTab);delete window.nvUrlbarTestTab;
            """)
            if original["had"]:
                self.pref("browser.nova.enabled", original["value"])
            else:
                self.m.chrome("Services.prefs.clearUserPref('browser.nova.enabled');")
            (self.capture_dir() / "urlbar-action-contrast.json").write_text(json.dumps(results, indent=2) + "\n")
