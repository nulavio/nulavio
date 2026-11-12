"""ADR 0008: "managed by your organization" is the engine's line for a policy somebody set, not for Nulavio's own.

Nulavio ships a few policies of its own (its content blocker, no telemetry, no studies), so the engine showed that
line on every pane to everyone, and it would also be the only sign of a policy added by someone else. The settings
page drops it only while the policies in effect were read and are exactly the build's own, and "Sobre" then says
how many those are. Another policy, a read that failed or a state not read yet leave the engine's line in place.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import harness
import settings_page

MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs")'
GUARD = f"{MODULE}.NulavioGuard"
NOTICE = (
    settings_page.DOC
    + 'const n = d.getElementById("policies-container-content");'
    + "return { shown: !n.hidden && n.getBoundingClientRect().height > 0, link: n.getAttribute('href'),"
    + ' own: d.documentElement.hasAttribute("nulavio-own-policies") };'
)
# What coming back to the tab does: every value the page read is read again.
AGAIN = settings_page.DOC + 'd.dispatchEvent(new w.Event("visibilitychange")); return true;'
ROW = "nulavio-policies"


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsPoliciesTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        shipped = Path(harness.nulavio_engine().path).parent / "distribution" / "policies.json"
        self.shipped = json.loads(shipped.read_text(encoding="utf-8"))["policies"]

    def notice(self, shown: bool) -> dict:
        harness.wait_until(lambda: self.m.chrome(NOTICE)["shown"] is shown, 10)
        return self.m.chrome(NOTICE)

    def answer(self, body: str) -> None:
        """Replace what the Guard says about the policies, and have the page read it again."""
        self.m.chrome(f"window.nvPolicies ??= {GUARD}.policiesOrigin; {GUARD}.policiesOrigin = async () => {{ {body} }};")
        self.m.chrome(AGAIN)

    def restore(self) -> None:
        self.m.chrome(f"if (window.nvPolicies) {{ {GUARD}.policiesOrigin = window.nvPolicies; delete window.nvPolicies; }}")

    def test_01_only_nulavios_own_policies_no_managed_line_and_sobre_says_how_many(self):
        count = len(self.shipped)
        self.assertGreater(count, 0)
        self.assertEqual(self.m.chrome(f"return {GUARD}.policiesOrigin();"), {"origin": "own", "count": count})
        for pane in ("", "privacy", "paneAbout"):
            with self.subTest(pane=pane):
                settings_page.open_pane(self.m, pane)
                settings_page.wait_control(self.m, ROW, lambda now: now["label"])  # the read arrived
                self.assertEqual(self.notice(False), {"shown": False, "link": "about:policies", "own": True})
        row = settings_page.wait_control(self.m, ROW)
        self.assertEqual(row["label"], f"O Nulavio aplica {count} políticas próprias")
        self.assertEqual(row["description"], "Elas vêm com o Nulavio, e nenhuma outra está em vigor. Veja quais são.")
        # The row leads to the engine's own list of them.
        tabs = "return gBrowser.browsers.map(b => b.currentURI.spec);"
        settings_page.click(self.m, f"#{ROW}")
        self.assertTrue(harness.wait_until(lambda: "about:policies" in self.m.chrome(tabs), 10), self.m.chrome(tabs))

    def test_02_another_policy_or_a_failed_read_keeps_the_engines_line(self):
        self.addCleanup(self.restore)
        settings_page.open_pane(self.m, "paneAbout")
        settings_page.wait_control(self.m, ROW)
        self.assertFalse(self.notice(False)["shown"])
        # A policy that is not Nulavio's: the engine's line is back on the page, and the row says so.
        self.answer('return { origin: "other", count: 4 };')
        self.assertEqual(self.notice(True), {"shown": True, "link": "about:policies", "own": False})
        row = settings_page.wait_control(self.m, ROW, lambda now: now["label"] == "4 políticas em vigor")
        self.assertIn("não são exatamente as que vêm com o Nulavio", row["description"])
        # A read that fails is not "only Nulavio's": the line stays, the row goes and the group says it could not read.
        self.answer('throw new Error("fixture");')
        settings_page.wait_control(self.m, "nulavio-policies-failed")
        self.assertTrue(self.notice(True)["shown"])
        self.assertFalse(settings_page.control(self.m, ROW)["shown"])
        # Read again as only Nulavio's: the line goes, the row is back.
        self.restore()
        self.m.chrome(AGAIN)
        self.assertFalse(self.notice(False)["shown"])
        self.assertFalse(settings_page.control(self.m, "nulavio-policies-failed")["shown"])
        self.assertTrue(settings_page.wait_control(self.m, ROW)["shown"])
        # A page loaded while another policy is in effect shows the line.
        self.answer('return { origin: "other", count: 4 };')
        settings_page.open_pane(self.m, "privacy")
        self.m.send("WebDriver:Refresh", {})  # the same address with another hash does not load the page again
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(settings_page.READY), 20))
        self.assertEqual(self.notice(True), {"shown": True, "link": "about:policies", "own": False})

    def test_03_what_counts_as_the_same_policies(self):
        same = f"return {MODULE}.samePolicies(arguments[0], arguments[1]);"
        ours = self.shipped
        reordered = dict(reversed(list(ours.items())))
        self.assertTrue(self.m.chrome(same, [ours, reordered]))
        # The engine fills some policies with empty values from the second start on: they set nothing.
        self.assertTrue(self.m.chrome(same, [ours | {"SitePolicies": [], "Empty": {}, "Nothing": None}, ours]))
        first = next(iter(ours))
        for label, other in (
            ("one added", ours | {"DisableAppUpdate": True}),
            ("one removed", {k: v for k, v in ours.items() if k != first}),
            ("one changed", ours | {first: "changed"}),
            ("a certificate added", ours | {"Certificates": {"Install": ["/tmp/ca.pem"]}}),
            ("no policies at all", {}),
        ):
            with self.subTest(label):
                self.assertFalse(self.m.chrome(same, [other, ours]))
        # A shipped file that could not be read equals nothing, and neither does something that is not a set of policies.
        for label, shipped in (("unreadable", None), ("a list", []), ("a string", "policies")):
            with self.subTest(label):
                self.assertFalse(self.m.chrome(same, [ours, shipped]))


if __name__ == "__main__":
    unittest.main()
