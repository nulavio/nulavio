"""A page opened in a new profile's first seconds, before uBlock Origin is ready (#875): a measurement.

On a new profile's first start the build's policy installs uBlock Origin from addons.mozilla.org, and uBlock Origin
then loads its lists. A page that loads before that is not filtered. This module measures that window on the real
first start of a new profile, with the first-run sequence on as a person gets it, in the two ways a person can reach
a page that early:

- `test_01`: a link from another app starts the browser, so the page loads while the browser starts;
- `test_02`: the person chooses "Use the defaults" on the welcome as soon as it shows and opens a page at once.

The page asks for an image that uBlock Origin's default lists block by its address (`/adbanners/*`, the case
`test_engine_slice.py` 08 checks) beside a control image that no list blocks. Each reading counts the requests that
reached the local server; a reading where the control image never came says nothing and fails. While the early tab
is left alone, a new tab is opened again and again with a new address until the image is blocked there: that is the
moment the filter is ready for a new page. Then the early tab is checked, in this order (each step hides the one
before it): an image added to the page it shows, a new address in the same tab, a reload.

What is asserted holds however fast the network is: uBlock Origin is installed, a new tab is filtered within
`READY_WITHIN` seconds of the start, and reloading the early tab filters it (what docs/security/residual-risks.md
R91 tells people to do). Whether the first page's image left, and how long each part of the window lasted, is
recorded and not asserted: a JSON file per run in NULAVIO_TEST_ARTIFACTS and one line on stderr. The times depend on
the network, addons.mozilla.org and the machine, and the residual-risk entry gives what the runs measured.

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
SHELL_ID = "shell@nulavio.net"
READY_WITHIN = 180  # seconds after the engine process started: a new tab is filtered by then
READING = 20  # seconds a reading may take before it says nothing
AFTER_READY = 5  # rounds of (a new tab, an image added to the early page) once the filter is ready

ADDON = """
const done = arguments[arguments.length - 1];
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
AddonManager.getAddonByID(arguments[0]).then(
  a => done(a ? {active: a.isActive, version: a.version} : null), e => done({error: String(e)}));
