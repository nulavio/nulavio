"""No feature tip from Mozilla's messaging system in the Nulavio build (#929).

Firefox 161 dropped the pref that kept the tab group tips off (browser.tabs.groups.onboardingCallouts.enabled): their
targeting is now only `userPrefs.cfrFeatures`, Settings' "Recommend features as you browse", and the tip loads
Mozilla's artwork from its CDN (firefox-settings-attachments.cdn.mozilla.net/main-workspace/ms-images/,
FeatureCalloutMessages.sys.mjs). In the Nulavio build that switch is off twice: the DisableFirefoxStudies policy the
build ships (distribution/policies.json) sets it off and locks it, and firefox-branding.js makes off its default, which
is what is left if the policy ever goes. test_00 reads the switch; test_01 creates a tab group on a new profile the way
the tab menu does, with the engine's own network log on from the first moment of the process (as
test_new_profile_connections does), and sees no tip and no request for the artwork. Its control turns the switch on in
the same window and sees both, so the check cannot pass on an engine where the tip never comes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import connections
import harness

SWITCH = "browser.newtabpage.activity-stream.asrouter.userprefs.cfr.features"
TIP = "CREATE_TAB_GROUP_ONBOARDING_CALLOUT"
ARTWORK = "https://firefox-settings-attachments.cdn.mozilla.net/main-workspace/ms-images/"

# The messaging system as the window has it: whether it listens for a new tab group, the tips it holds for one, what
# it has shown, the switch, and the callout on screen with its images.
STATE = """
const { ASRouter } = ChromeUtils.importESModule("resource:///modules/asrouter/ASRouter.sys.mjs");
const { ASRouterTriggerListeners } = ChromeUtils.importESModule(
  "resource:///modules/asrouter/ASRouterTriggerListeners.sys.mjs");
