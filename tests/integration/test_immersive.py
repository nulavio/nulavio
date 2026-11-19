"""ADR 0009: Immersive. The toolbar and the tab list leave the view; the band stays, with the site.

The window decides where the mode applies: never where the band cannot name the page, never in a
pop-up, never while a device is shared; and a panel anchored on the toolbar keeps it shown."""

from __future__ import annotations

import itertools
import time
import unittest

import harness
import settings_page

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
# The window: whether Immersive is drawn, why not, what holds the chrome, and what is really in view.
WINDOW = """
const root = document.documentElement;
const bar = getComputedStyle(document.getElementById("nav-bar"));
const origin = document.querySelector("#nulavio-band .nv-band-origin");
return {
  on: root.hasAttribute("nulavio-immersive"),
  off: root.getAttribute("nulavio-immersive-off"),
  hold: root.getAttribute("nulavio-immersive-hold"),
  toolbar: bar.opacity === "1" && bar.pointerEvents !== "none",
  band: document.getElementById("nulavio-band").getBoundingClientRect().height > 0,
  origin: origin && origin.checkVisibility() ? origin.textContent : null,
};
"""

# The engine's security cues of the address bar (the list of test_horizon 07, with the identity box): how each is
# drawn, and where. Immersive must change none of them; it only takes the toolbar they sit in out of view.
CUES = """
const view = document.documentElement.getBoundingClientRect();
return ["identity-box", "trust-icon-container", "tracking-protection-icon-container", "identity-permission-box",
        "remote-control-box", "notification-popup-box"].map(id => {
  const e = document.getElementById(id);
  if (!e) return { id, missing: true };
  const style = getComputedStyle(e), box = e.getBoundingClientRect();
  return { id, display: style.display, visibility: style.visibility, opacity: style.opacity,
           width: Math.round(box.width), height: Math.round(box.height),
           inside: box.width > 0 && box.top >= view.top && box.bottom <= view.bottom };
});
"""
# What the band says while the toolbar is away: who, how protected, which site, and what the engine thinks of the
# connection (its own verdict: the identity box's classes).
BAND = """
const band = document.getElementById("nulavio-band");
const text = name => {
  const e = band.querySelector(`.nv-band-${name}`);
  return e && e.checkVisibility() ? e.textContent.trim() : null;
};
const origin = band.querySelector(".nv-band-origin");
return { name: text("name"), protection: text("protection"), host: text("origin-host"), state: text("origin-state"),
         secure: origin.getAttribute("data-secure"), label: origin.getAttribute("aria-label"),
         engine: [...document.getElementById("identity-box").classList] };
"""

# Hold the request for one address before it leaves, as a site that is slow to answer does; and let it go.
HOLD = """
const held = (window.nvHeld = { address: arguments[0], channel: null });
window.nvHold = { observe(subject) {
  const channel = subject.QueryInterface(Ci.nsIHttpChannel);
  if (channel.URI.spec === held.address && !held.channel) { channel.suspend(); held.channel = channel; }
} };
Services.obs.addObserver(window.nvHold, "http-on-modify-request");
"""
RELEASE = """
if (window.nvHold) { Services.obs.removeObserver(window.nvHold, "http-on-modify-request"); delete window.nvHold; }
if (window.nvHeld?.channel) { window.nvHeld.channel.resume(); }
delete window.nvHeld;
"""
# The selected tab: the address the engine shows for it, and the document that is really in it.
DOCUMENT = """
const browser = gBrowser.selectedBrowser;
return { shown: browser.currentURI.spec, there: browser.browsingContext.currentWindowGlobal?.documentURI?.spec ?? null };
"""


# #238: the toolbar and the side tab list as drawn: where each box is, and whether it is in view (shown, not slid out).
PARTS = """
const box = id => {
  const e = document.getElementById(id), b = e.getBoundingClientRect(), s = getComputedStyle(e);
  return { left: b.left, top: b.top, right: b.right, bottom: b.bottom,
           shown: b.width > 0 && b.right > 0 && b.left < innerWidth && s.opacity !== "0" && s.visibility !== "hidden" };
};
return { toolbar: box("nav-bar"), tabs: box("sidebar-container"), band: box("nulavio-band") };
"""
EDGE = "window.synthesizeMouseEvent('mousemove', 2, Math.round(innerHeight / 2), {}, {});"
AWAY = "window.synthesizeMouseEvent('mousemove', Math.round(innerWidth / 2), Math.round(innerHeight / 2), {}, {});"


# #239: where a click lands, by what is drawn there; and a click there through the window (as a person's).
CLICK_AT = """
const [x, y] = arguments[0];
window.synthesizeMouseEvent('mousedown', x, y, {button: 0, clickCount: 1}, {});
window.synthesizeMouseEvent('mouseup', x, y, {button: 0, clickCount: 1}, {});
"""
SPOTS = """
const box = id => document.getElementById(id).getBoundingClientRect();
const page = box('browser'), band = box('nulavio-band'), tabs = box('sidebar-container');
// A point of the band that is not one of its controls (they decide where the keyboard goes themselves).
let free = null;
for (let x = band.right - 4; x > band.left && !free; x -= 6) {
  const e = document.elementFromPoint(x, band.top + band.height / 2);
  const control = e?.closest('button, toolbarbutton, [role=button], a');
  if (e && document.getElementById('nulavio-band').contains(e) && !control) free = [x, band.top + band.height / 2];
}
return { page: [page.left + page.width / 2, page.top + page.height * 0.6], band: free,
         tabs: [tabs.left + tabs.width / 2, tabs.top + tabs.height * 0.7] };
"""
FOCUS = "return { urlbar: gURLBar.focused, active: document.activeElement?.id || document.activeElement?.localName };"
# #118: the band's pin, as drawn.
PIN = """
const pin = document.querySelector('#nulavio-band .nv-band-pin');
const box = pin?.getBoundingClientRect();
return { shown: !!pin && pin.checkVisibility(), pressed: pin?.getAttribute('aria-pressed') ?? null,
         label: pin?.getAttribute('aria-label') ?? null, size: box ? [Math.round(box.width), Math.round(box.height)] : null };
"""
PRESS_PIN = "document.querySelector('#nulavio-band .nv-band-pin').click();"

# #344: every frame while the pointer moves, the boxes of the band, the toolbar, the tab list, the assistant's panel
# and the page ([left, top, right, bottom, opacity, in view]), what holds the chrome and where the pointer is.
TRACE = """
const t = window.nvTrace = { frames: [], x: -1, y: -1, on: true };
if (!window.nvTraceMove) {
  window.nvTraceMove = e => { if (window.nvTrace) { window.nvTrace.x = e.clientX; window.nvTrace.y = e.clientY; } };
  addEventListener('mousemove', window.nvTraceMove, true);
}
const box = id => {
  const e = document.getElementById(id), b = e.getBoundingClientRect(), s = getComputedStyle(e);
  // The bounds as they are, and last the right side as far as the window goes: a part past the right edge (#346, the
  // tab list on the right) is out of view as one past the left edge is, and a page that grows past it still moved.
  return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom), +s.opacity,
          e.checkVisibility() ? 1 : 0, Math.round(Math.min(b.right, innerWidth))];
};
const tick = () => {
  if (!t.on) return;
  t.frames.push({ x: t.x, y: t.y, hold: document.documentElement.getAttribute('nulavio-immersive-hold'),
    band: box('nulavio-band'), toolbar: box('nav-bar'), tabs: box('sidebar-container'), panel: box('sidebar-box'),
    page: box('tabbrowser-tabbox') });
  if (t.frames.length < 5000) requestAnimationFrame(tick);
};
requestAnimationFrame(tick);
"""
TRACE_END = "window.nvTrace.on = false; return window.nvTrace.frames;"
# Two more frames drawn, so the trace's last frame is of the window as it is now. Without it, a trace ended right
# after a change could end on a frame from before the change (the 160.0-0.6 release run did, on a fast machine).
TRACE_DRAWN = (
    "const done = arguments[arguments.length - 1]; requestAnimationFrame(() => requestAnimationFrame(() => done(true)));"
)
STILL = "return !document.getAnimations().some(a => a.playState === 'running');"  # no transition running in the window
# #344: the assistant's panel the journeys run with: none, Nulavio's (the Shell's sidebar action) or a site's (the
# engine's AI chatbot panel, on a page of the fixture).
PANELS = {
    "none": "SidebarController.hide();",
    "nulavio": "SidebarController.show('shell_nulavio_net-sidebar-action');",
    "site": "Services.prefs.setBoolPref('browser.ml.chat.enabled', true);"
    " Services.prefs.setStringPref('browser.ml.chat.provider', arguments[0]);"
    " SidebarController.show('viewGenaiChatSidebar');",
}


# #346: the side panel on the other side of the page (#527): the setting, the assistant's panel, and the panel as drawn
# ([left, right] of the box, whether it is in view), with the page's box and the frame margin.
OPPOSITE = "nulavio.sidebar.panelOpposite"
ASSISTANT = "shell_nulavio_net-sidebar-action"
PANEL = """
const e = document.getElementById("sidebar-box"), b = e.getBoundingClientRect(), s = getComputedStyle(e);
const page = gBrowser.selectedBrowser.closest(".browserContainer").getBoundingClientRect();
const frame = getComputedStyle(document.documentElement).getPropertyValue("--nulavio-frame-margin").trim();
return { box: [Math.round(b.left), Math.round(b.right)], page: [Math.round(page.left), Math.round(page.right)],
         shown: e.checkVisibility() && b.width > 0 && b.right > 2 && b.left < innerWidth - 2 && s.opacity !== "0",
         frame: frame ? Math.round(parseFloat(frame)) : 0,
         opposite: document.documentElement.hasAttribute("nulavio-panel-opposite") };
"""


def pointer_path(points: list[tuple[int, ...]], pause_ms: int = 0) -> list[dict]:
    """A pointer moving through `points` in 8 px steps at 60 Hz, as a hand moves it, resting `pause_ms` at each
    point, or as long as the point's third number says."""
    actions = []
    for start, end in itertools.pairwise(points):
        (x0, y0), (x1, y1) = start[:2], end[:2]
        steps = max(1, round(max(abs(x1 - x0), abs(y1 - y0)) / 8))
        for i in range(1, steps + 1):
            actions.append(
                {
                    "type": "pointerMove",
                    "duration": 16,
                    "origin": "viewport",
                    "x": round(x0 + (x1 - x0) * i / steps),
                    "y": round(y0 + (y1 - y0) * i / steps),
                }
            )
        rest = end[2] if len(end) > 2 else pause_ms
        if rest:
            actions.append({"type": "pause", "duration": rest})
    return actions


