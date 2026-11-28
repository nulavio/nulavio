"""A page opened in a new profile's first seconds, before uBlock Origin is ready (#875): a measurement.

On a new profile's first start the build's policy installs uBlock Origin from addons.mozilla.org, and uBlock Origin
then loads its lists. A request made before that is not filtered, and the requests made while it loads them are held
back and then let through, filtered or not (docs/security/residual-risks.md, R91). This module measures that window
on the real first start of a new profile, with the first-run sequence on as a person gets it, in the two ways a
person can reach a page that early:

- `test_01`: a link from another app starts the browser, so the page loads while the browser starts;
- `test_02`: the person chooses "Use the defaults" on the welcome as soon as it shows and opens a page at once.

The page asks for an image that uBlock Origin's default lists block by its address (`/adbanners/*`, the case
`test_engine_slice.py` 08 checks) beside a control image that no list blocks. Each reading counts the requests that
reached the local server; a reading where the control image never came says nothing and fails. While the early tab
is left alone, a new tab is opened again and again with a new address until the image is blocked there: that is the
moment the filter is ready for a new page. Then the early tab is checked, in this order (each step hides the one
before it): an image added to the page it shows, a new address in the same tab, a reload.

The new tab's content-filter line (#898): before each new tab's page the Shell's reading of uBlock Origin
(`NulavioPrivacy.filter()`, the one the line shows) is recorded, and no page it let through may follow a reading that
said it filters. A new tab opened after the early page and left open must turn to "active" by itself once the filter
is ready, and in `test_02` the new tab the person sees before opening the page is read too.

What is asserted holds however fast the network is: uBlock Origin is installed, a new tab is filtered within
`READY_WITHIN` seconds of the start, and once it is, nothing the test asks for afterwards leaves, in new tabs or in
the early tab (R91 says so). Whether the first page's image left, and how long each part of the window lasted, is
recorded and not asserted: a JSON file per run in NULAVIO_TEST_ARTIFACTS and one line on stderr (a case that stops
before its end, failed or skipped, still writes what it measured, with `complete` false). The times depend on
the network, addons.mozilla.org and the machine, and the residual-risk entry gives what the runs measured. What
uBlock Origin hides inside a page (by element, not by request) is not measured here.

It needs the network, as a first start does: without it uBlock Origin is never installed, and the module is skipped
and says so, or fails where the run requires the network (NULAVIO_REQUIRE_NETWORK=1).
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

UBLOCK = "uBlock0@raymondhill.net"
READY_WITHIN = 180  # seconds after the engine process started: a new tab is filtered by then
READING = 20  # seconds a reading may take before it says nothing
AFTER_READY = 5  # rounds of (a new tab, an image added to the early page) once the filter is ready

ADDON = """
const done = arguments[arguments.length - 1];
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
AddonManager.getAddonByID(arguments[0]).then(
  a => done(a ? {active: a.isActive, version: a.version} : null), e => done({error: String(e)}));
