"""What's new in this version, in the browser (#198 phase 2; Nulavio build).

The notes are the installed version's record, packed by the release build into
distribution/whats-new.json. A development build has none, so each case puts a
record in the module's place (NulavioWhatsNew.useRecordForTest) and runs the
start-up decision again; the profile, its prefs, the windows and the reader page
are the real ones. Covered: a new profile's first run, an update of Nulavio's
revision only, an engine update, skipped versions, a downgrade, a restart, the
setting turned off, two windows, a window opened private, an agent's browser, a
broken record, the reader page, and no request to nulavio.net on the way.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWhatsNew.sys.mjs").NulavioWhatsNew'
TEXT = {"summary": "An update of the alpha.", "new": ["One new thing."], "fixed": ["One fix.", "Another fix."]}
RECORD = {
    "version": "160.0-0.5", "date": "2026-11-20", "channel": "alpha", "firefox": "160.0",
    "pt-BR": {"summary": "Uma atualização da alpha.", "new": ["Uma novidade."], "fixed": ["Uma correção.", "Outra correção."]},
    "en-US": TEXT, "security": ["GHSA-j8cq-r5j6-q2x3"],
}  # fmt: skip


def record(version: str) -> dict:
    data = copy.deepcopy(RECORD)
    data["version"], data["firefox"] = version, version.split("-")[0]
    return data


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


@unittest.skipUnless(harness.nulavio_engine(), "the reader and the bar are the Nulavio build's Shell (NULAVIO_ENGINE)")
class WhatsNewBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.shots = harness.artifacts_dir() / "whats-new"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def setUp(self):
        self.prefs(notice=True)

    def w(self, body: str, *args):
        return chrome_async(self.m, f"const W = {MODULE}; {body}", args)

    def prefs(self, seen: str | None = None, notice: bool | None = None, firstrun: str | None = None) -> None:
        self.m.set_context("chrome")
        try:
            if seen is not None:
                self.m.execute("Services.prefs.setStringPref('nulavio.whatsnew.seen', arguments[0]);", [seen])
            if notice is not None:
                self.m.execute("Services.prefs.setBoolPref('nulavio.whatsnew.notice', arguments[0]);", [notice])
            if firstrun is not None:
                self.m.execute("Services.prefs.setStringPref('nulavio.firstrun.done', arguments[0]);", [firstrun])
        finally:
            self.m.set_context("content")

    def seen(self) -> str:
        return self.m.chrome("return Services.prefs.getStringPref('nulavio.whatsnew.seen', '');")

    def start_with(self, data) -> dict:
        """The start-up decision again, with `data` as the packed record; every bar from before closed first."""
        self.m.chrome(
            "for (const w of Services.wm.getEnumerator('navigator:browser'))"
            " w.gNotificationBox?.getNotificationWithValue('nulavio-whatsnew')?.close();"
        )
        return self.w("W.useRecordForTest(args[0]); return await W.start();", data)

    def open_reader(self) -> None:
        self.m.navigate(self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('whatsnew/whatsnew.html');"))
        ready = "return !document.querySelector('.whatsnew').hasAttribute('aria-busy');"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 15))

    def notice_on(self) -> bool:
        return self.m.chrome("return Services.prefs.getBoolPref('nulavio.whatsnew.notice', true);")

    def bars(self) -> list:
        """The bar's text in each browser window, '' where there is none."""
        return self.m.chrome(
            "return [...Services.wm.getEnumerator('navigator:browser')].map(w => {"
            " const n = w.gNotificationBox?.getNotificationWithValue('nulavio-whatsnew');"
            " return n ? n.messageText.textContent : ''; });"
        )

    def test_00_start_up_adds_the_help_entry_by_itself(self):
        # Before any case calls start(): the experiment's onStartup must have run (in 160.0-0.5 it failed
        # quietly on a module address, so no entry and no bar; every later case called start() itself).
        entry = "return !!document.getElementById('nulavio-whatsnew-menu');"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(entry), 20), "the Help menu entry is there at start-up")

    def test_01_the_build_packs_its_own_version_or_nothing(self):
        state = self.w("W.useRecordForTest(undefined); return await W.read();")
        if state["state"] == "ok":  # a release build: the record of this very engine
            version = self.m.chrome("return Services.appinfo.version;")
            self.assertEqual(state["record"]["firefox"], version)
        else:
            self.assertEqual(state["state"], "none", "a development build has no notes, and says so")

    def test_02_a_new_profiles_first_run_is_not_an_update(self):
        self.prefs(seen="", firstrun="")
        self.m.chrome("Services.prefs.setBoolPref('nulavio.startpage.shellFirstTab', true);")
        try:
            outcome = self.start_with(record("160.0-0.4"))
        finally:
            self.prefs(firstrun="finished")
        self.assertEqual(outcome["decision"], "first-run")
        self.assertEqual(self.seen(), "160.0-0.4")
        self.assertEqual(set(self.bars()), {""})

    def test_03_a_nulavio_only_update_shows_one_bar_once(self):
        before = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow();")  # two ordinary windows: the bar goes to one
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 15))
        second = next(iter(set(self.m.window_handles()) - before))
        self.prefs(seen="160.0-0.4")
        outcome = self.start_with(record("160.0-0.5"))
        self.assertEqual((outcome["decision"], outcome["from"]), ("show", "160.0-0.4"))
        bars = [b for b in self.bars() if b]
        self.assertEqual(len(self.bars()), 2)
        self.assertEqual(len(bars), 1, "one bar, in one of the two windows")
        self.assertIn("160.0-0.4", bars[0])
        self.assertIn("160.0-0.5", bars[0])
        self.assertEqual(self.seen(), "160.0-0.5", "recorded when shown: it never comes back for this version")
        # No tab was opened and the page kept its focus: the bar asks nothing.
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), 1)
        self.m.set_context("chrome")  # the bar is in the window, above the page
        try:
            (self.shots / "bar.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.set_context("content")
        # The same version again (a new window, the next start): nothing.
        self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "seen")
        self.assertEqual(set(self.bars()), {""})
        self.m.switch_to(second)
        self.m.chrome("window.close();")
        self.m.switch_to(next(iter(before)))

    def test_04_a_restart_does_not_bring_it_back(self):
        self.prefs(seen="160.0-0.4")
        self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "show")
        self.m = type(self).m = self.session.restart()
        self.assertEqual(self.seen(), "160.0-0.5")
        self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "seen")
        self.assertEqual(set(self.bars()), {""})

    def test_05_an_engine_update_and_skipped_versions(self):
        self.prefs(seen="160.0-0.1")
        outcome = self.start_with(record("161.0-0.3"))
        self.assertEqual((outcome["decision"], outcome["from"]), ("show", "160.0-0.1"), "one bar for every version skipped")
        self.assertEqual(len([b for b in self.bars() if b]), 1)

    def test_06_a_downgrade_says_nothing_and_keeps_the_newest(self):
        self.prefs(seen="161.0-0.3")
        self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "older")
        self.assertEqual(self.seen(), "161.0-0.3")
        self.assertEqual(set(self.bars()), {""})

    def test_07_turned_off_it_records_without_a_bar(self):
        self.prefs(seen="160.0-0.4", notice=False)
        outcome = self.start_with(record("160.0-0.5"))
        self.assertEqual(outcome["decision"], "off")
        self.assertEqual(self.seen(), "160.0-0.5", "turned on again later, it does not show an old update")
        self.assertEqual(set(self.bars()), {""})

    def test_08_a_private_window_waits_for_an_ordinary_one(self):
        before = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 15))
        private = next(iter(set(self.m.window_handles()) - before))
        self.m.chrome("window.close();")  # the ordinary window goes: only the private one is left
        self.m.switch_to(private)
        self.assertTrue(self.m.chrome("return PrivateBrowsingUtils.isWindowPrivate(window);"))
        self.prefs(seen="160.0-0.4")
        self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "show")
        self.assertEqual(set(self.bars()), {""}, "never in a private window")
        self.assertEqual(self.seen(), "160.0-0.4", "nothing recorded while only private windows are open")
        before = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow();")
        self.assertTrue(harness.wait_until(lambda: any(self.bars()), 15), "the next ordinary window gets it")
        self.assertEqual(self.seen(), "160.0-0.5")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 15))
        self.m.switch_to(next(iter(set(self.m.window_handles()) - before)))
        self.m.chrome(
            "for (const w of Services.wm.getEnumerator('navigator:browser'))"
            " if (PrivateBrowsingUtils.isWindowPrivate(w)) w.close();"
        )
        self.assertTrue(harness.wait_until(lambda: len(self.m.window_handles()) == 1, 15))

    def test_09_an_agents_browser_never_shows_or_records(self):
        self.prefs(seen="160.0-0.4")
        self.m.chrome("Services.prefs.setStringPref('nulavio.ai.workspace', 'test-agent');")
        try:
            self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "not-here")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('nulavio.ai.workspace');")
        self.assertEqual(self.seen(), "160.0-0.4")
        self.assertEqual(set(self.bars()), {""})

    def test_09b_a_temporary_profile_never_shows_or_records(self):
        self.prefs(seen="160.0-0.4")
        self.m.chrome("Services.prefs.setBoolPref('nulavio.profile.temporary', true);")
        try:
            self.assertEqual(self.start_with(record("160.0-0.5"))["decision"], "not-here")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('nulavio.profile.temporary');")
        self.assertEqual(self.seen(), "160.0-0.4")
        self.assertEqual(set(self.bars()), {""})

    def test_10_a_broken_record_is_reported_never_shown_in_part(self):
        broken = record("160.0-0.5")
        broken["en-US"]["new"] = [{"html": "<b>x</b>"}]
        self.prefs(seen="160.0-0.4")
        self.assertEqual(self.start_with(broken)["decision"], "unreadable")
        self.assertEqual(set(self.bars()), {""})
        self.open_reader()
        self.assertTrue(self.m.execute("return !document.getElementById('missing').hidden;"))
        self.assertEqual(self.m.execute("return document.querySelectorAll('.whatsnew__part:not([hidden])').length;"), 0)

    def test_11_the_reader_shows_the_notes_as_text_and_fetches_nothing(self):
        self.w(
            # On the chrome window: each Marionette script has its own global.
            "window.__nvRequests = []; window.__nvObserver = s => {"
            " const uri = s.QueryInterface(Ci.nsIChannel).URI.spec;"
            " if (uri.includes('nulavio.net')) window.__nvRequests.push(uri); };"
            " Services.obs.addObserver(window.__nvObserver, 'http-on-modify-request');"
        )
        try:
            data = record("160.0-0.5")
            data["en-US"]["fixed"][0] = "Tom's <script>alert(1)</script> fix"
            data["pt-BR"]["fixed"][0] = "Correção do Tom <script>alert(1)</script>"
            self.prefs(seen="160.0-0.5")
            self.start_with(data)
            self.open_reader()
            page = self.m.execute(
                "return {heading: document.getElementById('whatsnew-heading').textContent,"
                " parts: [...document.querySelectorAll('.whatsnew__part:not([hidden])')].map(s => s.id),"
                " items: [...document.querySelectorAll('#part-fixed li')].map(li => li.textContent),"
                " scripts: document.querySelectorAll('#part-fixed script').length,"
                " notice: document.getElementById('notice').checked,"
                " history: document.getElementById('history').href};"
            )
            self.assertIn("160.0-0.5", page["heading"])
            self.assertEqual(page["parts"], ["part-new", "part-fixed", "part-security"])
            self.assertIn("<script>", page["items"][0], "shown as text")
            self.assertEqual(page["scripts"], 0)
            self.assertTrue(page["notice"])
            self.assertRegex(page["history"], r"^https://nulavio\.net/(novidades|en/whats-new)/$")
            # The switch here is the setting.
            self.m.execute("document.getElementById('notice').click();")
            self.assertTrue(harness.wait_until(lambda: not self.notice_on(), 10))
            self.assertEqual(self.w("return window.__nvRequests;"), [], "reading and deciding fetch nothing")
        finally:
            self.w("Services.obs.removeObserver(window.__nvObserver, 'http-on-modify-request');")

    def test_12_the_help_menu_opens_the_reader(self):
        self.start_with(record("160.0-0.5"))
        tabs = self.m.chrome("return gBrowser.tabs.length;")
        label = self.m.chrome(
            "const item = document.getElementById('nulavio-whatsnew-menu'); item.doCommand(); return item.getAttribute('label');"
        )
        self.assertTrue(label)
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return gBrowser.tabs.length;") == tabs + 1, 10))
        selected = "return gBrowser.selectedBrowser.currentURI.spec;"
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(selected).endswith("/whatsnew/whatsnew.html"), 10), self.m.chrome(selected)
        )
        self.m.chrome("gBrowser.removeCurrentTab();")


if __name__ == "__main__":
    unittest.main()
