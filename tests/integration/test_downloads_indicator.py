"""UX3C: native indicator over real, disposable Downloads API lists.

Transfers contain inert text only. Attention-priority inputs are explicit native
indicator states, not simulated reputation verdicts or a reputation backend.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import threading
import time
import unittest
from pathlib import Path

import harness
from marionette import MarionetteError
from test_horizon import rgb
from test_horizon_groups import KEY
from test_profiles import chrome_async

STATE = """
const b=document.getElementById('downloads-button'), badge=b.querySelector('.toolbarbutton-badge');
const s=getComputedStyle(badge), r=b.getBoundingClientRect();
const a=Cc['@mozilla.org/accessibilityService;1'].getService(Ci.nsIAccessibilityService).getAccessibleFor(b);
return {program:b.hasAttribute('nulavio-program'), attention:b.getAttribute('attention'),
  private:ChromeUtils.importESModule('resource://gre/modules/PrivateBrowsingUtils.sys.mjs')
    .PrivateBrowsingUtils.isWindowPrivate(window),
  progress:b.hasAttribute('progress'), percent:DownloadsIndicatorView._percentComplete,
  description:document.getElementById('nulavio-downloads-program-description')?.textContent ?? '',
  refs:b.getAttribute('aria-describedby'), name:a?.name, accessibleDescription:a?.description,
  label:b.getAttribute('label'), tooltip:b.getAttribute('tooltip'),
  badge:{display:s.display, image:s.backgroundImage, fill:s.fill, opacity:s.opacity,
    animation:s.animationName}, bg:getComputedStyle(document.getElementById('nav-bar')).backgroundColor,
  width:r.width, height:r.height, focus:document.activeElement===b,
  outline:getComputedStyle(b.badgeStack).outlineStyle, outlineWidth:getComputedStyle(b.badgeStack).outlineWidth,
  hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('#downloads-button')===b};