"""
# Where uBlock Origin's install was when Marionette first answered (in the runs of 2026-11-27 it was always active).
FIRST_ANSWER = """
const done = arguments[arguments.length - 1];
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
Promise.all([AddonManager.getAddonByID(arguments[0]), AddonManager.getAllInstalls()]).then(([addon, all]) => done({
  active: addon ? addon.isActive : null,
  installs: all.filter(install => /ublock/i.test(install.sourceURI?.spec ?? "")).map(install => install.state),
}), e => done({error: String(e)}));
"""
# What the new tab's content-filter line shows: uBlock Origin installed, active, and whether it filters yet (#898).
FILTER = """return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs")
  .NulavioPrivacy.filter();"""
NEWTAB = "return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');"
LINE = """const dd = document.querySelector('#status [data-status=filter]');
return dd?.dataset.level ? {level: dd.dataset.level, text: dd.textContent} : null;"""
# uBlock Origin's toolbar button, every 100 ms from Marionette's first answer, each change with its time since the
# engine started (#898): "loading" from the start of its background, "own" once its request listener took over, and
# its badge "!" when a request went out while it had no listener (vAPI.Net in its js/vapi-background.js). A new
# `start` is a new start of the add-on. Read-only; it shows what NulavioPrivacy.filterReady() reads.
TRACE_START = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
const { ExtensionParent } = ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");
const zero = Services.startup.getStartupInfo().process.getTime();
const trace = (win.nulavioFilterTrace = []);
const id = arguments[0];
let last = "", seen = null, starts = 0;
const look = () => {
  const policy = WebExtensionPolicy.getByID(id);
  const ext = policy?.extension ?? null;
  if (ext && ext !== seen) { seen = ext; starts++; }
  const data = ext ? ExtensionParent.apiManager.global.browserActionFor?.(ext)?.action?.getContextData(null) : null;
  const loading = data && JSON.stringify(data.icon).includes("-loading.");
  const icon = !data ? "none" : !Object.hasOwn(data, "icon") ? "manifest" : loading ? "loading" : "own";
  const now = {active: Boolean(policy?.active), icon, badge: data ? data.badgeText : null, start: starts};
  const key = JSON.stringify(now);
  if (key !== last) { last = key; trace.push({at: Math.round(Date.now() - zero) / 1000, ...now}); }
};
look();
win.nulavioFilterTraceTimer = win.setInterval(look, 100);
"""
TRACE_READ = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
return win?.nulavioFilterTrace ?? null;
"""
IMAGES_DONE = "return document.readyState === 'complete' && [...document.images].every(i => i.complete);"
ADD_IMAGES = """
for (const src of arguments) { const image = new Image(); image.src = src; document.body.append(image); }
"""
# The window around the page while the first run is staged (test_firstrun_stage.py).
STAGED = "return document.documentElement.hasAttribute('nulavio-stage');"
# The new tab's own mark while a first-run card is its question (newtab.js, show()).
PAGE_STAGED = "return document.documentElement.hasAttribute('data-stage');"


def control(n: str) -> str:
    return f"/assets/control.png?n={n}"


def ad(n: str) -> str:
    return f"/adbanners/nulavio-test.png?n={n}"


def seconds_since_start(pid: int) -> float:
    """How long ago the process started, from the kernel's own record (/proc/<pid>/stat, field 22)."""
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    started = int(fields[19]) / os.sysconf("SC_CLK_TCK")
    return float(Path("/proc/uptime").read_text().split()[0]) - started