def visible(part: list) -> bool:
    right = part[6] if len(part) > 6 else part[2]  # within the window (TRACE's last number)
    return part[5] == 1 and part[4] > 0.05 and right > part[0] + 2 and right > 2 and part[3] > part[1]


def covers(a: list, b: list) -> bool:
    """Two parts in view with more than a pixel in common."""
    return visible(a) and visible(b) and min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


@unittest.skipUnless(harness.nulavio_engine(), "Immersive needs the built-in Shell on the engine")
class ImmersiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Imersivo")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/page/Imersivo")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.page)
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def window(self):
        return self.m.chrome(WINDOW)

    def trace_end(self) -> list:
        """The frames of the trace begun with TRACE, the last of them drawn after whatever the test did last."""
        self.m.set_context("chrome")
        try:
            self.m.execute_async(TRACE_DRAWN)
        finally:
            self.m.set_context("content")
        return self.m.chrome(TRACE_END)

    def plain_http(self, *hosts: str) -> None:
        """Names that are not this computer answered by the fixture over plain http: resolved here, with the
        per-site HTTPS-Only exception a person gives on the engine's warning. HTTPS-Only itself stays on."""
        self.m.chrome(
            "Services.prefs.setStringPref('network.dns.localDomains', arguments[0].join(','));"
            "for (const host of arguments[0]) {"
            "  const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(`http://${host}:${arguments[1]}`);"
            "  Services.perms.addFromPrincipal(p, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION);"
            "}",
            [list(hosts), self.server.port],
        )
        self.addCleanup(
            self.m.chrome,
            "Services.prefs.clearUserPref('network.dns.localDomains');"
            "for (const host of arguments[0]) {"
            "  const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(`http://${host}:${arguments[1]}`);"
            "  Services.perms.removeFromPrincipal(p, 'https-only-load-insecure');"
            "}",
            [list(hosts), self.server.port],
        )

    def settled(self, want: bool) -> dict:
        """The toolbar in (or out of) view, after its transition and its hold time."""
        harness.wait_until(lambda: self.window()["toolbar"] is want, 6)
        return self.window()

    def test_01_off_unless_the_person_turns_it_on(self):
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        state = self.settled(True)
        self.assertEqual((state["on"], state["off"], state["toolbar"]), (False, None, True), state)

    def test_02_the_band_stays_with_the_site_and_its_port(self):
        state = self.settled(False)
        self.assertTrue(state["band"], state)
        self.assertFalse(state["toolbar"], state)
        self.assertIn(f"127.0.0.1:{self.server.port}", state["origin"], "the site, with its port, is in the band")
        # One key brings the address back with the keyboard in it; leaving it lets the toolbar go.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertFalse(self.settled(False)["toolbar"])

    def test_03_a_page_the_band_cannot_name_keeps_the_full_window(self):
        for address in ("about:blank", "about:blank#x", "about:blank?x", "data:text/html,<h1>x</h1>", f"view-source:{self.page}"):
            with self.subTest(address=address):
                self.m.chrome(
                    "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
                    " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
                    [address],
                )
                # The tab shows this address (the reason is "page" from the address before as well, and the next
                # load would overtake one that had not begun).
                shown = lambda address=address: self.m.chrome(DOCUMENT)["shown"] == address  # noqa: E731
                self.assertTrue(harness.wait_until(shown, 10), (address, self.m.chrome(DOCUMENT)))
                self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "page", 10), self.window())
                state = self.settled(True)
                self.assertEqual((state["on"], state["toolbar"]), (False, True), state)
        # Back to a site, loaded as the addresses above were.
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            [self.page],
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(DOCUMENT)["there"] == self.page, 15), self.m.chrome(DOCUMENT))
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), (self.window(), self.m.chrome(DOCUMENT)))

    def test_04_a_panel_on_the_toolbar_holds_it_and_a_menu_on_the_page_does_not(self):
        self.assertFalse(self.settled(False)["toolbar"])
        # A permission request: the browser shows the toolbar itself, for as long as its panel is open.
        self.m.execute("navigator.geolocation.getCurrentPosition(() => {}, () => {});")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"], "the toolbar is not shown under the permission request")
        self.m.chrome("PopupNotifications.remove(PopupNotifications.getNotification('geolocation', gBrowser.selectedBrowser));")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        # The application menu, anchored on its button.
        self.m.chrome("PanelUI.show();")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome("PanelUI.hide();")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())
        # A menu opened on the page is the page's business: nothing comes into view.
        self.m.chrome(
            "const menu = document.getElementById('contentAreaContextMenu');"
            "menu.openPopupAtScreen(window.screenX + 400, window.screenY + 400, true);"
        )
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('contentAreaContextMenu').state;") == "open", 10
            )
        )
        state = self.window()
        self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        self.assertEqual((state["hold"], state["toolbar"]), (None, False), state)

    def test_05_a_window_without_the_full_toolbar_is_never_immersive(self):
        before = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome(
            "window.openDialog(AppConstants.BROWSER_CHROME_URL, '_blank', 'chrome,dialog=no,location,width=480,height=360',"
            " arguments[0]);",
            [self.page],
        )
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 20))
        self.m.switch_to((set(self.m.window_handles()) - before).pop())
        try:
            self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "popup", 15), self.window())
            self.assertFalse(self.window()["on"])
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)

    def test_06_while_a_device_is_shared_the_toolbar_stays(self):
        # The engine's test mode for capture (fake devices, no prompt) bypasses its own sharing indicators, so the
        # state is set where the engine sets it for a real capture: the tab's sharing state (updateBrowserSharing).
        share = "gBrowser.updateBrowserSharing(gBrowser.selectedBrowser, {webRTC: arguments[0]});"
        self.m.chrome(share, [{"sharing": "microphone", "microphone": 1, "camera": 0, "screen": "", "paused": False}])
        self.addCleanup(self.m.chrome, share, [None])
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "sharing", 15), self.window())
        state = self.settled(True)
        self.assertEqual((state["on"], state["toolbar"]), (False, True), state)
        # A tab in the background that shares keeps the toolbar too.
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [self.page])
        self.addCleanup(self.m.chrome, "while (gBrowser.tabs.length > 1) gBrowser.removeTab(gBrowser.tabs.at(-1));")
        harness.wait_until(lambda: self.m.chrome("return !gBrowser.selectedBrowser.webProgress.isLoadingDocument;"), 15)
        self.assertEqual(self.window()["off"], "sharing", self.window())
        # A capture that is paused is still a capture: the tab's mark may go, the browser's state stays.
        self.m.chrome(
            "const first = gBrowser.tabs[0];"
            "gBrowser.updateBrowserSharing(first.linkedBrowser, {webRTC: {sharing: 'microphone', paused: true}});"
            "first.removeAttribute('sharing'); gBrowser._tabAttrModified(first, ['sharing']);"
        )
        self.assertEqual(self.window()["off"], "sharing", self.window())
        self.m.chrome("gBrowser.updateBrowserSharing(gBrowser.tabs[0].linkedBrowser, {webRTC: null});")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())

    def test_06b_a_prompt_on_the_tab_brings_the_full_window_back(self):
        """Independent review (2026-11-11): the engine's tab prompts are not panels. For a cross-site HTTP
        authentication request it rewrites the address bar to the site that asks; that must be in view."""
        self.assertFalse(self.settled(False)["toolbar"])
        # A dialog in the engine's tab dialog box, where its prompts live. (Not an alert: the test driver
        # dismisses those by itself.)
        self.m.chrome(
            "gBrowser.getTabDialogBox(gBrowser.selectedBrowser).open('chrome://global/content/aboutAbout.html',"
            " {features: 'resizable=no', modalType: Services.prompt.MODAL_TYPE_TAB});"
        )
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "prompt", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"], "the toolbar is not shown under a tab prompt")
        self.m.chrome("gBrowser.selectedBrowser.tabDialogBox.getTabDialogManager().abortDialogs();")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        # The state the engine sets for a cross-site authentication request, before its dialog opens.
        mark = "gBrowser.selectedBrowser.currentAuthPromptURI = arguments[0] ? Services.io.newURI(arguments[0]) : null;"
        refresh = "gBrowser.tabContainer.dispatchEvent(new CustomEvent('TabSelect', {bubbles: true}));"
        self.m.chrome(mark + refresh, ["https://other.example/"])
        self.addCleanup(self.m.chrome, mark + refresh, [None])
        self.assertEqual(self.window()["off"], "prompt", self.window())
        self.m.chrome(mark + refresh, [None])
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def test_06c_a_download_that_needs_attention_keeps_the_toolbar(self):
        self.assertFalse(self.settled(False)["toolbar"])
        button = "document.getElementById('downloads-button')"
        self.m.chrome(f"{button}.setAttribute('attention', 'severe');")
        self.addCleanup(self.m.chrome, f"{button}.removeAttribute('attention');")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome(f"{button}.setAttribute('attention', 'success');")  # a finished download is no warning
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())

    def test_07_the_switch_and_the_key_write_one_pref_and_say_so(self):
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        said = self.m.chrome(
            f"const said = []; const L = {LAYOUT};"
            "const off = L.setImmersive(false, key => said.push(key)); const on = L.setImmersive(true, key => said.push(key));"
            "return [off, on, said];"
        )
        self.assertEqual(
            said, [{"on": False, "locked": False}, {"on": True, "locked": False}, ["layoutImmersiveOff", "layoutImmersiveOn"]]
        )
        self.assertTrue(self.m.chrome(pref))
        # Locked by an administrator: nothing changes, and the reason is said.
        refused = self.m.chrome(
            f"const L = {LAYOUT}; Services.prefs.lockPref('nulavio.layout.immersive'); const said = [];"
            "try { L.setImmersive(false, key => said.push(key)); return 'changed'; } catch (e) { return [e.code, said]; }"
            "finally { Services.prefs.unlockPref('nulavio.layout.immersive'); }"
        )
        self.assertEqual(refused, ["layout-locked", ["layoutLocked"]])
        self.assertTrue(self.m.chrome(pref))

    def test_07b_the_view_menu_turns_it_on_and_off_and_shows_a_lock(self):
        # #167: a menu item next to Full Screen, reading the switch each time the menu opens.
        item = (
            "const popup = document.getElementById('menu_viewPopup');"
            "const item = document.getElementById('nulavio-menu-immersive');"
            "popup.dispatchEvent(new Event('popupshowing'));"
            "const seen = item && { next: item.nextElementSibling?.id, parent: item.parentNode.id,"
            "  label: item.getAttribute('label'),"
            "  type: item.getAttribute('type'), checked: item.getAttribute('checked'), disabled: item.hasAttribute('disabled') };"
            "popup.dispatchEvent(new Event('popuphidden'));"  # the menu closed again: no hold is left behind
            "return seen;"
        )
        shown = self.m.chrome(item)
        self.assertEqual(
            (shown["parent"], shown["next"], shown["type"], shown["checked"], shown["disabled"]),
            ("menu_viewPopup", "fullScreenItem", "checkbox", "true", False),
            shown,
        )
        self.assertIn(shown["label"], ("Imersivo", "Immersive"))
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        self.m.chrome("document.getElementById('nulavio-menu-immersive').doCommand();")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 5))
        state = self.settled(True)
        self.assertTrue(state["toolbar"], state)
        self.assertEqual(self.m.chrome(item)["checked"], "false")
        self.m.chrome("document.getElementById('nulavio-menu-immersive').doCommand();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 5))
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        # Locked by an administrator: shown with the state in effect (a lock gives the pref its default value, off),
        # disabled, and a command changes nothing.
        self.m.chrome("Services.prefs.lockPref('nulavio.layout.immersive');")
        self.addCleanup(self.m.chrome, "Services.prefs.unlockPref('nulavio.layout.immersive');")
        self.assertFalse(self.m.chrome(pref))
        locked = self.m.chrome(item)
        self.assertEqual((locked["checked"], locked["disabled"]), ("false", True), locked)
        self.m.chrome("document.getElementById('nulavio-menu-immersive').doCommand();")
        self.assertFalse(self.m.chrome(pref))
        self.assertEqual(self.m.chrome(item)["checked"], "false")

    def test_08_the_switch_in_settings_turns_it_on_and_off(self):
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        # The switch is in the settings page's Aparência pane, under the arrangement (ADR 0009, ADR 0011).
        settings_page.open_pane(self.m, "appearance")
        off = lambda now: now["shown"] and not now["pressed"] and not now["disabled"]  # noqa: E731
        settings_page.wait_control(self.m, "nulavio-immersive", off, timeout=15)
        marked = settings_page.DOC + 'return d.getElementById("nulavio-immersive").dataset.option;'
        self.assertEqual(self.m.chrome(marked), "immersive")
        settings_page.click(self.m, "#nulavio-immersive")
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        # The settings page is the browser's own page: the mode applies while it is in front, as on any page.
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        settings_page.click(self.m, "#nulavio-immersive")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 10))
        self.assertTrue(self.settled(True)["toolbar"])

    def test_09_the_security_cues_are_the_engines_with_the_mode_on(self):
        """The security-visibility matrix with Immersive on (ADR 0009's accepted exception, issue #118). Out of view,
        no cue is restyled and the band says who, how protected, which site and what the engine thinks of the
        connection; back in view, every cue is drawn exactly as with the mode off."""

        def cues() -> dict:
            return {cue["id"]: cue for cue in self.m.chrome(CUES)}

        def drawn(now: dict) -> dict:
            return {name: (cue.get("display"), cue.get("visibility"), cue.get("opacity")) for name, cue in now.items()}

        def sized(now: dict) -> dict:
            return {name: (cue.get("width"), cue.get("height"), cue.get("inside")) for name, cue in now.items()}

        # Off: the engine's own drawing, the reference.
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(self.settled(True)["toolbar"])
        reference = cues()
        self.assertTrue(reference["trust-icon-container"]["inside"], reference)
        # On, the toolbar away: nothing about a cue changed (the toolbar is moved and made transparent as a whole),
        # and the band carries what the address bar said.
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertEqual(drawn(cues()), drawn(reference))
        band = self.m.chrome(BAND)
        self.assertEqual(band["name"], "Imersivo", band)  # the profile
        self.assertTrue(band["protection"], band)  # its protection, in words
        self.assertEqual(band["host"], f"127.0.0.1:{self.server.port}", band)
        self.assertIn("localResource", band["engine"], band)  # the engine's verdict for this page...
        self.assertEqual((band["state"] or "", band["secure"]), ("", "true"), band)  # ...and the band's: no warning
        # On, the toolbar back by the keyboard: every cue as with the mode off, same place and size.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        back = cues()
        self.assertEqual(drawn(back), drawn(reference))
        self.assertEqual(sized(back), sized(reference))
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertFalse(self.settled(False)["toolbar"])
        # A connection the engine calls not secure (plain http to a name that is not this computer): with the
        # toolbar away, the band says so in words, before the site's name.
        host = "nulavio-plain.test"
        self.plain_http(host)
        self.m.navigate(f"http://{host}:{self.server.port}/page/Imersivo")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["host"] == f"{host}:{self.server.port}", 10))
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        plain = self.m.chrome(BAND)
        self.assertIn("notSecure", plain["engine"], plain)
        self.assertEqual(plain["secure"], "false", plain)
        words = "return WebExtensionPolicy.getByID('shell@nulavio.net').extension.localizeMessage(...arguments);"
        self.assertEqual(plain["state"], self.m.chrome(words, ["bandOriginNotSecure"]), plain)
        self.assertIn(self.m.chrome(words, ["bandOriginNamedNotSecure", [plain["host"]]]), plain["label"], plain)
        # The band follows the engine's verdict, read from the identity box: "verified" is fine, and "verified" by
        # an exception the person added is not (the engine draws a warning on that padlock). No test server has a
        # certificate, so the verdict is put on the box as the engine would write it.
        verdict = "document.getElementById('identity-box').className = arguments[0];"
        self.m.chrome(verdict, ["verifiedDomain"])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["secure"] == "true", 6), self.m.chrome(BAND))
        self.assertFalse(self.m.chrome(BAND)["state"], "a verified site carries no warning in words")
        self.m.chrome(verdict, ["verifiedDomain mixedActiveBlocked"])
        self.assertEqual(self.m.chrome(BAND)["secure"], "true")
        self.assertTrue(self.window()["on"])
        # A connection the engine found broken is neither: an exception the person added to a certificate, mixed
        # content that was loaded, a weak cipher, or a verdict nobody here knows. The band still says it is not
        # secure, and the toolbar stays, with the engine's own indicators (ADR 0009, decision 6; #142).
        for broken in (
            "verifiedDomain certUserOverridden",
            "unknownIdentity mixedActiveContent",
            "unknownIdentity weakCipher",
            "somethingNew",
        ):
            with self.subTest(verdict=broken):
                self.m.chrome(verdict, [broken])
                self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "connection", 6), self.window())
                self.assertEqual(self.m.chrome(BAND)["secure"], "false")
                self.assertTrue(self.settled(True)["toolbar"])
                self.m.chrome(verdict, ["verifiedDomain"])
                self.assertTrue(harness.wait_until(lambda: self.window()["on"], 6), self.window())
        self.m.chrome(verdict, [" ".join(plain["engine"])])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["state"] == plain["state"], 6))
        self.assertFalse(self.settled(False)["toolbar"])
        away = cues()
        # And its warning in the address bar is the engine's, untouched, once the toolbar is back.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        warned = cues()
        self.assertTrue(warned["trust-icon-container"]["inside"], warned)
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(self.settled(True)["toolbar"])
        off = cues()
        self.assertEqual(drawn(away), drawn(off))
        self.assertEqual(drawn(warned), drawn(off))
        self.assertEqual(sized(warned), sized(off))

    def test_10_a_tab_being_restored_keeps_the_toolbar_until_its_document_is_there(self):
        """ADR 0009, decision 6: a restored preference alone hides nothing. A tab that session restore left unloaded
        shows its address as soon as it is selected, and its document only when the site answers: until then the
        page is still about:blank, and the band would name a site that is not there. The toolbar stays."""
        address = self.server.url("/page/Restaurada")
        self.m.chrome(HOLD, [address])
        self.addCleanup(self.m.chrome, RELEASE)
        self.addCleanup(
            self.m.chrome,
            "gBrowser.selectedTab = gBrowser.tabs[0];"
            " if (window.nvLazy) { gBrowser.removeTab(window.nvLazy); delete window.nvLazy; }",
        )
        self.m.chrome("window.nvLazy = gBrowser.addTrustedTab(arguments[0], { createLazyBrowser: true });", [address])
        self.assertTrue(self.window()["on"], "an unloaded tab in the background changes nothing")
        self.m.chrome("gBrowser.selectedTab = window.nvLazy;")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return Boolean(window.nvHeld.channel);"), 15), "not asked for")
        self.assertEqual(self.m.chrome(DOCUMENT), {"shown": address, "there": "about:blank"})
        waiting = self.settled(True)
        self.assertEqual((waiting["on"], waiting["off"], waiting["toolbar"]), (False, "page", True), waiting)
        # The site answers: its document is there, the band names it, and the mode applies.
        self.m.chrome("window.nvHeld.channel.resume(); window.nvHeld.channel = null;")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())
        self.assertEqual(self.m.chrome(DOCUMENT), {"shown": address, "there": address})
        self.assertEqual(self.m.chrome(BAND)["host"], f"127.0.0.1:{self.server.port}")

    def test_11_an_error_page_keeps_the_full_window(self):
        """An error page keeps the address of what failed, and the document is the engine's own page about it: the
        band cannot say that site is what is on screen, so the toolbar stays."""
        refused = "http://127.0.0.1:1/"  # nothing listens there
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            [refused],
        )
        failed = lambda: (self.m.chrome(DOCUMENT)["there"] or "").startswith("about:neterror")  # noqa: E731
        self.assertTrue(harness.wait_until(failed, 15), self.m.chrome(DOCUMENT))
        self.assertEqual(self.m.chrome(DOCUMENT)["shown"], refused)
        state = self.settled(True)
        self.assertEqual((state["on"], state["off"], state["toolbar"]), (False, "page", True), state)
        # The band's name for an IPv6 address has its brackets: without them its last group and a port read as one.
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            ["http://[::1]:1/"],
        )
        named = "return document.querySelector('#nulavio-band .nv-band-origin-host').textContent;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(named) == "[::1]:1", 15), self.m.chrome(named))
        self.m.navigate(self.page)
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def test_12_a_notification_bar_keeps_the_toolbar_and_is_seen(self):
        """The engine's notification bars (a blocked pop-up, a page opened past a Safe Browsing warning) and the
        Guard's sit in a toolbar of their own under the address bar. Immersive takes the toolbars out of view: while
        one of those bars is shown, in the window or on the selected tab, they stay, and so does the bar."""
        seen = """
        const bar = document.getElementById("notifications-toolbar");
        const note = (arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox())
          .getNotificationWithValue("nulavio-test");
        const style = getComputedStyle(bar), box = note?.getBoundingClientRect();
        return { there: Boolean(note), opacity: style.opacity, events: style.pointerEvents,
                 inside: Boolean(box) && box.height > 0 && box.top >= 0 && box.bottom <= window.innerHeight };
        """
        show = """
        const box = arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox();
        box.appendNotification("nulavio-test", { label: "Nulavio test", priority: box.PRIORITY_WARNING_MEDIUM }, []);
        """
        close = """
        (arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox())
          .getNotificationWithValue("nulavio-test")?.close();
        """
        in_view = lambda bar: bar["inside"] and bar["opacity"] == "1"  # noqa: E731
        self.assertFalse(self.settled(False)["toolbar"])
        for where in ("window", "tab"):
            with self.subTest(where=where):
                self.addCleanup(self.m.chrome, close, [where])
                self.m.chrome(show, [where])
                state = self.settled(True)
                self.assertEqual((state["on"], state["toolbar"]), (True, True), state)
                self.assertTrue(harness.wait_until(lambda where=where: in_view(self.m.chrome(seen, [where])), 6))
                self.assertEqual(self.m.chrome(seen, [where])["events"], "auto")
                if where == "tab":
                    # A bar on a tab in the background holds nothing; back on its tab, it does again.
                    first = self.m.chrome("return gBrowser.tabs.indexOf(gBrowser.selectedTab);")
                    self.addCleanup(
                        self.m.chrome,
                        "if (window.nvOther) { gBrowser.removeTab(window.nvOther); delete window.nvOther; }",
                    )
                    self.m.chrome(
                        "window.nvOther = gBrowser.addTrustedTab(arguments[0]); gBrowser.selectedTab = window.nvOther;",
                        [self.server.url("/page/Outra")],
                    )
                    self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())
                    self.m.chrome("gBrowser.selectedBrowser.focus();")
                    self.assertFalse(self.settled(False)["toolbar"], "a bar on another tab kept this one's toolbar")
                    self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[arguments[0]];", [first])
                    self.assertTrue(self.settled(True)["toolbar"])
                self.m.chrome(close, [where])
                self.m.chrome("gBrowser.selectedBrowser.focus();")
                self.assertFalse(self.settled(False)["toolbar"], "the bar is gone and the toolbar stayed")

    def test_13_the_toolbar_and_the_side_tab_list_never_draw_over_each_other(self):
        """#238: with the tabs at the side (Lateral, Foco), the toolbar and the tab list do not overlap while either
        is shown, hidden or coming back, in both themes. With the toolbar shown the list starts under it."""
        layout = f"const d = arguments[arguments.length - 1]; {LAYOUT}.apply(window, arguments[0]).then(d, e => d(String(e)));"
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        self.addCleanup(self.m.chrome, AWAY)

        def overlap(a, b):
            return (
                a["shown"]
                and b["shown"]
                and a["left"] < b["right"]
                and b["left"] < a["right"]
                and a["top"] < b["bottom"]
                and b["top"] < a["bottom"]
            )

        def parts(want_toolbar, want_tabs):
            wanted = lambda p: p["toolbar"]["shown"] is want_toolbar and p["tabs"]["shown"] is want_tabs  # noqa: E731
            self.assertTrue(harness.wait_until(lambda: wanted(self.m.chrome(PARTS)), 6), self.m.chrome(PARTS))
            time.sleep(0.4)  # past the transitions
            return self.m.chrome(PARTS)

        def apply(preset):
            self.m.set_context("chrome")
            try:
                return self.m.execute_async(layout, [preset])
            finally:
                self.m.set_context("content")

        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(apply, before)
        for preset in ("lateral", "focus"):
            apply(preset)
            for dark in (0, 1):
                with self.subTest(preset=preset, dark=bool(dark)):
                    self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                    self.m.chrome(AWAY + "gBrowser.selectedBrowser.focus();")
                    parts(False, False)
                    # The tab list alone, by the pointer at the edge: right under the band.
                    self.m.chrome(EDGE)
                    alone = parts(False, True)
                    self.assertLessEqual(alone["band"]["bottom"], alone["tabs"]["top"] + 1, alone)
                    # The toolbar too, by the keyboard: the list moves under it, and neither covers the other.
                    self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
                    both = parts(True, True)
                    self.assertFalse(overlap(both["toolbar"], both["tabs"]), both)
                    self.assertLessEqual(both["toolbar"]["bottom"], both["tabs"]["top"] + 1, both)
                    # The toolbar alone: the list goes; back on the page, the toolbar goes too.
                    self.m.chrome(AWAY)
                    toolbar = parts(True, False)
                    self.assertFalse(overlap(toolbar["toolbar"], toolbar["tabs"]), toolbar)
                    self.m.chrome("gBrowser.selectedBrowser.focus();")
                    parts(False, False)

    def test_14_a_click_outside_the_toolbar_takes_the_keyboard_out_of_the_address_bar(self):
        """#239: after the keyboard was in the address bar, a click on a page (a site, or one of the browser's own in
        the same process), on the tab list or on the band gives the focus to the page, and the toolbar goes. The
        engine leaves it in the address bar after a click on something that takes no focus; with the mode on the
        toolbar then stayed over the page."""
        layout = f"const d = arguments[arguments.length - 1]; {LAYOUT}.apply(window, arguments[0]).then(d, e => d(String(e)));"

        def apply(preset):
            self.m.set_context("chrome")
            try:
                return self.m.execute_async(layout, [preset])
            finally:
                self.m.set_context("content")

        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(apply, before)
        self.addCleanup(self.m.chrome, AWAY)
        apply("lateral")
        for page in (self.page, "about:preferences#privacy"):
            self.m.navigate(page)
            self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
            for spot in ("page", "tabs", "band"):
                with self.subTest(page=page.split("/")[-1], spot=spot):
                    self.m.chrome(AWAY + "gBrowser.selectedBrowser.focus();")
                    self.assertFalse(self.settled(False)["toolbar"])
                    if spot == "tabs":
                        self.m.chrome(EDGE)
                        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 6))
                    self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
                    self.assertTrue(self.settled(True)["toolbar"])
                    self.assertTrue(self.m.chrome(FOCUS)["urlbar"])
                    at = self.m.chrome(SPOTS)[spot]
                    self.assertIsNotNone(at, "no free point on the band")
                    self.m.chrome(CLICK_AT, [at])
                    self.assertTrue(harness.wait_until(lambda: not self.m.chrome(FOCUS)["urlbar"], 5), self.m.chrome(FOCUS))
                    self.m.chrome(AWAY)
                    self.assertFalse(self.settled(False)["toolbar"], spot)
        # Not on the toolbar itself: a click in the address bar keeps the keyboard there.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        field = self.m.chrome(
            "const b = gURLBar.inputField.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2];"
        )
        self.m.chrome(CLICK_AT, [field])
        time.sleep(0.5)
        self.assertTrue(self.m.chrome(FOCUS)["urlbar"])
        self.m.chrome("gBrowser.selectedBrowser.focus();")

    def test_15_a_name_in_another_script_keeps_its_registrable_part_apart(self):
        """#142: the registrable part was found by comparing the displayed host with the service's answer, which
        is in punycode: a name in another script never matched, and the whole host was emphasised alike."""
        ace = "xn--80a1acny.xn--e1afmkfd.test"  # почта.пример.test
        self.plain_http(ace)
        self.m.navigate(f"http://{ace}:{self.server.port}/page/Imersivo")
        parts = (
            "const o = document.querySelector('#nulavio-band .nv-band-origin');"
            "const part = name => o.querySelector(`.nv-band-origin-${name}`).textContent;"
            "return {sub: part('sub'), host: part('host'), shown: gBrowser.selectedBrowser.currentURI.displayHost};"
        )
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(parts)["host"].endswith(f".test:{self.server.port}"), 10),
            self.m.chrome(parts),
        )
        now = self.m.chrome(parts)
        # As the engine displays it (in its own script when its rules allow, in punycode otherwise): the last two
        # labels are the site, the rest gives way.
        labels = now["shown"].split(".")
        self.assertEqual(now["sub"], labels[0] + ".", now)
        self.assertEqual(now["host"], f"{labels[1]}.{labels[2]}:{self.server.port}", now)

    def test_16_a_site_that_does_not_fit_gets_a_second_line_then_keeps_the_toolbar(self):
        """ADR 0009, decision 6 (#142, R64): the registrable part is never cut. In a window too narrow for it the
        name ran over its neighbours in the band. Where one line is not enough the site gets a second (#118); where
        two are not enough either, the toolbar stays, and the mode comes back when it fits."""
        long_name = "a" * 63 + ".test"
        # Longer than two lines of a window at its narrowest (638 px here): a registrable part that cannot be cut, as
        # long as a public suffix makes it (63 letters under a suffix of the Public Suffix List's private part).
        longest = "b" * 63 + ".s3-website.ap-northeast-1.amazonaws.com"
        self.plain_http(long_name, longest)
        size = self.m.chrome("return [outerWidth, outerHeight];")
        self.addCleanup(self.m.chrome, "window.resizeTo(arguments[0], arguments[1]);", size)
        self.m.chrome("window.resizeTo(1500, 800);")
        self.m.navigate(f"http://{long_name}:{self.server.port}/page/Imersivo")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        inside = (
            "const o = document.querySelector('#nulavio-band .nv-band-origin').getBoundingClientRect();"
            "const h = document.querySelector('#nulavio-band .nv-band-origin-host').getBoundingClientRect();"
            "return h.left >= o.left - 0.5 && h.right <= o.right + 0.5;"
        )
        self.assertTrue(self.m.chrome(inside), "the name is over its neighbours with the mode on")
        # #118: one line is not enough, two are: the site gets a line of its own under the row, and the mode stays.
        lines = (
            "const band = document.getElementById('nulavio-band').getBoundingClientRect();"
            "const row = document.querySelector('#nulavio-band .nv-band-identity').getBoundingClientRect();"
            "const o = document.querySelector('#nulavio-band .nv-band-origin').getBoundingClientRect();"
            "const tabs = document.getElementById('sidebar-container').getBoundingClientRect();"
            "return { two: document.documentElement.hasAttribute('nulavio-immersive-two-lines'), band: band.height,"
            "         below: o.top >= row.bottom - 0.5, tabs: tabs.top };"
        )
        self.m.chrome("window.resizeTo(760, 800);")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(lines)["two"], 10), (self.window(), self.m.chrome(lines)))
        state = self.m.chrome(lines)
        self.assertTrue(self.window()["on"], self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertTrue(state["below"], state)
        self.assertGreater(state["band"], 40, state)  # two rows of the band
        # The tab list starts under the taller band, once its top has moved there (it moves with a transition).
        under = harness.wait_until(lambda: self.m.chrome(lines)["tabs"] >= self.m.chrome(lines)["band"], 5)
        self.assertTrue(under, self.m.chrome(lines))
        self.assertTrue(self.m.chrome(inside), "the name is over its neighbours on its own line")
        self.shoot_window("16-two-lines")
        # The row itself too long for one line (as a long profile name and a few seals make it): the site would go to a
        # third line, under the band and over the page, so the toolbar stays instead (review of #342). A test sheet
        # gives the profile's chip that width; a small resize has the window measure again, as a new name does.
        wide = (
            "const sheet = document.createElementNS('http://www.w3.org/1999/xhtml', 'style'); sheet.id = 'nv-test-wide';"
            "sheet.textContent = '#nulavio-band .nv-band-identity { min-inline-size: 720px !important; }';"
            "document.documentElement.append(sheet);"
        )
        self.m.chrome(wide)
        self.m.chrome("window.resizeTo(770, 800);")
        try:
            self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "fit", 10), (self.window(), self.m.chrome(lines)))
            self.assertFalse(self.m.chrome(lines)["two"], "two lines drawn while the row needs two by itself")
            self.assertTrue(self.settled(True)["toolbar"])
        finally:
            self.m.chrome("document.getElementById('nv-test-wide')?.remove(); window.resizeTo(760, 800);")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(lines)["two"], 10), (self.window(), self.m.chrome(lines)))
        self.m.chrome("window.resizeTo(520, 800);")  # as narrow as the window goes
        narrowest = self.m.chrome("return innerWidth;")
        self.assertLess(narrowest, 840, f"this desktop's narrowest window ({narrowest} px) fits the longest name on two lines")
        self.m.navigate(f"http://{longest}:{self.server.port}/page/Imersivo")
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "fit", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.assertFalse(self.m.chrome(lines)["two"], "two lines drawn while the toolbar stays")
        self.m.chrome("window.resizeTo(1500, 800);")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertFalse(self.m.chrome(lines)["two"], "two lines left on a window wide enough for one")

    def test_17_an_ai_workspace_keeps_the_whole_window(self):
        """ADR 0009, decision 6 (#142): a window an agent drives shows everything, whatever the switch says."""
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.m.chrome("Services.prefs.setStringPref('nulavio.ai.workspace', 'test-agent');")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.ai.workspace');")
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "agent", 45), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome("Services.prefs.clearUserPref('nulavio.ai.workspace');")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 45), self.window())
        self.assertFalse(self.settled(False)["toolbar"])

    def shoot_window(self, name: str) -> None:
        """The whole window in the light and the dark theme, for the review of #118 (NULAVIO_TEST_ARTIFACTS)."""
        folder = harness.artifacts_dir() / "immersive"
        folder.mkdir(parents=True, exist_ok=True)
        shown = self.window()["toolbar"]  # as it is now: the theme change must not leave it moving in the shot
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                harness.wait_until(
                    lambda want=bool(dark): self.m.chrome("return matchMedia('(prefers-color-scheme: dark)').matches;") == want,
                    10,
                )
                if not shown:
                    self.m.chrome(AWAY)
                harness.wait_until(lambda: self.window()["toolbar"] is shown and self.m.chrome(STILL), 10)
                self.m.set_context("chrome")
                try:
                    png = self.m.screenshot_png()
                finally:
                    self.m.set_context("content")
                (folder / f"{name}-{'dark' if dark else 'light'}.png").write_bytes(png)
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")

    def test_18_the_pin_keeps_the_toolbar_and_the_tab_list_in_view_for_touch(self):
        """#118, ADR 0009 decision 7: with no pointer to bring the chrome back (touch), the pin in the band holds the
        toolbar and the tab list until it is pressed again. It is there only in the mode; turning the mode off
        lets it go."""
        self.m.chrome(AWAY)
        self.assertFalse(self.settled(False)["toolbar"])
        pin = self.m.chrome(PIN)
        self.assertEqual((pin["shown"], pin["pressed"]), (True, "false"), pin)
        self.assertTrue(pin["label"], pin)
        self.assertGreaterEqual(min(pin["size"]), 24, pin)
        # Not on the first run's stage, which shows the band and the page alone (ADR 0010, decision 5).
        self.m.chrome("document.documentElement.setAttribute('nulavio-stage', 'layout');")
        try:
            self.assertFalse(self.m.chrome(PIN)["shown"], "the pin is on the first run's stage")
        finally:
            self.m.chrome("document.documentElement.removeAttribute('nulavio-stage');")
        self.m.chrome(PRESS_PIN)
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "tabs toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 6), self.m.chrome(PARTS))
        self.assertEqual(self.m.chrome(PIN)["pressed"], "true")
        self.shoot_window("18-pinned")
        # Pressed again with a real click (the button takes the keyboard): both leave once the pointer goes.
        spot = self.m.chrome(
            "const b = document.querySelector('#nulavio-band .nv-band-pin').getBoundingClientRect();"
            "return [b.left + b.width / 2, b.top + b.height / 2];"
        )
        self.m.chrome(CLICK_AT, [spot])
        self.m.chrome(AWAY)
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 6), self.m.chrome(PARTS))
        self.assertEqual(self.m.chrome(PIN)["pressed"], "false")
        # Pinned, then the mode turned off: no pin left for the next time, and none on the full window.
        self.m.chrome(PRESS_PIN)
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "tabs toolbar", 10), self.window())
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', false);")
        self.assertTrue(harness.wait_until(lambda: not self.window()["on"], 10), self.window())
        self.assertEqual(self.m.chrome(PIN)["shown"], False)
        self.assertEqual((self.window()["hold"], self.m.chrome(PIN)["pressed"]), (None, "false"))

    def test_19_a_tab_opened_in_the_background_shows_the_tab_list_for_a_moment(self):
        """#118, ADR 0009 decision 4: a tab opened behind the one in view comes into view in the tab list, which
        leaves again by itself. A tab opened in front of the page is seen anyway and holds nothing."""
        self.m.chrome(AWAY)
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 6), self.m.chrome(PARTS))
        self.addCleanup(
            self.m.chrome, "for (const tab of window.nvOpened ?? []) gBrowser.removeTab(tab); delete window.nvOpened;"
        )
        system = "{triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()}"
        add = f"(window.nvOpened ??= []).push(gBrowser.addTab(arguments[0], {system}));"
        self.m.chrome(add, [self.page])
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "tabs", 5), self.window())
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))
        self.shoot_window("19-background-tab")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 6), self.window())
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 6), self.m.chrome(PARTS))
        self.assertFalse(self.window()["toolbar"])
        # In front: selected at once, so nothing is held for it.
        self.m.chrome(add.replace("push(gBrowser.addTab", "push(gBrowser.selectedTab = gBrowser.addTab"), [self.page])
        self.assertFalse(harness.wait_until(lambda: self.window()["hold"] is not None, 2), self.window())
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0];")

    def test_20_pointer_journeys_keep_every_part_in_place(self):
        """#344: the window driven by pointer paths, not jumps (WebDriver actions in the chrome, through the engine's
        own event path), measured at every frame. Along band -> toolbar -> tab list and back, side edge -> tab list ->
        toolbar, across the page, and out and back in during the hold and during a transition: the toolbar never
        covers the tab list or the assistant's panel, the page and the panel never move sideways, the band never
        moves, and once the pointer rests on the page nothing stays shown. With no panel, Nulavio's assistant and a
        site's; in Lateral, Foco and Abas no topo (where the side column is the launcher's, as with the mode off), and in
        Lateral with the tab list on the right (#346: every journey mirrored, by the right edge); light at 1440 x 900
        and dark at the narrowest window.
        The tab list is drawn over the panel as it is over the page: it comes and goes without moving either."""
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        # Last, once the window has its size back: the pointer on the page, away from where any part comes in (the
        # mirrored journeys end at the left quarter, where the tab list on the left would be).
        self.addCleanup(self.rest_pointer)
        self.addCleanup(
            self.m.chrome,
            "Services.prefs.clearUserPref('browser.ml.chat.enabled'); Services.prefs.clearUserPref('browser.ml.chat.provider');",
        )
        self.addCleanup(self.m.chrome, "SidebarController.hide();")
        self.addCleanup(
            self.m.chrome,
            "window.resizeTo(arguments[0], arguments[1]);",
            self.m.chrome("return [window.outerWidth, window.outerHeight];"),
        )
        self.addCleanup(self.m.chrome, "if (window.nvTrace) window.nvTrace.on = false;")
        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        chatbot = self.server.url("/page/chatbot")

        def walk(name: str, points: list[tuple[int, ...]], pause_ms: int = 0) -> list[dict]:
            self.m.chrome(TRACE)
            self.m.set_context("chrome")
            try:
                rest = [{"type": "pause", "duration": 1600}]  # the hold and the exit, then the window at rest
                self.m.send(
                    "WebDriver:PerformActions",
                    {
                        "actions": [
                            {
                                "type": "pointer",
                                "id": "mouse",
                                "parameters": {"pointerType": "mouse"},
                                "actions": pointer_path(points, pause_ms) + rest,
                            }
                        ]
                    },
                )
            finally:
                self.m.set_context("content")
            frames = self.trace_end()
            self.assertGreater(len(frames), 30, name)
            return frames

        def check(where: str, frames: list[dict], panel: bool, want_tabs: bool, want_toolbar: bool):
            first = frames[0]
            for n, f in enumerate(frames):
                at = f"{where}, frame {n} of {len(frames)}: {f}"
                self.assertFalse(covers(f["toolbar"], f["tabs"]), "the toolbar over the tab list: " + at)
                self.assertFalse(covers(f["toolbar"], f["panel"]), "the toolbar over the panel: " + at)
                self.assertEqual(f["band"][:4], first["band"][:4], "the band moved: " + at)
                self.assertEqual([f["page"][0], f["page"][2]], [first["page"][0], first["page"][2]], "the page moved: " + at)
                self.assertEqual(f["page"][1], first["page"][1], "the page moved: " + at)
                if panel:
                    self.assertEqual(
                        [f["panel"][0], f["panel"][2]], [first["panel"][0], first["panel"][2]], "the panel moved: " + at
                    )
                if visible(f["tabs"]):
                    self.assertGreaterEqual(f["tabs"][1] + 1, f["band"][3], "the tab list over the band: " + at)
            # It went where the pointer took it, so the checks above saw it (no journey passes by seeing nothing)...
            self.assertEqual(any(visible(f["tabs"]) for f in frames), want_tabs, f"{where}: the tab list")
            self.assertEqual(any(visible(f["toolbar"]) for f in frames), want_toolbar, f"{where}: the toolbar")
            # ...and left once the pointer rests on the page.
            last = frames[-1]
            self.assertFalse(visible(last["toolbar"]) or visible(last["tabs"]), f"{where}: still shown at rest: {last}")

        for size, dark in (((1440, 900), 0), ((320, 480), 1)):
            self.m.chrome("window.resizeTo(arguments[0], arguments[1]);", list(size))
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            for preset, start in (("lateral", True), ("focus", True), ("top", True), ("lateral", False)):
                self.apply_preset(preset)
                self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', arguments[0]);", [start])
                # The engine can move the column at the end of a view transition: wait for its side, then stillness.
                side = "return document.documentElement.hasAttribute('sidebar-positionend');"
                self.assertTrue(
                    harness.wait_until(
                        lambda side=side, start=start: self.m.chrome(side) is not start and self.m.chrome(STILL), 10
                    )
                )
                for panel, show in PANELS.items():
                    self.m.chrome(show, [chatbot])
                    if panel != "none":
                        self.assertTrue(
                            harness.wait_until(
                                lambda: self.m.chrome("return document.getElementById('sidebar-box').checkVisibility();"), 10
                            )
                        )
                    self.m.chrome(AWAY + "gBrowser.selectedBrowser.focus();")
                    self.assertTrue(harness.wait_until(lambda: not self.window()["toolbar"] and self.m.chrome(STILL), 10))
                    w, h = self.m.chrome("return [innerWidth, innerHeight];")
                    side = "" if start else " on the right"
                    where = f"{preset}{side}, panel {panel}, {w}x{h}, {'dark' if dark else 'light'}"

                    def journey(name, points, pause_ms=0, w=w, start=start):
                        # With the tab list on the right, the same path seen in a mirror: by the right edge.
                        mirrored = [p if start else (w - 1 - p[0], *p[1:]) for p in points]
                        return walk(name, mirrored, pause_ms)

                    page = (w * 3 // 4, h // 2)
                    with self.subTest(where=where):
                        # Band -> toolbar -> tab list and back up, then out over the page.
                        frames = journey(
                            "band-toolbar-tabs",
                            [page, (1, h // 2), (100, h // 3), (100, 10), (100, 50), (100, h // 3), (100, 10), page],
                            120,
                        )
                        check(where + ", band -> toolbar -> tab list", frames, panel != "none", True, True)
                        # Side edge -> tab list -> toolbar, along the toolbar and down onto the page.
                        frames = journey(
                            "edge-tabs-toolbar",
                            [page, (1, h * 2 // 3), (100, h // 2), (100, 10), (100, 50), (w // 2, 50), page],
                            120,
                        )
                        check(where + ", edge -> tab list -> toolbar", frames, panel != "none", True, True)
                        # Across the page, under the toolbar and away from the edge: nothing comes.
                        frames = journey("across", [page, (w // 4, h - 40), (w - 40, 80), page])
                        check(where + ", across the page", frames, panel != "none", False, False)
                        # Out of the toolbar and back while it is held (back after about 0.2 s), then out and back
                        # while it leaves (about 0.7 s: past the 0.6 s hold, inside the 0.18 s exit), then away.
                        frames = journey(
                            "back-in",
                            [
                                page,
                                (w // 2, 10, 400),
                                (w // 2, 120),
                                (w // 2, 10, 400),
                                (w // 2, 200, 150),
                                (w // 2, 10, 400),
                                page,
                            ],
                        )
                        check(where + ", out and back in", frames, panel != "none", False, True)
                        self.m.chrome(PANELS["none"])

    def test_21_typing_and_a_tab_menu_with_the_tab_list_shown_keep_the_parts_apart(self):
        """#344: the mode turned on with the toolbar and the tab list leaving at once; then the tab list brought by the
        pointer, the address field typed in with its results open, and the menu of a tab opened with a right click in
        the list: at every frame the toolbar and the list stay apart, the page does not move, and both leave once the
        pointer rests on the page."""
        self.addCleanup(self.m.chrome, "if (window.nvTrace) window.nvTrace.on = false;")
        self.addCleanup(self.m.chrome, "document.getElementById('tabContextMenu').hidePopup(); gURLBar.view.close();")
        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.apply_preset("lateral")
        w, h = self.m.chrome("return [innerWidth, innerHeight];")
        page = (w * 3 // 4, h // 2)

        def act(*sources):
            self.m.set_context("chrome")
            try:
                self.m.send("WebDriver:PerformActions", {"actions": list(sources)})
            finally:
                self.m.set_context("content")

        def pointer(actions):
            return {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": actions}

        def keys(text):
            return {
                "type": "key",
                "id": "keyboard",
                "actions": [a for c in text for a in ({"type": "keyDown", "value": c}, {"type": "keyUp", "value": c})],
            }

        def apart(frames, where, page_moves=False):
            first = frames[0]
            for n, f in enumerate(frames):
                at = f"{where}, frame {n} of {len(frames)}: {f}"
                self.assertFalse(covers(f["toolbar"], f["tabs"]), "the toolbar over the tab list: " + at)
                if not page_moves:
                    self.assertEqual(f["page"][:4], first["page"][:4], "the page moved: " + at)
            self.assertFalse(visible(frames[-1]["toolbar"]) or visible(frames[-1]["tabs"]), f"{where}: {frames[-1]}")

        # The mode turned off and on again (the key, the switch): the toolbar and the list leave at once; the toolbar
        # was held 0.6 s over the list's top as the list left the flow.
        self.m.chrome(TRACE)
        for on in (False, True):
            self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', arguments[0]);", [on])
            self.assertTrue(harness.wait_until(lambda want=on: self.window()["on"] is want and self.m.chrome(STILL), 10))
        apart(self.trace_end(), "the mode turned on", page_moves=True)
        self.m.chrome(AWAY + "gBrowser.selectedBrowser.focus();")
        self.assertTrue(harness.wait_until(lambda: not self.window()["toolbar"] and self.m.chrome(STILL), 10))

        # The list by the pointer, which stays in it; the address field by the keyboard, typed in.
        self.m.chrome(TRACE)
        act(pointer(pointer_path([page, (1, h // 2), (100, h // 2)], 300)))
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        act(keys("imersivo"))
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return gURLBar.view.isOpen;"), 5), "no results")
        both = lambda: (p := self.m.chrome(PARTS))["toolbar"]["shown"] and p["tabs"]["shown"] and self.m.chrome(STILL)  # noqa: E731
        self.assertTrue(harness.wait_until(both, 5), self.m.chrome(PARTS))
        self.shoot_window("21-typing-with-the-list")
        self.m.chrome("gURLBar.view.close(); gURLBar.handleRevert(); gBrowser.selectedBrowser.focus();")
        act(pointer([*pointer_path([(100, h // 2), page], 0), {"type": "pause", "duration": 1600}]))
        apart(self.trace_end(), "typing")

        # A tab's menu, by a right click on the tab in the list: the list stays while it is open.
        self.m.chrome(TRACE)
        act(pointer(pointer_path([page, (1, h // 2), (100, h // 2)], 300)))
        tab = self.m.chrome(
            "const b = gBrowser.selectedTab.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2];"
        )
        spot = (round(tab[0]), round(tab[1]))
        right = [{"type": "pointerDown", "button": 2}, {"type": "pointerUp", "button": 2}]
        act(pointer([*pointer_path([(100, h // 2), spot], 100), *right]))
        menu = "return document.getElementById('tabContextMenu').state;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(menu) == "open", 5))
        act(pointer([*pointer_path([spot, page], 0), {"type": "pause", "duration": 1200}]))
        self.assertTrue(self.m.chrome(PARTS)["tabs"]["shown"], "the list left with its tab's menu open")
        self.assertIn("tabs", self.window()["hold"] or "")
        self.m.chrome("document.getElementById('tabContextMenu').hidePopup();")
        act(pointer([{"type": "pause", "duration": 1600}]))
        apart(self.trace_end(), "a tab's menu")

        # A tab dragged in the list: the engine's drag session takes the hover away from the list, which left under the
        # pointer before the drop. The list stays from the drag's start to its end. (Marionette starts no drag
        # session; the drag through the X server is in the pull request's real-input pass.)
        drag = (
            "gBrowser.selectedTab.dispatchEvent(new DragEvent(arguments[0], {bubbles: true, dataTransfer: new DataTransfer()}));"
        )
        # The synthetic drag never had a drag session, so the engine's own end of a drag (dragend, and its check for
        # a stale drag) does not leave moving-tab mode: the cleanup ends it the way a drop does, so the toolbar takes
        # the pointer again for what runs next (#398, test 22).
        end = "gBrowser.tabContainer.tabDragAndDrop.finishAnimateTabMove();for (const tab of gBrowser.tabs) delete tab._dragData;"
        self.m.chrome(drag, ["dragstart"])
        self.addCleanup(self.m.chrome, end)
        self.addCleanup(self.m.chrome, drag, ["dragend"])
        self.assertTrue(harness.wait_until(lambda: "tabs" in (self.window()["hold"] or ""), 5), self.window())
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))
        # Then not gone within the hold and the exit a hover gets (0.6 s + 0.18 s), and more.
        gone = harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 1.2)
        self.assertFalse(gone, "the list left during a tab's drag")
        self.m.chrome(drag, ["dragend"])
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 5), self.window())
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))

    def test_23_the_tab_list_on_the_right_leaves_and_comes_back_by_the_right_edge(self):
        """#346: with the tab list on the right (sidebar.position_start false) it leaves by the right and only the right
        edge brings it back, over the page, which does not move; the left edge brings nothing. At rest nothing of it
        is in view."""
        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        self.apply_preset("lateral")
        self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', false);")
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return document.documentElement.hasAttribute('sidebar-positionend');"), 10)
        )
        geometry = (
            "const r = id => document.getElementById(id).getBoundingClientRect();"
            "const list = r('sidebar-container'), edge = r('nulavio-immersive-edge'), page = r('tabbrowser-tabbox');"
            "return {width: innerWidth, list: [list.left, list.right], edge: [edge.left, edge.right],"
            " page: [page.left, page.right]};"
        )
        self.m.chrome(AWAY)
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))
        rest = self.m.chrome(geometry)
        self.assertGreaterEqual(rest["list"][0], rest["width"], rest)  # out of view, past the right edge
        self.assertEqual(round(rest["edge"][1]), rest["width"], rest)  # the edge that brings it back is the right one
        self.addCleanup(self.m.chrome, "if (window.nvTrace) window.nvTrace.on = false;")
        self.m.chrome(TRACE)  # every frame while the pointer is at the left edge, not one look after it
        self.m.chrome(EDGE)  # the left edge
        time.sleep(1)
        frames = self.trace_end()
        self.assertGreater(len(frames), 10)
        flashed = [f["tabs"] for f in frames if visible(f["tabs"])]
        self.assertEqual(flashed, [], "the left edge brought the list on the right")
        self.m.chrome(AWAY)
        self.m.chrome("window.synthesizeMouseEvent('mousemove', innerWidth - 2, Math.round(innerHeight / 2), {}, {});")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(STILL), 5))  # in place, past its slide
        shown = self.m.chrome(geometry)
        self.assertAlmostEqual(shown["list"][1], shown["width"], delta=1, msg=shown)
        self.assertEqual(shown["page"], rest["page"], "the page moved when the list came in")
        self.m.chrome(AWAY)
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PARTS)["tabs"]["shown"], 5), self.m.chrome(PARTS))

    def test_24_the_security_cues_are_the_engines_with_the_tab_list_anywhere(self):
        """#346: the first part of the matrix (09) with the tab list on the right and with tabs on top, in both themes:
        out of view no cue is restyled, and back in view every cue is drawn where and as with the mode off."""

        def cues() -> dict:
            return {cue["id"]: cue for cue in self.m.chrome(CUES)}

        def drawn(now: dict) -> dict:
            return {name: (cue.get("display"), cue.get("visibility"), cue.get("opacity")) for name, cue in now.items()}

        def sized(now: dict) -> dict:
            return {name: (cue.get("width"), cue.get("height"), cue.get("inside")) for name, cue in now.items()}

        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        for preset, start in (("lateral", False), ("top", True)):
            self.apply_preset(preset)
            self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', arguments[0]);", [start])
            side = "return document.documentElement.hasAttribute('sidebar-positionend');"
            self.assertTrue(
                harness.wait_until(lambda side=side, start=start: self.m.chrome(side) is not start and self.m.chrome(STILL), 10)
            )
            for dark in (0, 1):
                with self.subTest(preset=preset, right=not start, dark=bool(dark)):
                    self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                    self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
                    self.assertTrue(self.settled(True)["toolbar"])
                    reference = cues()
                    self.assertTrue(reference["trust-icon-container"]["inside"], reference)
                    self.m.chrome(
                        "Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();"
                    )
                    self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
                    self.assertFalse(self.settled(False)["toolbar"])
                    self.assertEqual(drawn(cues()), drawn(reference))
                    self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
                    self.assertTrue(self.settled(True)["toolbar"])
                    back = cues()
                    self.assertEqual(drawn(back), drawn(reference))
                    self.assertEqual(sized(back), sized(reference))
                    self.m.chrome("gBrowser.selectedBrowser.focus();")
                    self.assertFalse(self.settled(False)["toolbar"])

    # -- #346: the side panel on the other side of the page (#527) has an edge of its own ----------------------------

    def panel_opposite(self, start: bool = True) -> tuple[int, int]:
        """Lateral, the tab list on the left (start) or the right, the side panel opposite it (patch 0013, #527) with the
        assistant open, and everything away: the pointer on the page, the keyboard in the page, the opening's moment
        over. Returns the window's inner size. A build of this tree must have the patch."""
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        self.addCleanup(self.m.chrome, f"Services.prefs.clearUserPref('{OPPOSITE}');")
        self.addCleanup(self.m.chrome, "SidebarController.hide();")
        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.apply_preset("lateral")
        self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', arguments[0]);", [start])
        self.m.chrome(f"Services.prefs.setBoolPref('{OPPOSITE}', true);")
        marked = "return document.documentElement.hasAttribute('nulavio-panel-opposite');"
        if not harness.wait_until(lambda: self.m.chrome(marked), 5):
            if harness.built_from_this_tree():
                self.fail("this engine is a build of this tree and does not place the panel opposite: patch 0013 is missing")
            self.skipTest("an engine without patch 0013 (a development package with this tree's Shell)")
        side = "return document.documentElement.hasAttribute('sidebar-positionend');"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(side) is not start, 10))
        self.m.chrome(f"SidebarController.show('{ASSISTANT}');")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return SidebarController.currentID;") == ASSISTANT, 10))
        self.rest_pointer_at(start)
        # The assistant's page may take the keyboard once it has loaded (its question field), which holds the panel, as
        # it should: give it that moment, then put the keyboard back in the page.
        inside = "return document.getElementById('sidebar-box').contains(document.activeElement);"
        harness.wait_until(lambda: self.m.chrome(inside), 3)
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        away = harness.wait_until(lambda: self.panel_away() and self.m.chrome(STILL), 10)
        self.assertTrue(away, f"{self.m.chrome(PANEL)}, {self.window()}, keyboard in the panel: {self.m.chrome(inside)}")
        return tuple(self.m.chrome("return [innerWidth, innerHeight];"))

    def panel_away(self) -> bool:
        return not self.m.chrome(PANEL)["shown"] and "panel" not in (self.window()["hold"] or "")

    def rest_pointer_at(self, start: bool) -> None:
        """The pointer on the page, a quarter in from the tab list's side: away from both edges."""
        w, h = self.m.chrome("return [innerWidth, innerHeight];")
        x = w // 3 if start else w * 2 // 3
        self.m.set_context("chrome")
        try:
            move = {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": x, "y": h // 2}
            pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [move]}
            self.m.send("WebDriver:PerformActions", {"actions": [pointer]})
        finally:
            self.m.set_context("content")

    def walk(self, points: list[tuple[int, ...]], pause_ms: int = 0) -> list[dict]:
        """A pointer journey through the engine's own event path, every frame traced (TRACE), and the rest after it."""
        self.addCleanup(self.m.chrome, "if (window.nvTrace) window.nvTrace.on = false;")
        self.m.chrome(TRACE)
        self.m.set_context("chrome")
        try:
            actions = [*pointer_path(points, pause_ms), {"type": "pause", "duration": 1600}]
            pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": actions}
            self.m.send("WebDriver:PerformActions", {"actions": [pointer]})
        finally:
            self.m.set_context("content")
        frames = self.trace_end()
        self.assertGreater(len(frames), 30)
        return frames

    def test_25_the_panel_opposite_leaves_and_comes_back_by_its_own_edge(self):
        """#346: with the side panel on the other side of the page (#527), the panel leaves entirely by its own edge and
        only that edge brings it back, over the page, which does not move. Journeys with the pointer, every frame: the
        panel's edge, into the panel and back onto the page; the tab list's edge; the toolbar; across the page. The
        toolbar never covers the panel, the panel never covers the tab list, the band and the page never move, the tab
        list's edge never brings the panel and the panel's edge never brings the tab list, and once the pointer rests
        on the page nothing is in view. Tabs on the left and on the right; light at 1440 x 900, dark at 1366 x 768."""
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        self.addCleanup(
            self.m.chrome,
            "window.resizeTo(arguments[0], arguments[1]);",
            self.m.chrome("return [window.outerWidth, window.outerHeight];"),
        )
        for size, dark in (((1440, 900), 0), ((1366, 768), 1)):
            self.m.chrome("window.resizeTo(arguments[0], arguments[1]);", list(size))
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            for start in (True, False):
                w, h = self.panel_opposite(start)
                where = f"tabs {'left' if start else 'right'}, {w}x{h}, {'dark' if dark else 'light'}"
                frame = self.m.chrome(PANEL)["frame"]

                def mirror(points, w=w, start=start):
                    # Drawn for the tab list on the left; with it on the right, the same path in a mirror.
                    return [p if start else (w - 1 - p[0], *p[1:]) for p in points]

                def check(name, frames, want_panel, want_tabs, want_toolbar, where=where):
                    first = frames[0]
                    for n, f in enumerate(frames):
                        at = f"{where}, {name}, frame {n} of {len(frames)}: {f}"
                        self.assertFalse(covers(f["toolbar"], f["panel"]), "the toolbar over the panel: " + at)
                        self.assertFalse(covers(f["toolbar"], f["tabs"]), "the toolbar over the tab list: " + at)
                        self.assertFalse(covers(f["panel"], f["tabs"]), "the panel and the tab list together: " + at)
                        self.assertEqual(f["band"][:4], first["band"][:4], "the band moved: " + at)
                        self.assertEqual(f["page"][:4], first["page"][:4], "the page moved: " + at)
                        if visible(f["panel"]):
                            self.assertGreaterEqual(f["panel"][1] + 1, f["band"][3], "the panel over the band: " + at)
                    self.assertEqual(any(visible(f["panel"]) for f in frames), want_panel, f"{where}, {name}: the panel")
                    self.assertEqual(any(visible(f["tabs"]) for f in frames), want_tabs, f"{where}, {name}: the tab list")
                    self.assertEqual(any(visible(f["toolbar"]) for f in frames), want_toolbar, f"{where}, {name}: the toolbar")
                    last = frames[-1]
                    self.assertFalse(
                        visible(last["panel"]) or visible(last["tabs"]) or visible(last["toolbar"]),
                        f"{where}, {name}: still shown at rest: {last}",
                    )

                page = (w // 3, h // 2)
                with self.subTest(where=where):
                    # At rest: the page between the frame margins, the panel entirely past its edge.
                    rest = self.m.chrome(PANEL)
                    self.assertEqual(rest["page"], [frame, w - frame], rest)
                    self.assertTrue(rest["box"][0] >= w if start else rest["box"][1] <= 0, rest)
                    # The panel's edge, into the panel, a moment there, and back onto the page.
                    frames = self.walk(mirror([page, (w - 1, h // 2, 300), (w - 120, h // 2, 400), page]))
                    check("the panel's edge", frames, True, False, False)
                    # In view, it rests at the frame margin of its side and never comes further in; the other frames in
                    # view are its slide's.
                    gaps = [(w - f["panel"][2]) if start else f["panel"][0] for f in frames if visible(f["panel"])]
                    self.assertEqual(max(set(gaps), key=gaps.count), frame, f"the panel at rest in view: {gaps}")
                    self.assertEqual(max(gaps), frame, f"the panel came further in than the frame margin: {gaps}")
                    # The tab list's edge brings the tab list, never the panel.
                    frames = self.walk(mirror([page, (1, h // 2, 300), (100, h // 2, 300), page]))
                    check("the tab list's edge", frames, False, True, False)
                    # The toolbar, from the top, and down onto the page.
                    frames = self.walk(mirror([page, (w // 2, 10, 400), page]))
                    check("the toolbar", frames, False, False, True)
                    # Across the page, away from every edge.
                    frames = self.walk(mirror([page, (w // 4, h - 40), (w * 3 // 4, 80), page]))
                    check("across the page", frames, False, False, False)

    def test_26_the_panel_stays_while_it_has_the_focus_a_menu_or_the_pin(self):
        """#346, the toolbar's holds for the panel on its own edge: the keyboard in it, a menu anchored in it and the
        band's pin keep it in view with the pointer away; when they end, it leaves."""
        self.panel_opposite(True)

        def stays(why: str) -> None:
            self.m.chrome(AWAY)
            time.sleep(2)  # past the hold and the exit a pointer gets
            self.assertTrue(self.m.chrome(PANEL)["shown"], f"{why}: the panel left: {self.m.chrome(PANEL)}")

        def leaves(why: str) -> None:
            self.m.chrome(AWAY)
            self.assertTrue(harness.wait_until(self.panel_away, 6), f"{why}: the panel stayed: {self.m.chrome(PANEL)}")

        # The keyboard in the panel (the page in it), then back in the page.
        self.m.chrome(
            "const outer = SidebarController.browser; outer.contentWindow.focus();"
            "(outer.contentDocument?.querySelector('browser') ?? outer).focus();"
        )
        inside = "return document.getElementById('sidebar-box').contains(document.activeElement);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(inside), 5), "the keyboard did not go into the panel")
        self.assertTrue(harness.wait_until(lambda: "panel" in (self.window()["hold"] or ""), 5), self.window())
        stays("the keyboard in it")
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        leaves("the keyboard back in the page")
        # A menu anchored in it.
        self.addCleanup(self.m.chrome, "document.getElementById('nv-test-panel-menu')?.remove();")
        self.m.chrome(
            "const menu = document.createXULElement('menupopup'); menu.id = 'nv-test-panel-menu';"
            "const item = document.createXULElement('menuitem'); item.setAttribute('label', 'Item'); menu.append(item);"
            "document.getElementById('mainPopupSet').append(menu);"
            "menu.openPopup(document.getElementById('sidebar-box'), 'overlap', 20, 20);"
        )
        menu = "return document.getElementById('nv-test-panel-menu').state;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(menu) == "open", 5))
        self.assertIn("panel", self.window()["hold"] or "")
        stays("a menu open in it")
        self.m.chrome("document.getElementById('nv-test-panel-menu').hidePopup();")
        leaves("the menu closed")
        # The pin, for touch: pressed, it holds the panel too; pressed again, it lets it go.
        self.m.chrome(PRESS_PIN)
        self.addCleanup(lambda: self.m.chrome(PIN)["pressed"] == "true" and self.m.chrome(PRESS_PIN))
        stays("the pin pressed")
        self.m.chrome(PRESS_PIN + "gBrowser.selectedBrowser.focus();")
        leaves("the pin let go")

    def test_27_a_panel_just_opened_or_with_a_request_waiting_is_in_view(self):
        """#346: a panel opened while it is away (the key, the launcher) comes into view for a moment, as a tab opened in
        the background does; and while the assistant's permission request waits as a card in it, it stays in view, so
        the request is never left unseen in a panel that is out of view (NulavioAI places the card there while the
        panel is open)."""
        self.panel_opposite(True)
        self.m.chrome("SidebarController.hide();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return !SidebarController.isOpen;"), 5))
        self.m.chrome(f"SidebarController.show('{ASSISTANT}');")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PANEL)["shown"], 3), self.m.chrome(PANEL))
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertTrue(harness.wait_until(self.panel_away, 6), self.m.chrome(PANEL))
        # A request waiting in the panel: what NulavioAI says of this window's runs, then its notice of the change.
        ai = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI'
        # Back to NulavioAI's own answer, and the window told so, as the end of a request tells it (else the window keeps
        # the hold of a request that no longer waits, for whatever runs next).
        self.addCleanup(
            self.m.chrome, f"delete {ai}.assistantRuns; Services.obs.notifyObservers(window, 'nulavio-ai-activity-changed');"
        )
        self.m.chrome(
            f"{ai}.assistantRuns = () => [{{ runId: 'r', kind: 'task', state: 'running', pendingApproval: 'a1' }}];"
            "Services.obs.notifyObservers(window, 'nulavio-ai-activity-changed');"
        )
        self.assertTrue(harness.wait_until(lambda: "panel" in (self.window()["hold"] or ""), 5), self.window())
        self.m.chrome(AWAY)
        time.sleep(2)
        self.assertTrue(self.m.chrome(PANEL)["shown"], "the panel left with a request waiting in it")
        self.m.chrome(f"delete {ai}.assistantRuns; Services.obs.notifyObservers(window, 'nulavio-ai-activity-changed');")
        self.assertTrue(harness.wait_until(self.panel_away, 6), self.m.chrome(PANEL))
        # With the panel beside the tabs (the setting off) it stays in the flow (#344): a waiting request holds nothing,
        # so the window's other rules that look at the holds (#239: a click on the page takes the keyboard) are as before.
        self.m.chrome(f"Services.prefs.clearUserPref('{OPPOSITE}');")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(PANEL)["opposite"], 5))
        self.m.chrome(
            f"{ai}.assistantRuns = () => [{{ runId: 'r', kind: 'task', state: 'running', pendingApproval: 'a1' }}];"
            "Services.obs.notifyObservers(window, 'nulavio-ai-activity-changed');"
        )
        self.assertFalse(harness.wait_until(lambda: self.window()["hold"] is not None, 2), self.window())

    def test_28_a_side_that_changes_moves_the_part_that_is_away_at_once(self):
        """#346 (from #539's review): with the mode on and the tab list away, changing its side (sidebar.position_start)
        moved its edge at once while its slide ran, so the list was seen crossing the window. The part that is away
        goes to its new edge without a slide: the tab list alone, and the tab list with the panel opposite it."""
        before = self.m.chrome(f"return {LAYOUT}.state(window).then(state => state.preset);")
        self.addCleanup(self.apply_preset, before)
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        self.apply_preset("lateral")
        side = "return document.documentElement.hasAttribute('sidebar-positionend');"

        def flip(where: str) -> None:
            for start in (False, True):
                self.m.chrome(TRACE)
                self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', arguments[0]);", [start])
                self.assertTrue(harness.wait_until(lambda start=start: self.m.chrome(side) is not start, 10))
                time.sleep(1)  # longer than any slide
                frames = self.trace_end()
                self.assertGreater(len(frames), 10)
                seen = [f for f in frames if visible(f["tabs"]) or visible(f["panel"])]
                self.assertEqual(seen, [], f"{where}, to the {'left' if start else 'right'}: seen crossing")

        self.rest_pointer()
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertTrue(harness.wait_until(lambda: not self.window()["toolbar"] and self.m.chrome(STILL), 10))
        flip("the tab list")
        self.panel_opposite(True)
        flip("the tab list and the panel opposite it")

    def rest_pointer(self):
        """The pointer on the page, three quarters across and halfway down, through the engine's own event path."""
        w, h = self.m.chrome("return [innerWidth, innerHeight];")
        self.m.set_context("chrome")
        try:
            move = {"type": "pointerMove", "duration": 0, "origin": "viewport", "x": w * 3 // 4, "y": h // 2}
            pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [move]}
            self.m.send("WebDriver:PerformActions", {"actions": [pointer]})
        finally:
            self.m.set_context("content")

    def test_22_after_the_tab_drags_the_toolbar_takes_the_pointer_again(self):
        """#398: the journeys above (21) drag a tab with events of their own and no drag session. When they are done,
        the engine's moving-tab state is gone from the toolbox, and the toolbar takes the pointer again: a test after
        them sees the window a person has after a real drag ends."""
        state = (
            "return { moving: gNavToolbox.hasAttribute('movingtab') || gBrowser.tabContainer.hasAttribute('movingtab'),"
            " pointer: getComputedStyle(document.getElementById('nav-bar')).pointerEvents };"
        )
        self.assertFalse(self.m.chrome(state)["moving"], self.m.chrome(state))
        # With Imersivo on, a hidden toolbar takes no pointer by design: the check is the window with it off.
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', false);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(state) == {"moving": False, "pointer": "auto"}, 5), self.m.chrome(state)
        )

    def apply_preset(self, preset: str):
        layout = f"const d = arguments[arguments.length - 1]; {LAYOUT}.apply(window, arguments[0]).then(d, e => d(String(e)));"
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(layout, [preset])
        finally:
            self.m.set_context("content")


if __name__ == "__main__":
    unittest.main()