const name = arguments[0];
const callout = document.getElementById("feature-callout");
return {
  listening: Boolean(ASRouter.initialized && ASRouterTriggerListeners.get("tabGroupCreated")?._initialized),
  tips: ASRouter.state.messages.filter(m => m.trigger?.id === "tabGroupCreated").map(m => m.id),
  shown: Object.keys(ASRouter.state.messageImpressions ?? {}),
  switch: { value: Services.prefs.getBoolPref(name), user: Services.prefs.prefHasUserValue(name),
            locked: Services.prefs.prefIsLocked(name) },
  callout: callout && {
    open: callout.state === "open" || (!callout.hidden && !callout.classList.contains("hidden")
      && callout.getBoundingClientRect().height > 0),
    images: [...callout.querySelectorAll("img")].map(i => i.src),
  },
};
"""

# What the messaging system did with each new tab group: the tip it put on screen, or null. Read from the engine's own
# call, so "nothing" is an answer the engine gave, not a wait that ran out.
WATCH = """
const { ASRouter } = ChromeUtils.importESModule("resource:///modules/asrouter/ASRouter.sys.mjs");
if (!ASRouter.nulavioTestRouted) {
  const own = ASRouter.sendTriggerMessage;
  ASRouter.nulavioTestRouted = [];
  ASRouter.sendTriggerMessage = function (trigger, ...rest) {
    const result = own.call(this, trigger, ...rest);
    if (trigger?.id === "tabGroupCreated") {
      ASRouter.nulavioTestRouted.push(result.then(r => r?.message?.id ?? null, e => "error: " + e));
    }
    return result;
  };
}
"""

# A tab group made as the tab menu makes one (a user-triggered addTabGroup opens the group editor), then "Done".
CREATE_GROUP = """
const [label, done] = [arguments[0], arguments[arguments.length - 1]];
(async () => {
  const { ASRouter } = ChromeUtils.importESModule("resource:///modules/asrouter/ASRouter.sys.mjs");
  const routed = ASRouter.nulavioTestRouted;
  const before = routed.length;
  const tick = () => new Promise(r => window.setTimeout(r, 100));
  const tab = gBrowser.addTrustedTab("about:blank");
  const editor = gBrowser.tabGroupMenu;
  const panel = editor.querySelector("panel");
  const opened = new Promise(r => panel.addEventListener("popupshown", r, { once: true }));
  const group = gBrowser.addTabGroup([tab], {
    label,
    metricsContext: gBrowser.TabMetrics.userTriggeredContext(gBrowser.TabMetrics.METRIC_SOURCE.TAB_MENU),
  });
  const shown = await Promise.race([opened.then(() => true), new Promise(r => window.setTimeout(() => r(false), 10000))]);
  if (!shown) return { error: "the group editor did not open" };
  editor.querySelector("#tab-group-editor-button-create").click();
  for (let i = 0; routed.length === before; i++) {
    if (i > 100) return { error: "the messaging system was not told about the new group" };
    await tick();
  }
  return { group: group.label, tabs: group.tabs.length, routed: await routed[before] };
})().then(done, e => done({ error: String(e) }));
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class FeatureCalloutsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.session.env["MOZ_LOG"] = connections.ENGINE_LOG
        self.session.env["MOZ_LOG_FILE"] = str(self.session.tmp / "engine")
        self.m = self.session.start()

    def state(self) -> dict:
        return self.m.chrome(STATE, [SWITCH])

    def create_group(self, label: str) -> dict:
        self.m.set_context("chrome")
        try:
            result = self.m.execute_async(CREATE_GROUP, [label])
        finally:
            self.m.set_context("content")
        self.assertNotIn("error", result, result)
        self.assertEqual((result["group"], result["tabs"]), (label, 1), result)
        return result

    def artwork_asked(self) -> list[str]:
        addresses, _ = connections.read_log(self.session.tmp)
        return sorted({connections.without_query(a) for a in addresses if a.startswith(ARTWORK)})

    def ready(self) -> dict:
        """The engine is ready to answer: it listens for new tab groups and holds the tip (a wait for that state, so a
        group made before the messaging system starts cannot pass for one it saw)."""
        state = harness.wait_until(lambda: (s := self.state())["listening"] and TIP in s["tips"] and s, 60)
        self.assertTrue(state, self.state())
        return state

    def test_00_the_switch_is_off_and_the_studies_policy_locks_it(self):
        state = self.ready()
        self.assertEqual(state["switch"], {"value": False, "user": False, "locked": True})
        policies = self.m.chrome("return Services.policies.getActivePolicies()?.DisableFirefoxStudies ?? null;")
        self.assertIs(policies, True, "the policy that locks the switch (scripts/build/make_distribution.py)")

    def test_01_a_new_tab_group_brings_no_tip_and_no_request_for_mozillas_artwork(self):
        self.ready()  # the switch itself is test_00's
        self.m.chrome(WATCH)
        first = self.create_group("Trabalho")
        self.assertIsNone(first["routed"], "the messaging system showed a tip for the first tab group")
        state = self.state()
        self.assertIsNone(state["callout"], state)
        self.assertNotIn(TIP, state["shown"])
        self.assertEqual(self.artwork_asked(), [], "Mozilla's CDN was asked for the tip's artwork")
        # Control: the switch on (unlocked first where the policy locks it, test-only), and the next group brings the
        # tip with Mozilla's artwork and its request: what a new profile of the 161 engine does with the engine's
        # default and no policy.
        locked = state["switch"]["locked"]
        self.m.chrome("Services.prefs.unlockPref(arguments[0]); Services.prefs.setBoolPref(arguments[0], true);", [SWITCH])
        try:
            second = self.create_group("Estudos")
            self.assertEqual(second["routed"], TIP, second)
            shown = harness.wait_until(lambda: (s := self.state()["callout"]) and s["open"] and s["images"] and s, 15)
            self.assertTrue(shown, self.state())
            self.assertTrue(any(src.startswith(ARTWORK) for src in shown["images"]), shown)
            asked = harness.wait_until(self.artwork_asked, 15)
            self.assertTrue(asked, "the engine's network log did not show the artwork the tip loads")
        finally:
            self.m.chrome(
                "Services.prefs.clearUserPref(arguments[0]); if (arguments[1]) Services.prefs.lockPref(arguments[0]);",
                [SWITCH, locked],
            )


if __name__ == "__main__":
    unittest.main()
