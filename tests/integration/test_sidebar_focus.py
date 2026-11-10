"""Native sidebar keyboard focus keeps WCAG UI contrast in the Nulavio build."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brand"))
import harness
from contrast import ratio
from test_horizon import rgb


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's native sidebars")
class SidebarFocusTest(unittest.TestCase):
    def test_focus_contrast_in_native_panels(self):
        session = harness.GeckoProfileSession(name="Foco")
        self.addCleanup(session.cleanup)
        m = session.start()
        artifacts = harness.artifacts_dir() / "sidebar-focus"
        artifacts.mkdir(parents=True, exist_ok=True)
        measured = []
        probe = """
        const [view, done] = arguments;
        (async () => {
          await SidebarController.show(view);
          const deep = root => [...root.querySelectorAll('*')].flatMap(e => [e, ...(e.shadowRoot ? deep(e.shadowRoot) : [])]);
          const usable = root => deep(root).find(e => (e.localName === 'input' || e.localName === 'button')
            && e.getBoundingClientRect().width > 0 && !e.disabled);
          // Firefox 160 draws an extension panel's header (its close button) in the window, next
          // to the panel, not inside webext-panels.xhtml.
          let doc = SidebarController.browser.contentDocument;
          let control = usable(doc);
          const header = document.getElementById('sidebar-panel-header');
          if (!control && header && !header.hidden) {
            await header.updateComplete;
            control = usable(header.shadowRoot ?? header);
            doc = document;
          }
          if (!control) throw new Error('no native control in ' + SidebarController.browser.contentDocument.documentURI);
          Services.focus.setFocus(control, Ci.nsIFocusManager.FLAG_BYKEY);
          InspectorUtils.addPseudoClassLock(control, ':focus-visible');
          await new Promise(resolve => doc.defaultView.requestAnimationFrame(resolve));
          // moz-button draws its focus ring on the background span, not the inner button.
          const face = control.querySelector('.button-background') || control;
          const cs = doc.defaultView.getComputedStyle(face);
          let bg = 'rgba(0, 0, 0, 0)';
          for (const start of [face, SidebarController.browser]) {
            for (let e = start; e; e = e.parentElement || e.getRootNode().host) {
              bg = e.ownerDocument.defaultView.getComputedStyle(e).backgroundColor;
              if (bg !== 'rgba(0, 0, 0, 0)') break;
            }
            if (bg !== 'rgba(0, 0, 0, 0)') break;
          }
          return {uri: doc.documentURI, tag: control.localName, id: control.id, color: cs.outlineColor,
            style: cs.outlineStyle, width: cs.outlineWidth, bg};
        })().then(done, e => done({error: String(e)}));
        """

        def read(view):
            m.set_context("chrome")
            try:
                return m.execute_async(probe, [view])
            finally:
                m.set_context("content")

        for dark in (False, True):
            m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [int(dark)])
            time.sleep(0.6)
            for view in ("viewHistorySidebar", "viewBookmarksSidebar", "shell_nulavio_net-sidebar-action"):
                with self.subTest(dark=dark, view=view):
                    result = read(view)
                    self.assertNotIn("error", result, result)
                    self.assertEqual(result["style"], "solid", result)
                    self.assertGreaterEqual(float(result["width"].removesuffix("px")), 2, result)
                    contrast = ratio(rgb(result["color"]), rgb(result["bg"]))
                    self.assertGreaterEqual(contrast, 3, result)
                    measured.append({"dark": dark, "view": view, **result, "contrast": contrast})
                    time.sleep(0.6)  # the extension panel can still be painting after its native header is ready
                    m.set_context("chrome")
                    try:
                        (artifacts / f"{view}-{'dark' if dark else 'light'}.png").write_bytes(m.screenshot_png())
                    finally:
                        m.set_context("content")

        m.chrome("Services.prefs.setBoolPref('nulavio.horizon.enabled', false);")
        time.sleep(0.3)
        off = read("shell_nulavio_net-sidebar-action")
        self.assertNotEqual(rgb(off["color"]), rgb(result["color"]), off)
        m.chrome("Services.prefs.clearUserPref('nulavio.horizon.enabled');")

        def theme(addon_id):
            m.set_context("chrome")
            try:
                return m.execute_async(
                    "const [id, done] = arguments;"
                    "ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs').AddonManager"
                    ".getAddonByID(id).then(a => a ? a.enable().then(() => true) : false).then(done);",
                    [addon_id],
                )
            finally:
                m.set_context("content")

        if theme("firefox-alpenglow@mozilla.org"):
            try:
                time.sleep(0.6)
                themed = read("shell_nulavio_net-sidebar-action")
                self.assertNotEqual(rgb(themed["color"]), rgb(result["color"]), themed)
            finally:
                theme("default-theme@mozilla.org")

        m.navigate("data:text/html,<title>Web page</title><input>")
        self.assertEqual(
            m.execute("return getComputedStyle(document.documentElement).getPropertyValue('--focus-outline-color');"), ""
        )
        (artifacts / "contrast.json").write_text(json.dumps(measured, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