"""


@unittest.skipUnless(harness.nulavio_engine(), "UX3C requires the native Nulavio downloads patch")
class DownloadsIndicatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locale = os.environ.get("NULAVIO_DOWNLOADS_LOCALE", "pt-BR")
        cls.old_prefs = dict(harness.PROFILE_TEST_PREFS)
        harness.PROFILE_TEST_PREFS.update(
            {
                "intl.locale.requested": cls.locale,
                "browser.download.alwaysOpenPanel": False,
                "browser.download.autohideButton": False,
            }
        )
        cls.session = harness.GeckoProfileSession(name="Downloads")
        cls.m = cls.session.start()
        cls.main = cls.m.window_handles()[0]
        assert harness.wait_until(lambda: cls.m.chrome("return !!document.getElementById('nulavio-band');"), 20)
        assert cls.m.chrome("return Services.locale.appLocaleAsBCP47;") == cls.locale
        cls.out = harness.artifacts_dir() / "downloads-indicator" / cls.locale
        cls.out.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()
        harness.PROFILE_TEST_PREFS.clear()
        harness.PROFILE_TEST_PREFS.update(cls.old_prefs)

    def run_js(self, body, args=()):
        result = chrome_async(self.m, body, args)
        self.assertNotIn("error", result, result)
        return result["ok"]

    def setUp(self):
        self.directories = []
        self.run_js("""
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          const list=await Downloads.getList(Downloads.ALL);
          for(const d of await list.getAll()) {
            await list.remove(d); await d.finalize(true);
          }
          window.nvDownloads=[];
          DownloadsIndicatorView.ensureInitialized();
          DownloadsCommon.getIndicatorData(window).attention='';
          window.resizeTo(1366,768);
        """)

    def tearDown(self):
        for handle in self.m.window_handles():
            if handle != self.main:
                self.m.switch_to(handle)
                self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(self.main)
        self.run_js("""
          DownloadsPanel.hidePanel();
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          const list=await Downloads.getList(Downloads.ALL);
          for(const d of await list.getAll()) {
            await list.remove(d); await d.finalize(true);
          }
          for(const d of (window.nvDownloads ?? [])) {
            await d.finalize(true);
          }
          for(const key of ['ui.systemUsesDarkTheme','ui.prefersReducedMotion','nulavio.horizon.enabled',
            'ui.useAccessibilityTheme']) Services.prefs.clearUserPref(key);
        """)

        for directory in self.directories:
            shutil.rmtree(directory, ignore_errors=True)

    def add(self, name="example.AppImage", start=True, private=False, source="data:text/plain,Inert%20UX3C%20fixture"):
        result = self.run_js(
            """
          const [name,start,isPrivate,source]=args;
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          const dir=PathUtils.join(PathUtils.tempDir, 'nulavio-ux3c-'+Services.uuid.generateUUID());
          await IOUtils.makeDirectory(dir);
          const d=await Downloads.createDownload({source:{url:source,isPrivate},target:PathUtils.join(dir,name)});
          const list=await Downloads.getList(isPrivate?Downloads.PRIVATE:Downloads.PUBLIC);
          window.nvDownloads ??= [];
          nvDownloads.push(d); await list.add(d);
          if(start) await d.start().catch(()=>{});
          return {succeeded:d.succeeded,canceled:d.canceled,error:!!d.error,directory:dir};
        """,
            [name, start, private, source],
        )
        self.directories.append(Path(result["directory"]))
        return result

    def remove(self, index=0):
        self.run_js(
            """
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          const list=await Downloads.getList(Downloads.ALL);
          await list.remove(nvDownloads[args[0]]); await nvDownloads[args[0]].finalize(true);
        """,
            [index],
        )

    def state(self):
        return self.m.chrome(STATE)

    def expect_program(self, value):
        self.assertTrue(harness.wait_until(lambda: self.state()["program"] == value, 5), self.state())
        state = self.state()
        self.assertEqual(bool(state["description"]), value, state)
        return state

    def capture(self, name):
        self.m.set_context("chrome")
        (self.out / f"{name}.png").write_bytes(self.m.screenshot_png())
        self.m.set_context("content")

    def test_01_completed_program_render_and_native_names(self):
        self.assertTrue(harness.wait_until(lambda: self.state()["name"], 5), self.state())
        before = self.state()
        self.assertTrue(self.add()["succeeded"])
        measurements = []
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme',arguments[0]);", [dark])
            time.sleep(2.5)  # native completion notification ends; no changed deadline/assertion
            self.assertTrue(harness.wait_until(lambda: self.state()["name"], 5), self.state())
            self.capture(("dark" if dark else "light") + "-completed")
            state = self.state()
            measurements.append({"dark": dark, **state})
        (self.out / "completed.json").write_text(json.dumps(measurements, indent=2) + "\n")
        for state in measurements:
            self.assertEqual(state["attention"], "warning", state)
            self.assertTrue(state["program"], state)
            self.assertIn("warning-fill-12.svg", state["badge"]["image"])
            self.assertEqual(state["badge"]["display"], "block")
            self.assertEqual(state["badge"]["opacity"], "1")
            self.assertEqual(state["badge"]["animation"], "none")
            self.assertEqual((state["label"], state["tooltip"]), (before["label"], before["tooltip"]))
            self.assertEqual(state["name"], before["name"])
            self.assertIn("program", state["description"].lower())
            self.assertEqual(state["accessibleDescription"], state["description"])
            self.assertGreaterEqual(state["width"], 24)
            self.assertGreaterEqual(state["height"], 24)
            self.assertTrue(state["hit"])
            from contrast import ratio

            self.assertGreaterEqual(ratio(rgb(state["badge"]["fill"]), rgb(state["bg"])), 3)
        self.remove()
        self.expect_program(False)

    def test_02_multiple_items_last_removal_and_clear(self):
        self.expect_program(False)
        self.add("notes.txt")
        self.expect_program(False)
        self.m.chrome("""
          const d=document.createXULElement('description');d.id='ux3c-existing-description';
          d.hidden=true;d.textContent='Existing native description';document.documentElement.append(d);
          document.getElementById('downloads-button').setAttribute('aria-describedby',d.id);
        """)
        self.add("one.sh")
        self.add("two.rpm")
        self.expect_program(True)
        self.remove(1)
        self.expect_program(True)
        self.remove(2)
        self.expect_program(False)
        self.assertEqual(self.state()["refs"], "ux3c-existing-description")
        self.m.chrome("""
          document.getElementById('ux3c-existing-description').remove();
          document.getElementById('downloads-button').removeAttribute('aria-describedby');
        """)
        self.add("three.jar")
        self.run_js("""
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          await (await Downloads.getList(Downloads.PUBLIC)).removeFinished();
          for(const d of nvDownloads) await IOUtils.remove(d.target.path,{ignoreAbsent:true});
        """)
        self.expect_program(False)
        self.assertFalse(self.m.chrome("return DownloadsIndicatorView.hasDownloads;"))

    def test_03_failed_item_retains_type_until_removed(self):
        failed = self.add("failed.run", source="http://127.0.0.1:1/ux3c-unavailable")
        self.assertTrue(failed["error"], failed)
        self.expect_program(True)
        self.remove()
        self.expect_program(False)

    def test_04_native_attention_priority_and_suppression(self):
        self.add()
        for native in ("", "success", "info", "warning", "severe"):
            self.m.chrome("DownloadsCommon.getIndicatorData(window).attention=arguments[0];", [native])
            self.assertEqual(self.state()["attention"], "severe" if native == "severe" else "warning")
        self.remove()
        self.assertEqual(self.state()["attention"], None)
        for native in ("", "success", "info", "warning", "severe"):
            self.m.chrome("DownloadsCommon.getIndicatorData(window).attention=arguments[0];", [native])
            self.assertEqual(self.state()["attention"], native or None)
        self.add()
        self.m.chrome("DownloadsPanel.showPanel();")
        self.expect_program(True)  # viewing the panel acknowledges native attention, not list membership
        self.m.chrome("DownloadsPanel.hidePanel();")
        self.expect_program(True)

    def open_private_window(self):
        target = self.run_js("""
          // Completion warnings can create unrelated public tabs concurrently.
          // Include one deliberately: the first new tab is not a window identity.
          gBrowser.addTrustedTab('about:blank');
          const win=OpenBrowserWindow({private:true});
          if(!win.gBrowserInit?.delayedStartupFinished) await new Promise(resolve=>{
            const observer=(subject,topic)=>{
              if(subject===win){Services.obs.removeObserver(observer,topic);resolve();}
            };
            Services.obs.addObserver(observer,'browser-delayed-startup-finished');
          });
          return String(win.browsingContext.id);
        """)

        def find_target():
            for handle in self.m.window_handles():
                try:
                    self.m.switch_to(handle)
                    if self.m.chrome("return String(window.browsingContext.id)===arguments[0];", [target]):
                        return handle
                except MarionetteError as error:
                    if "no such window" not in str(error):
                        raise
            return None

        handle = harness.wait_until(find_target, 15)
        self.assertTrue(handle, target)
        self.m.switch_to(handle)
        self.m.chrome("DownloadsIndicatorView.ensureInitialized();")
        self.assertTrue(self.state()["private"])
        return handle

    def test_05_private_and_public_lists_do_not_leak(self):
        public_handle = self.main
        private = self.open_private_window()
        self.add(private=True)
        self.expect_program(True)
        self.m.switch_to(public_handle)
        self.expect_program(False)
        self.add()
        self.expect_program(True)
        self.m.switch_to(private)
        self.remove()
        self.expect_program(False)
        # Do not queue another completion-warning tab while closing this scope.
        self.add(private=True, start=False)
        self.m.switch_to(public_handle)
        self.m.chrome("""
          const {PrivateBrowsingUtils}=ChromeUtils.importESModule('resource://gre/modules/PrivateBrowsingUtils.sys.mjs');
          for(const win of Services.wm.getEnumerator('navigator:browser')) {
            if(PrivateBrowsingUtils.isWindowPrivate(win)) win.close();
          }
        """)
        self.assertTrue(
            harness.wait_until(
                lambda: self.run_js("""
          const {Downloads}=ChromeUtils.importESModule('resource://gre/modules/Downloads.sys.mjs');
          return (await (await Downloads.getList(Downloads.PRIVATE)).getAll()).length===0;
        """),
                5,
            )
        )
        self.expect_program(True)
        self.open_private_window()
        self.expect_program(False)
        self.add("private-notes.txt", private=True)
        self.expect_program(False)

    def test_06_native_keyboard_and_view_reconnect(self):
        self.add()
        self.assertTrue(harness.wait_until(lambda: len(self.m.window_handles()) > 1, 10))
        time.sleep(0.3)  # the real Shell warning's navigation must settle before keyboard input
        self.m.switch_to(self.main)
        self.m.chrome("""
          DownloadsIndicatorView.ensureTerminated();
          DownloadsIndicatorView.ensureInitialized();
          gURLBar.focus();
        """)
        self.expect_program(True)
        for _ in range(4):  # native page actions (e.g. bookmark star) can precede downloads
            self.m.chrome(KEY, ["Tab", "Tab", 9, False, False])
            if harness.wait_until(lambda: self.state()["focus"], 0.3):
                break
        self.assertTrue(
            harness.wait_until(lambda: self.state()["focus"], 5), self.m.chrome("return document.activeElement?.outerHTML;")
        )
        self.assertNotEqual(self.state()["outline"], "none")
        self.m.chrome(KEY, ["Enter", "Enter", 13, False, False])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return DownloadsPanel.panel.state==='open';"), 5))
        self.m.chrome("DownloadsPanel.hidePanel();")
        self.remove()
        self.expect_program(False)

    def test_07_transfer_progress_cancel_and_animation(self):
        release = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "1048576")
                self.end_headers()
                self.wfile.write(b"inert fixture" * 1024)
                self.wfile.flush()
                release.wait(15)

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.add("active.sh", start=False, source=f"http://127.0.0.1:{server.server_port}/active.sh")
            self.m.chrome("""
              nvDownloads[0].start().catch(()=>{});
            """)
            self.assertTrue(harness.wait_until(lambda: self.m.chrome("return nvDownloads[0].currentBytes>0;"), 5))
            self.expect_program(True)
            self.assertTrue(harness.wait_until(lambda: self.state()["progress"], 5), self.state())
            state = self.state()
            self.assertGreaterEqual(state["percent"], 0)
            self.assertLess(state["percent"], 100)
            self.assertEqual(state["badge"]["display"], "block", state)
            # Deterministically exercise the real notification entry point during progress.
            self.m.chrome("DownloadsIndicatorView.showEventNotification('finish');")
            self.assertEqual(self.state()["badge"]["display"], "block")
            self.capture("active-warning")
            self.run_js("await nvDownloads[0].cancel();")
            canceled = self.m.chrome("""
              const d=nvDownloads[0];return {canceled:d.canceled,partial:d.hasPartialData,
                stopped:d.stopped,error:d.error?.message,bytes:d.currentBytes,
                path:d.target.partFilePath,keep:d.tryToKeepPartialData};
            """)
            (self.out / "canceled.json").write_text(json.dumps(canceled, indent=2) + "\n")
            self.assertTrue(canceled["canceled"], canceled)
            self.assertTrue(canceled["stopped"], canceled)
            self.assertIsNone(canceled["error"], canceled)
            self.expect_program(True)
            self.run_js("await nvDownloads[0].removePartialData();")
            self.assertFalse(self.m.chrome("return nvDownloads[0].hasPartialData;"))
            self.expect_program(True)
            self.remove()
            self.expect_program(False)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_08_theme_motion_and_narrow_window_keep_warning(self):
        self.add(start=False)
        records = []
        for dark in (0, 1):
            for mode in ("horizon", "off", "contrast", "theme"):
                self.run_js(
                    """
                  const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
                  const [dark,mode]=args;
                  Services.prefs.setIntPref('ui.systemUsesDarkTheme',dark);
                  Services.prefs.setIntPref('ui.prefersReducedMotion',1);
                  Services.prefs.setBoolPref('nulavio.horizon.enabled',mode!=='off');
                  Services.prefs.setBoolPref('ui.useAccessibilityTheme',mode==='contrast');
                  await (await AddonManager.getAddonByID(mode==='theme'
                    ? 'firefox-compact-dark@mozilla.org' : 'default-theme@mozilla.org')).enable();
                  window.resizeTo(638,768);
                """,
                    [dark, mode],
                )
                time.sleep(0.2)
                state = self.expect_program(True)
                self.assertEqual(state["attention"], "warning", state)
                self.assertEqual(state["badge"]["display"], "block", state)
                self.assertEqual(state["badge"]["animation"], "none", state)
                self.assertTrue(state["hit"], state)
                records.append({"dark": dark, "mode": mode, **state})
        self.run_js("""
          const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
          await (await AddonManager.getAddonByID('default-theme@mozilla.org')).enable();
        """)
        (self.out / "fallbacks.json").write_text(json.dumps(records, indent=2) + "\n")

    def test_09_removal_while_indicator_detached_uses_current_list(self):
        # Keep the removed Download alive in nvDownloads, so WeakMap GC cannot
        # accidentally make this regression pass before its lifecycle fix.
        self.add(start=False)
        self.expect_program(True)
        self.m.chrome("DownloadsIndicatorView.ensureTerminated();")
        self.remove()
        self.add("notes.txt", start=False)
        self.m.chrome("DownloadsIndicatorView.ensureInitialized();")
        self.expect_program(False)
        self.assertTrue(self.m.chrome("return DownloadsIndicatorView.hasDownloads;"))


if __name__ == "__main__":
    unittest.main()
