"""Vertical-slice integration tests: real engine, real profile, real sandbox.

Each test asserts behaviour that a user would rely on. They run headless
against a disposable profile prepared by the launcher itself. Skipped when
no supported engine is installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from marionette import MarionetteError

from nulavio_launcher import prefs as prefs_mod
from nulavio_launcher import profile as profile_mod

UBO_ID = "uBlock0@raymondhill.net"
REGISTRY_FILES = [
    Path.home() / ".config" / "mozilla" / "firefox" / "profiles.ini",
    Path.home() / ".config" / "mozilla" / "firefox" / "installs.ini",
    Path.home() / ".mozilla" / "firefox" / "profiles.ini",
    Path.home() / ".mozilla" / "firefox" / "installs.ini",
]

PREF_READER = """
const names = arguments[0];
const out = {};
const def = Services.prefs.getDefaultBranch("");
for (const n of names) {
  const t = Services.prefs.getPrefType(n);
  let v = null;
  if (t == Services.prefs.PREF_BOOL) v = Services.prefs.getBoolPref(n);
  else if (t == Services.prefs.PREF_INT) v = Services.prefs.getIntPref(n);
  else if (t == Services.prefs.PREF_STRING) v = Services.prefs.getStringPref(n);
  out[n] = {type: t, value: v, hasDefault: def.getPrefType(n) != 0};
}
return out;
"""

ADDON_STATE = """
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const a = await AddonManager.getAddonByID(arguments[0]);
return a ? {active: a.isActive, userDisabled: a.userDisabled, seen: a.seen,
            signedState: a.signedState, version: a.version} : null;