@unittest.skipUnless(harness.nulavio_engine(), "uBlock Origin comes with the Nulavio build's policies (NULAVIO_ENGINE)")
class FirstStartFilterWindowTest(unittest.TestCase):
    def setUp(self):
        self.server = harness.FixtureServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)  # stops the engine and removes the temporary home
        self.artifacts = harness.artifacts_dir()  # kept after the run: the session's temporary home is removed
        self.counter = 0
        self.record: dict = {"complete": False}
        self.saved: str | None = None
        self.last_control = 0.0  # unrounded seconds since the start: the deadline is decided on it
        self.addCleanup(self.save)  # added last, so it runs first: whatever was measured is kept, even on a failure

    # -- clock and readings ---------------------------------------------------------------------------------
    def started(self) -> None:
        """Set the clock's zero to the moment the engine process started."""
        since = seconds_since_start(self.session.process.pid)
        self.zero = time.monotonic() - since
        self.m.set_context("chrome")
        try:
            self.record["ublock_at_first_answer"] = {"at": self.now(), **self.m.execute_async(FIRST_ANSWER, [UBLOCK])}
            self.m.execute(TRACE_START, [UBLOCK])
        finally:
            self.m.set_context("content")

    def elapsed(self, moment: float | None = None) -> float:
        return (time.monotonic() if moment is None else moment) - self.zero

    def now(self, moment: float | None = None) -> float:
        """Seconds since the start, rounded for the record; decisions use `elapsed`."""
        return round(self.elapsed(moment), 2)

    def fresh(self, tag: str) -> str:
        self.counter += 1
        return f"{tag}{self.counter}"

    def read(self, n: str, asked: float, times: int = 1, ads_before: int = 0) -> dict:
        """One reading for `n`, asked for at `asked` (seconds since the start): when the control image reached the
        server (its `times`-th request), whether the image the lists block did too (more than `ads_before` times)
        and when it did, and when every image of the current page was done. Raises when the control image never
        came: such a reading says nothing."""
        if not harness.wait_until(lambda: len(self.server.hit_times(control(n))) >= times, timeout=READING):
            raise AssertionError(f"could not measure: the control image {control(n)} was not requested; {self.server.hits[-6:]}")
        if not harness.wait_until(lambda: self.m.execute(IMAGES_DONE), timeout=READING):
            raise AssertionError(f"could not measure: the page's images did not finish for n={n}")
        done = self.now()
        ads = self.server.hit_times(ad(n))
        self.last_control = self.elapsed(self.server.hit_times(control(n))[times - 1])
        return {
            "asked": asked,
            "requested": round(self.last_control, 2),
            "leaked": len(ads) > ads_before,
            "leaked_at": self.now(ads[ads_before]) if len(ads) > ads_before else None,
            "done": done,
        }

    def addon(self) -> dict | None:
        self.m.set_context("chrome")
        try:
            state = self.m.execute_async(ADDON, [UBLOCK])
        finally:
            self.m.set_context("content")
        if state and "error" in state:
            raise AssertionError(state["error"])
        return state

    def probe(self, into: list) -> None:
        """A new tab with a new address: is the image blocked there? The reading goes into `into` as soon as it is
        made, before the tab is closed: a failure while closing it does not lose it."""
        n = self.fresh("p")
        handle = self.m.new_tab()
        self.m.switch_to(handle)
        ready = self.m.chrome(FILTER).get("ready")  # what the new tab's line says now
        asked = self.now()
        self.m.navigate(self.server.url(f"/ads-fixture?n={n}"))
        into.append({**self.read(n, asked), "shell_ready": ready})
        if ready and self.record.get("shell_ready_at") is None:
            self.record["shell_ready_at"] = asked
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(self.early)

    # -- the measurement ------------------------------------------------------------------------------------
    def wait_for_the_filter(self) -> None:
        """New tabs, one after another, until two in a row are filtered; the early tab is not touched. The first of
        the two counts if its control image came before `READY_WITHIN`: the second then only confirms it."""
        probes, present, installed, streak = [], False, None, 0
        self.record["probes"] = probes  # filled as it goes: a failure keeps the probes made

        def before_the_deadline() -> bool:
            return self.elapsed() < READY_WITHIN or (streak == 1 and self.last_control < READY_WITHIN)

        def look_at_the_addon() -> None:
            nonlocal present, installed
            state = self.addon()
            present = present or state is not None
            if state and state["active"]:
                installed = self.now()
                self.record["ublock_version"] = state["version"]
            self.record["ublock_active_at"] = installed

        while streak < 2 and before_the_deadline():
            if installed is None:
                look_at_the_addon()
            self.probe(probes)
            streak = streak + 1 if not probes[-1]["leaked"] else 0
        if installed is None:
            look_at_the_addon()  # it may have appeared or become active during the last probe
        if installed is None:
            # Installed but never active is a broken activation, not a missing network: it fails everywhere.
            self.assertFalse(present, f"uBlock Origin was installed by the policy but not active in {READY_WITHIN} s")
            message = f"uBlock Origin was not installed by the policy in {READY_WITHIN} s (no network?)"
            if os.environ.get("NULAVIO_REQUIRE_NETWORK") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        self.assertEqual(streak, 2, f"a new tab was still not filtered {READY_WITHIN} s after the start: {probes[-4:]}")
        leaks = [p["leaked_at"] for p in probes if p["leaked"]]
        self.record["last_new_tab_leaked_at"] = leaks[-1] if leaks else None
        self.record["new_tab_filtered_at"] = probes[-2]["requested"]

    def check_the_early_tab(self, n: str) -> None:
        """Once the filter is ready for new tabs: the early tab's page, then a new address in it, then a reload."""
        same_document, later_probes = [], []
        self.record["new_tabs_after_ready"] = later_probes  # filled as it goes, as the probes are
        self.record["early_page_after_ready"] = same_document
        for _ in range(AFTER_READY):
            self.probe(later_probes)
            late = self.fresh(f"{n}-late")
            asked = self.now()
            self.m.execute(ADD_IMAGES, [control(late), ad(late)])
            same_document.append(self.read(late, asked))
        address = self.fresh("e")
        asked = self.now()
        self.m.navigate(self.server.url(f"/ads-fixture?n={address}"))
        self.record["early_tab_new_address"] = self.read(address, asked)
        # A reload asks for the same images again (the server says no-store): the second request of each counts.
        before, asked = len(self.server.hit_times(ad(address))), self.now()
        self.m.send("WebDriver:Refresh")
        self.record["early_tab_reload"] = self.read(address, asked, times=2, ads_before=before)

    def save(self) -> None:
        """Write the record once: from `finish`, or as a cleanup when the case stopped before it (a failure, a
        skip), with `complete` false and what was measured until then."""
        if self.saved:
            return
        case = self.record.get("case", "unknown")
        self.saved = f"first-start-filter-{case}-{time.strftime('%Y%m%dT%H%M%S')}.json"
        (self.artifacts / self.saved).write_text(json.dumps(self.record, indent=2) + "\n")
        if not self.record["complete"]:
            print(f"\nfirst-start-filter {case}: stopped before the end, partial record {self.saved}", file=sys.stderr)

    def finish(self) -> None:
        self.record["ublock_trace"] = self.m.chrome(TRACE_READ)
        self.record["engine"] = self.m.chrome("return Services.appinfo.version + ' ' + Services.appinfo.appBuildID;")
        self.record["complete"] = True
        self.save()
        case, name, r = self.record["case"], self.saved, self.record

        def word(entry: dict) -> str:
            return f"LEAKED@{entry['leaked_at']}s" if entry["leaked"] else f"blocked@{entry['requested']}s"

        print(
            f"\nfirst-start-filter {case}: first page asked@{r['first_page']['asked']}s {word(r['first_page'])},"
            f" uBlock Origin at the first answer {r['ublock_at_first_answer']}, active@{r['ublock_active_at']}s,"
            f" last new tab leaked@{r['last_new_tab_leaked_at']}s, new tab filtered@{r['new_tab_filtered_at']}s,"
            f" early page after ready {[word(e) for e in r['early_page_after_ready']]},"
            f" new address {word(r['early_tab_new_address'])}, reload {word(r['early_tab_reload'])};"
            f" new tabs after ready leaked {sum(p['leaked'] for p in r['new_tabs_after_ready'])}"
            f"/{len(r['new_tabs_after_ready'])}; uBlock Origin {r.get('ublock_version')}, engine {r['engine']}; {name}",
            file=sys.stderr,
        )
        # What R91 says of the time after the window: once a new tab is filtered, everything is, the early tab too.
        after = [*r["new_tabs_after_ready"], *r["early_page_after_ready"], r["early_tab_new_address"], r["early_tab_reload"]]
        self.assertEqual([e for e in after if e["leaked"]], [], f"a request left after the filter was ready: {name}")
        # #898: the new tab's line says "active" only once uBlock Origin filters, and says it once it does.
        said_ready = [p for p in [*r["probes"], *r["new_tabs_after_ready"]] if p["shell_ready"] and p["leaked"]]
        self.assertEqual(said_ready, [], f"the Shell said uBlock Origin filtered before a page it let through: {name}")
        self.assertTrue(all(p["shell_ready"] for p in r["new_tabs_after_ready"]), f"still 'loading' once it filters: {name}")
        line = r.get("newtab_line_at_first_page")
        if line is not None and r["first_page"]["leaked"]:
            self.assertNotEqual(line["level"], "ok", f"the new tab said 'active' before a page it let through: {name}")

    # -- a new tab left open (#898) ---------------------------------------------------------------------------
    def open_status_tab(self) -> None:
        """A new tab of the Shell, opened once the early page is read and left open: its content-filter line is read
        again by the page itself until uBlock Origin filters, without a reload."""
        self.status_tab = self.m.new_tab()
        self.m.switch_to(self.status_tab)
        self.m.navigate(self.m.chrome(NEWTAB))
        opened = harness.wait_until(lambda: self.m.execute(LINE), timeout=READING)
        self.record["status_tab_opened"] = {"at": self.now(), **opened} if opened else None
        self.m.switch_to(self.early)

    def read_status_tab(self) -> None:
        self.m.switch_to(self.status_tab)
        version = [self.record.get("ublock_version")]
        self.active_words = self.m.execute("return browser.i18n.getMessage('filterActive', [arguments[0]]);", version)
        turned = harness.wait_until(lambda: (lambda x: x if x and x["level"] == "ok" else None)(self.m.execute(LINE)), timeout=5)
        self.record["status_tab_after_ready"] = {"at": self.now(), **(turned or self.m.execute(LINE) or {})}
        self.m.switch_to(self.early)

    def assert_status_tab_turned(self) -> None:
        said = self.record["status_tab_after_ready"].get("text")
        self.assertEqual(said, self.active_words, "the new tab left open did not turn to 'active' once it filtered")

    def find_tab(self, address: str) -> str:
        for handle in self.m.window_handles():
            self.m.switch_to(handle)
            if address in self.m.current_url():
                return handle
        raise AssertionError(f"no tab shows {address}")

    # -- the two ways to an early page ----------------------------------------------------------------------
    def test_01_a_link_from_another_app_that_starts_the_browser(self):
        self.record["case"] = "link"
        n = self.fresh("s")
        self.m = self.session.start(self.server.url(f"/ads-fixture?n={n}"), first_run=True)
        self.started()
        if not harness.wait_until(lambda: self.server.count(control(n)) >= 1, timeout=READING):
            raise AssertionError(f"could not measure: the address given at the start never loaded; {self.server.hits[-6:]}")
        self.early = self.find_tab(f"/ads-fixture?n={n}")
        self.record["first_page"] = self.read(n, asked=0.0)
        self.open_status_tab()
        self.wait_for_the_filter()
        self.check_the_early_tab(n)
        self.read_status_tab()
        self.finish()
        self.assert_status_tab_turned()

    def test_02_a_page_opened_as_soon_as_the_welcome_lets_the_person_through(self):
        self.record["case"] = "welcome"
        self.m = self.session.start(first_run=True)
        self.started()
        self.early = self.m.send("WebDriver:GetWindowHandle")["value"]
        # Shown and painted: the new tab stays `visibility: hidden` until it has its final shape (pages.css).
        skip = "return Boolean(document.getElementById('firstrun-skip')?.checkVisibility({ visibilityProperty: true }));"
        shown = harness.wait_until(lambda: self.m.execute(skip), timeout=READING)
        self.assertTrue(shown, "could not measure: the welcome of a new profile did not show")
        self.record["welcome_shown_at"] = self.now()
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#firstrun-skip")})

        # Ended on both sides: the page leaves its stage once the click's handler is done, and the window after it.
        def ended() -> bool:
            return not self.m.execute(PAGE_STAGED) and not self.m.chrome(STAGED)

        self.assertTrue(harness.wait_until(ended, timeout=READING), "the welcome did not end")
        self.record["welcome_ended_at"] = self.now()
        # The new tab the person sees before going to the page: its content-filter line (#898).
        line = harness.wait_until(lambda: self.m.execute(LINE), timeout=READING)
        self.record["newtab_line_at_first_page"] = {"at": self.now(), **line} if line else None
        n = self.fresh("s")
        asked = self.now()
        self.m.navigate(self.server.url(f"/ads-fixture?n={n}"))
        self.record["first_page"] = self.read(n, asked)
        self.open_status_tab()
        self.wait_for_the_filter()
        self.check_the_early_tab(n)
        self.read_status_tab()
        self.finish()
        self.assert_status_tab_turned()


if __name__ == "__main__":
    unittest.main()