"""
IMAGES_DONE = "return document.readyState === 'complete' && [...document.images].every(i => i.complete);"
ADD_IMAGES = """
for (const src of arguments) { const image = new Image(); image.src = src; document.body.append(image); }
"""
# The window around the page while the first run is staged (test_firstrun_stage.py).
STAGED = "return document.documentElement.hasAttribute('nulavio-stage');"


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
        self.artifacts = Path(os.environ.get("NULAVIO_TEST_ARTIFACTS") or self.session.tmp / "artifacts")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.counter = 0
        self.record: dict = {}

    # -- clock and readings ---------------------------------------------------------------------------------
    def started(self) -> None:
        """Set the clock's zero to the moment the engine process started."""
        self.zero = time.monotonic() - seconds_since_start(self.session.process.pid)

    def now(self, moment: float | None = None) -> float:
        return round((time.monotonic() if moment is None else moment) - self.zero, 2)

    def fresh(self, tag: str) -> str:
        self.counter += 1
        return f"{tag}{self.counter}"

    def read(self, n: str, times: int = 1, ads_before: int = 0) -> bool:
        """Whether the image the lists block reached the server for `n`, once the control image did (`times` times)
        and every image of the current page is done. Raises when the control image never came."""
        if not harness.wait_until(lambda: self.server.count(control(n)) >= times, timeout=READING):
            raise AssertionError(f"could not measure: the control image {control(n)} was not requested; {self.server.hits[-6:]}")
        if not harness.wait_until(lambda: self.m.execute(IMAGES_DONE), timeout=READING):
            raise AssertionError(f"could not measure: the page's images did not finish for n={n}")
        return self.server.count(ad(n)) > ads_before

    def addon(self) -> dict | None:
        self.m.set_context("chrome")
        try:
            state = self.m.execute_async(ADDON, [UBLOCK])
        finally:
            self.m.set_context("content")
        if state and "error" in state:
            raise AssertionError(state["error"])
        return state

    def probe(self) -> dict:
        """A new tab with a new address: is the image blocked there? The tab is closed afterwards."""
        n = self.fresh("p")
        handle = self.m.new_tab()
        self.m.switch_to(handle)
        at = self.now()
        self.m.navigate(self.server.url(f"/ads-fixture?n={n}"))
        leaked = self.read(n)
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(self.early)
        return {"at": at, "leaked": leaked}

    # -- the measurement ------------------------------------------------------------------------------------
    def wait_for_the_filter(self) -> None:
        """New tabs, one after another, until two in a row are filtered; the early tab is not touched."""
        probes, installed, streak = [], None, 0
        while self.now() < READY_WITHIN and streak < 2:
            if installed is None:
                state = self.addon()
                if state and state["active"]:
                    installed = self.now()
                    self.record["ublock_version"] = state["version"]
            probes.append(self.probe())
            streak = streak + 1 if not probes[-1]["leaked"] else 0
        self.record["ublock_active_at"] = installed
        self.record["probes"] = probes
        if installed is None:
            message = f"uBlock Origin was not installed by the policy in {READY_WITHIN} s (no network?)"
            if os.environ.get("NULAVIO_REQUIRE_NETWORK") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        self.assertEqual(streak, 2, f"a new tab was still not filtered {READY_WITHIN} s after the start: {probes[-4:]}")
        leaks = [p["at"] for p in probes if p["leaked"]]
        self.record["last_new_tab_leaked_at"] = leaks[-1] if leaks else None
        self.record["new_tab_filtered_at"] = probes[-2]["at"]

    def check_the_early_tab(self, n: str) -> None:
        """Once the filter is ready for new tabs: the early tab's page, then a new address in it, then a reload."""
        same_document, later_probes = [], []
        for _ in range(AFTER_READY):
            later_probes.append(self.probe())
            late = self.fresh(f"{n}-late")
            at = self.now()
            self.m.execute(ADD_IMAGES, [control(late), ad(late)])
            same_document.append({"at": at, "leaked": self.read(late)})
        self.record["new_tabs_after_ready"] = later_probes
        self.record["early_page_after_ready"] = same_document
        address = self.fresh("e")
        at = self.now()
        self.m.navigate(self.server.url(f"/ads-fixture?n={address}"))
        self.record["early_tab_new_address"] = {"at": at, "leaked": self.read(address)}
        before = self.server.count(ad(address))
        at = self.now()
        self.m.send("WebDriver:Refresh")
        self.record["early_tab_reload"] = {"at": at, "leaked": self.read(address, times=2, ads_before=before)}

    def finish(self, case: str) -> None:
        self.record["case"] = case
        self.record["engine"] = self.m.chrome("return Services.appinfo.version + ' ' + Services.appinfo.appBuildID;")
        name = f"first-start-filter-{case}-{time.strftime('%Y%m%dT%H%M%S')}.json"
        (self.artifacts / name).write_text(json.dumps(self.record, indent=2) + "\n")
        r = self.record

        def word(entry: dict) -> str:
            return f"{'LEAKED' if entry['leaked'] else 'blocked'}@{entry['at']}s"

        print(
            f"\nfirst-start-filter {case}: first page {word(r['first_page'])}, uBlock Origin active@{r['ublock_active_at']}s,"
            f" last new tab leaked@{r['last_new_tab_leaked_at']}s, new tab filtered@{r['new_tab_filtered_at']}s,"
            f" early page after ready {[word(e) for e in r['early_page_after_ready']]},"
            f" new address {word(r['early_tab_new_address'])}, reload {word(r['early_tab_reload'])};"
            f" new tabs after ready leaked {sum(p['leaked'] for p in r['new_tabs_after_ready'])}"
            f"/{len(r['new_tabs_after_ready'])}; uBlock Origin {r.get('ublock_version')}, engine {r['engine']}; {name}",
            file=sys.stderr,
        )
        # The way out that R91 gives: a reload of the early tab is filtered.
        self.assertFalse(r["early_tab_reload"]["leaked"], f"the early tab was still not filtered after a reload: {r}")

    def find_tab(self, address: str) -> str:
        for handle in self.m.window_handles():
            self.m.switch_to(handle)
            if address in self.m.current_url():
                return handle
        raise AssertionError(f"no tab shows {address}")

    # -- the two ways to an early page ----------------------------------------------------------------------
    def test_01_a_link_from_another_app_that_starts_the_browser(self):
        n = self.fresh("s")
        self.m = self.session.start(self.server.url(f"/ads-fixture?n={n}"), first_run=True)
        self.started()
        if not harness.wait_until(lambda: self.server.count(control(n)) >= 1, timeout=READING):
            raise AssertionError(f"could not measure: the address given at the start never loaded; {self.server.hits[-6:]}")
        self.early = self.find_tab(f"/ads-fixture?n={n}")
        leaked = self.read(n)
        self.record["first_page"] = {"at": self.now(self.server.first_hit(control(n))), "leaked": leaked}
        self.wait_for_the_filter()
        self.check_the_early_tab(n)
        self.finish("link")

    def test_02_a_page_opened_as_soon_as_the_welcome_lets_the_person_through(self):
        self.m = self.session.start(first_run=True)
        self.started()
        self.early = self.m.send("WebDriver:GetWindowHandle")["value"]
        skip = "return Boolean(document.getElementById('firstrun-skip')?.checkVisibility());"
        shown = harness.wait_until(lambda: self.m.execute(skip), timeout=READING)
        self.assertTrue(shown, "could not measure: the welcome of a new profile did not show")
        self.record["welcome_shown_at"] = self.now()
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#firstrun-skip")})
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(STAGED), timeout=READING), "the welcome did not end")
        self.record["welcome_ended_at"] = self.now()
        n = self.fresh("s")
        self.m.navigate(self.server.url(f"/ads-fixture?n={n}"))
        leaked = self.read(n)
        self.record["first_page"] = {"at": self.now(self.server.first_hit(control(n))), "leaked": leaked}
        self.wait_for_the_filter()
        self.check_the_early_tab(n)
        self.finish("welcome")


if __name__ == "__main__":
    unittest.main()