"""

ADDON_TOGGLE = """
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const a = await AddonManager.getAddonByID(arguments[0]);
if (arguments[1]) { await a.enable(); } else { await a.disable(); }
return a.isActive;
"""


def _hash_registry() -> dict[str, str | None]:
    out = {}
    for path in REGISTRY_FILES:
        out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return out


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
class EngineSliceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry_before = _hash_registry()
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.Session()
        cls.m = cls.session.start()
        cls.artifacts = harness.artifacts_dir()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.stop()
            after = _hash_registry()
            if after != cls.registry_before:
                raise AssertionError(f"Firefox profile registry changed: {cls.registry_before} -> {after}")
        finally:
            cls.server.__exit__(None, None, None)
            cls.session.cleanup()

    # -- helpers ----------------------------------------------------------
    def chrome_async(self, script: str, args: list) -> object:
        wrapped = (
            "const [resolve] = [arguments[arguments.length - 1]];"
            "(async () => {" + script.replace("arguments[", "__args[") + "})().then(resolve, e => resolve({error: String(e)}));"
        )
        self.m.set_context("chrome")
        try:
            return self.m.execute_async("const __args = arguments;" + wrapped, args)
        finally:
            self.m.set_context("content")

    # -- tests ------------------------------------------------------------
    def test_01_start_page_renders_with_brand_and_facts(self):
        homepage = self.m.chrome("return Services.prefs.getStringPref('browser.startup.homepage');")
        self.assertTrue(homepage.startswith("file://"), homepage)
        self.assertIn(str(self.session.profile_dir), homepage.replace("file://", ""))
        self.m.navigate(homepage)
        self.assertEqual(self.m.title(), "Nulavio")
        text = self.m.execute("return document.body.innerText;")
        self.assertIn(self.session.profile_name, text)
        self.assertIn("uBlock Origin", text)
        # The stylesheet (and tokens) loaded under the page CSP.
        radius = self.m.execute("return getComputedStyle(document.querySelector('.card')).borderTopLeftRadius;")
        self.assertEqual(radius, "14px")
        symbol_ok = self.m.execute("const i = document.querySelector('.hero__symbol'); return i.complete && i.naturalWidth > 0;")
        self.assertTrue(symbol_ok, "brand symbol did not load")
        (self.artifacts / "startpage-light.png").write_bytes(self.m.screenshot_png())
        light_symbol = self.m.execute("return document.querySelector('.hero__symbol').currentSrc;")
        self.assertTrue(light_symbol.endswith("nulavio-symbol-dark-on-light.svg"), light_symbol)
        # Dark scheme: tokens and the symbol variant must follow the system preference.
        self.m.chrome("Services.prefs.setIntPref('layout.css.prefers-color-scheme.content-override', 0);")
        try:
            self.m.navigate(homepage)
            dark_symbol = self.m.execute("return document.querySelector('.hero__symbol').currentSrc;")
            self.assertTrue(dark_symbol.endswith("/nulavio-symbol.svg"), dark_symbol)
            canvas = self.m.execute("return getComputedStyle(document.documentElement).backgroundColor;")
            self.assertEqual(canvas, "rgb(11, 22, 35)")  # color.dark.bg.canvas #0B1623
            (self.artifacts / "startpage-dark.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.chrome("Services.prefs.clearUserPref('layout.css.prefers-color-scheme.content-override');")

    def test_02_baseline_prefs_are_applied_and_exist_in_engine(self):
        baseline = profile_mod.baseline_prefs()
        variables = {"STARTPAGE_URL": (self.session.profile_dir / "nulavio" / "startpage" / "index.html").as_uri()}
        state = self.m.chrome(PREF_READER, [[p.name for p in baseline]])
        unknown = [p.name for p in baseline if not state[p.name]["hasDefault"]]
        self.assertEqual(unknown, [], "prefs unknown to this engine (typo or removed upstream)")
        wrong = {
            p.name: (state[p.name]["value"], prefs_mod.substitute(p.value, variables))
            for p in baseline
            if state[p.name]["value"] != prefs_mod.substitute(p.value, variables)
        }
        self.assertEqual(wrong, {}, "baseline prefs not effective (actual, expected)")

    def test_03_tracking_protection_strict_is_effective(self):
        state = self.m.chrome(
            PREF_READER,
            [
                [
                    "privacy.trackingprotection.enabled",
                    "privacy.trackingprotection.socialtracking.enabled",
                    "network.cookie.cookieBehavior",
                ]
            ],
        )
        self.assertTrue(state["privacy.trackingprotection.enabled"]["value"])
        self.assertTrue(state["privacy.trackingprotection.socialtracking.enabled"]["value"])
        self.assertEqual(state["network.cookie.cookieBehavior"]["value"], 5)

    def test_04_content_processes_are_sandboxed(self):
        self.m.navigate(self.server.url("/page/sandbox-probe"))
        level = self.m.chrome(
            'return Cc["@mozilla.org/sandbox/sandbox-settings;1"]'
            ".getService(Ci.mozISandboxSettings).effectiveContentSandboxLevel;"
        )
        self.assertGreaterEqual(level, 4)
        parent = self.session.engine_pid()
        parent_ns = os.readlink(f"/proc/{parent}/ns/user")
        content = []
        for pid in harness.descendants(parent):
            try:
                info = harness.proc_info(pid)
            except OSError:
                continue
            if " -isForBrowser" in f" {info['cmd']} ":
                content.append(info)
        self.assertTrue(content, "no web content process found")

        def sandboxed(info: dict) -> bool:
            return all(v == 2 for v in info["seccomp"]) and info["userns"] != parent_ns

        def settled(pid: int) -> dict | None:
            try:
                info = harness.proc_info(pid)
            except OSError:
                return {"exited": True}
            return info if sandboxed(info) else None

        for info in content:
            if not sandboxed(info):
                # A content process caught in its first milliseconds has not applied
                # seccomp yet (measured ~30 ms, before any web content loads). Re-check;
                # a process that stays unsandboxed still fails.
                info = harness.wait_until(lambda pid=info["pid"]: settled(pid), timeout=3) or harness.proc_info(info["pid"])
                if info.get("exited"):
                    continue
            self.assertTrue(all(v == 2 for v in info["seccomp"]), f"seccomp filter missing on a thread of pid {info['pid']}")
            self.assertNotEqual(info["userns"], parent_ns, f"pid {info['pid']} shares the parent's user namespace")

    def test_05_navigation_and_tabs(self):
        self.m.navigate(self.server.url("/page/alpha"))
        self.assertEqual(self.m.title(), "alpha")
        first = self.m.send("WebDriver:GetWindowHandle")["value"]
        second = self.m.new_tab()
        self.m.switch_to(second)
        self.m.navigate(self.server.url("/page/beta"))
        # A freshly created tab can report the load before the title is set.
        self.assertTrue(harness.wait_until(lambda: self.m.title() == "beta", timeout=10), self.m.title())
        self.assertGreaterEqual(len(self.m.window_handles()), 2)
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(first)
        self.assertEqual(self.m.title(), "alpha")
        self.m.send("WebDriver:Back")
        self.m.send("WebDriver:Forward")
        self.assertEqual(self.m.title(), "alpha")

    def test_06_https_only_upgrades_and_exception_is_revocable(self):
        host = "nulavio-http.test"
        self.m.chrome("Services.prefs.setStringPref('network.dns.localDomains', arguments[0]);", [host])
        origin = f"http://{host}:{self.server.port}"
        url = f"{origin}/page/plain"

        def doc_uri() -> str:
            return self.m.execute("return document.documentURI;")

        def load(target: str) -> None:
            try:
                self.m.navigate(target)
            except MarionetteError as exc:  # navigating to an error page is reported as an error
                if "error page" not in str(exc).lower():
                    raise

        load(url)
        self.assertTrue(doc_uri().startswith("about:httpsonlyerror"), doc_uri())
        principal = "Services.scriptSecurityManager.createContentPrincipalFromOrigin(arguments[0])"
        self.m.chrome(
            f"Services.perms.addFromPrincipal({principal}, 'https-only-load-insecure', Services.perms.ALLOW_ACTION);", [origin]
        )
        load(url)
        self.assertEqual(self.m.title(), "plain")
        self.m.chrome(f"Services.perms.removeFromPrincipal({principal}, 'https-only-load-insecure');", [origin])
        load(url + "?again=1")
        self.assertTrue(doc_uri().startswith("about:httpsonlyerror"), doc_uri())

    def test_07_download_lands_privately(self):
        self.m.navigate(self.server.url("/page/download-start"))
        self.m.execute("location.href = arguments[0];", [self.server.url("/download")])
        target = self.session.downloads / "nulavio-fixture.bin"
        ok = harness.wait_until(lambda: target.exists() and target.read_bytes() == b"nulavio download fixture\n", timeout=20)
        self.assertTrue(ok, f"download not completed; dir has {list(self.session.downloads.iterdir())}")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o077, 0, "download readable by group/others")

    def test_08_ublock_blocks_and_is_reversible(self):
        registered = harness.wait_until(lambda: self.chrome_async(ADDON_STATE, [UBO_ID]), timeout=30)
        self.assertTrue(registered, "uBlock Origin was not registered by the engine")
        default_scopes = self.m.chrome(
            'return Services.prefs.getDefaultBranch("").getIntPref("extensions.autoDisableScopes", 0);'
        )
        if default_scopes & 1:
            # This engine (e.g. Mozilla's own build) asks the user before enabling extensions
            # added to the profile. Nulavio must never bypass that prompt.
            self.assertFalse(registered["active"], "sideloaded extension enabled without the engine's approval")
            self.assertTrue(registered["userDisabled"])
            self.assertTrue(self.chrome_async(ADDON_TOGGLE, [UBO_ID, True]), "approval (as the user) failed")
        state = harness.wait_until(lambda: (self.chrome_async(ADDON_STATE, [UBO_ID]) or {}).get("active"), timeout=30)
        self.assertTrue(state, "uBlock Origin is not active")

        counter = {"n": 0}

        def load_fixture() -> tuple[int, int]:
            counter["n"] += 1
            n = counter["n"]
            self.m.navigate(self.server.url(f"/ads-fixture?n={n}"))
            harness.wait_until(lambda: self.server.count(f"/assets/control.png?n={n}") >= 1, timeout=10)
            time.sleep(0.5)
            return self.server.count(f"/assets/control.png?n={n}"), self.server.count(f"/adbanners/nulavio-test.png?n={n}")

        # uBO compiles its bundled lists on first start; poll until filtering is live.
        blocked = harness.wait_until(lambda: load_fixture() == (1, 0), timeout=60, interval=1.0)
        self.assertTrue(blocked, f"ad image was not blocked; hits={self.server.hits[-6:]}")
        (self.artifacts / "adblock-fixture.png").write_bytes(self.m.screenshot_png())

        self.assertFalse(self.chrome_async(ADDON_TOGGLE, [UBO_ID, False]))
        control, ad = load_fixture()
        self.assertEqual((control, ad), (1, 1), "with uBO disabled the ad request should reach the server")

        self.assertTrue(self.chrome_async(ADDON_TOGGLE, [UBO_ID, True]))
        blocked_again = harness.wait_until(lambda: load_fixture() == (1, 0), timeout=30, interval=1.0)
        self.assertTrue(blocked_again, "re-enabling uBO did not restore blocking")

    def test_09_profile_files_are_private(self):
        offenders = []
        for root, dirs, files in os.walk(self.session.profile_dir):
            for name in dirs + files:
                path = Path(root) / name
                st = path.lstat()
                if stat.S_ISLNK(st.st_mode):
                    continue  # the engine's lock symlink
                if stat.S_IMODE(st.st_mode) & 0o077:
                    offenders.append(f"{stat.S_IMODE(st.st_mode):04o} {path.relative_to(self.session.profile_dir)}")
        self.assertEqual(offenders, [], "profile entries readable by group/others")
        mode = stat.S_IMODE(self.session.profile_dir.stat().st_mode)
        self.assertEqual(mode, 0o700)

    def test_10_guard_refuses_test_profile(self):
        # The harness overlay contains Marionette prefs: the real launcher must refuse it.
        result = self.session.nulavio("run", "--profile", self.session.profile_name, "--dry-run", check=False)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("marionette.port", result.stderr)

    def test_12_safe_browsing_has_api_key(self):
        # Without a Google Safe Browsing key the engine silently skips the phishing and
        # malware lists (SafeBrowsing.sys.mjs). Distribution builds ship one; a Nulavio
        # build must too before release. The key itself is never printed.
        has_key = self.m.chrome(
            'const k = Services.urlFormatter.formatURL("%GOOGLE_SAFEBROWSING_API_KEY%").trim();'
            'return Boolean(k) && k !== "no-google-safebrowsing-api-key";'
        )
        self.assertTrue(has_key, "engine built without a Google Safe Browsing key: phishing/malware lists inactive")

    def test_13_nulavio_build_identity_and_distribution(self):
        info = self.m.chrome("return {name: Services.appinfo.name, vendor: Services.appinfo.vendor};")
        if info["name"] != "Nulavio":
            self.skipTest("Track A engine (distribution Firefox)")
        state = self.m.chrome(
            'const d = Services.prefs.getDefaultBranch("");'
            "return {autoDisableScopes: d.getIntPref('extensions.autoDisableScopes', -1),"
            " requireSigning: Services.prefs.getBoolPref('xpinstall.signatures.required'),"
            " selfxss: d.getIntPref('devtools.selfxss.count', -1),"
            " policiesActive: Services.policies.status == Services.policies.ACTIVE,"
            " policyNames: Object.keys(Services.policies.getActivePolicies() || {}),"
            " distId: d.getStringPref('distribution.id', ''),"
            " httpsOnlyDefault: d.getBoolPref('dom.security.https_only_mode'),"
            " etpDefault: d.getStringPref('browser.contentblocking.category'),"
            " chromeDevtools: d.getBoolPref('devtools.chrome.enabled'),"
            " remoteDebugging: d.getBoolPref('devtools.debugger.remote-enabled'),"
            " dumpEnabled: d.getBoolPref('browser.dom.window.dump.enabled'),"
            " chromeStdout: d.getBoolPref('devtools.console.stdout.chrome'),"
            " sbLists: d.getStringPref('browser.safebrowsing.provider.google5.lists'),"
            " remoteDownloadCheck: d.getBoolPref('browser.safebrowsing.downloads.remote.enabled')};"
        )
        self.assertEqual(info["vendor"], "Nulavio")
        self.assertEqual(state["autoDisableScopes"], 15, "Track B must keep Mozilla's sideload approval prompt")
        self.assertTrue(state["requireSigning"])
        self.assertEqual(state["selfxss"], 0)
        self.assertTrue(state["policiesActive"], "distribution/policies.json missing (run make_distribution.py)")
        self.assertIn("ExtensionSettings", state["policyNames"])
        self.assertEqual(state["distId"], "nulavio")
        self.assertTrue(state["httpsOnlyDefault"])
        self.assertEqual(state["etpDefault"], "strict")
        # Non-official builds default these to true; Nulavio restores Mozilla's shipped values.
        for key in ("chromeDevtools", "remoteDebugging", "dumpEnabled", "chromeStdout"):
            self.assertFalse(state[key], f"{key} is on by default in this build")
        # Own Safe Browsing key: only the lists Google serves to it (docs/architecture/build.md).
        self.assertNotIn("goog-badbinurl-proto", state["sbLists"])
        self.assertNotIn("goog-downloadwhite-proto", state["sbLists"])
        self.assertIn("googpub-phish-proto", state["sbLists"])
        self.assertFalse(state["remoteDownloadCheck"], "remote download check needs a partner-only Google API")

    @unittest.skipUnless(
        os.environ.get("NULAVIO_NETWORK_TESTS") == "1", "set NULAVIO_NETWORK_TESTS=1 (contacts Google Safe Browsing)"
    )
    def test_14_safe_browsing_blocks_google_test_phishing_page(self):
        # End to end: download the phishing list from Google Safe Browsing (what the
        # browser does by itself, just sooner) and open Google's official test page.
        # It must be replaced by the "deceptive site" warning.
        # The local list name depends on the build: Mozilla-official builds (and
        # distributions such as Fedora's) use "goog-phish-proto", other builds such as
        # Nulavio use "googpub-phish-proto". With the v5 protocol both map to Google's
        # single social-engineering list.
        self.m.send("WebDriver:SetTimeouts", {"script": 150_000})
        try:
            state = self.chrome_async(
                """
                const lm = Cc["@mozilla.org/url-classifier/listmanager;1"].getService(Ci.nsIUrlListManager);
                const db = Cc["@mozilla.org/url-classifier/dbservice;1"].getService(Ci.nsIUrlClassifierDBService);
                const table = Services.prefs.getStringPref("urlclassifier.phishTable").split(",")
                  .find(t => /^goog(pub)?-phish-proto$/.test(t));
                const tables = () => new Promise(r => db.getTables(r));
                const has = t => t.split("\\n").some(l => l.startsWith(table + ";") && l.length > table.length + 10);
                let forced = false;
                for (let i = 0; i < 240 && !has(await tables()); i++) {
                  if (!forced) forced = lm.forceUpdates(table);
                  await new Promise(r => setTimeout(r, 500));
                }
                const v5 = Services.prefs.getBoolPref("browser.safebrowsing.provider.google5.enabled", false);
                const all = await tables();
                return {table, forced, listReady: has(all), malwareReady: all.includes("goog-malware-proto;"),
                        provider: v5 ? "google5" : "google4"};
                """,
                [],
            )
        finally:
            self.m.send("WebDriver:SetTimeouts", {"script": 30_000})
        self.assertTrue(state.get("listReady"), f"phishing list not downloaded: {state}")
        # Lists are fetched in one batch per provider; the malware list proves the batch succeeded.
        self.assertTrue(state.get("malwareReady"), f"malware list not downloaded: {state}")
        try:
            self.m.navigate("https://testsafebrowsing.appspot.com/s/phishing.html")
        except MarionetteError as exc:
            self.assertIn("about:blocked", str(exc))  # Marionette reports the error page it reached
        uri = self.m.execute("return document.documentURI;")
        self.assertTrue(uri.startswith("about:blocked"), uri)
        self.assertIn("e=deceptiveBlocked", uri)
        self.m.navigate("about:blank")

    def test_11_record_environment(self):
        info = self.m.chrome(
            "return {version: Services.appinfo.version, buildID: Services.appinfo.appBuildID, os: Services.appinfo.OS,"
            " widget: Services.appinfo.widgetToolkit, fission: Services.appinfo.fissionAutostart};"
        )
        self.assertTrue(info["fission"], "site isolation (Fission) is off")
        (self.artifacts / "engine.json").write_text(json.dumps(info, indent=2))


if __name__ == "__main__":
    unittest.main()
