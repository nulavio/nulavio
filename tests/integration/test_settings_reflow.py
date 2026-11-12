"""The settings page's Nulavio groups at a narrow window and at 200 % text (WCAG 1.4.10 and 1.4.4, issue #108).

The page is the engine's and its groups are drawn by the engine's widgets, so what is measured is what Nulavio adds:
each pane with the engine's groups hidden, against the same page with every group hidden.

* At 390 px, and at 200 % text in a window of ordinary width, Nulavio's groups add no sideways scroll, none of their
  controls or texts is cut by the edge of the page, and no word of theirs is broken across lines.
* At 320 px the engine's page scrolls sideways by itself, with nothing in it, and its own Home and Search panes more.
  Three of Nulavio's lists add to that there: a row keeps its buttons beside its name, and the engine's row does not
  wrap them, so the name is left a few pixels. They are named in KNOWN_AT_320: another control fails this test, and a
  fix shortens the list.
"""

from __future__ import annotations

import time
import unittest

import harness
import settings_page

# Panes that hold a Nulavio group, as the page's navigation names them.
PANES = (
    "paneAppearance",
    "paneNulavioProfiles",
    "panePrivacy",
    "panePasswordsAutofill",
    "paneSearch",
    "paneTabsBrowsing",
    "paneNulavioIntegrations",
    "paneAbout",
)
# Controls that, alone on the page at 320 px, make it scroll sideways further than the empty page does.
KNOWN_AT_320 = {"nulavio-profile-list", "nulavio-search-providers", "nulavio-passwords-providers"}

MEASURE = (
    settings_page.DOC
    + r"""
const main = d.querySelector(".main-content");
const extra = () => main.scrollWidth - main.clientWidth;
const all = (root, list = []) => {
  for (const el of root.querySelectorAll("*")) { list.push(el); if (el.shadowRoot) all(el.shadowRoot, list); }
  return list; };
const up = el => el.parentElement || (el.getRootNode() instanceof w.ShadowRoot ? el.getRootNode().host : null);
const owner = el => { for (let e = el; e; e = up(e)) { if (e.id?.startsWith("nulavio")) return e.id; } return ""; };
const shown = el => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
  for (let e = el; e; e = up(e)) {
    const s = w.getComputedStyle(e);
    if (s.visibility === "hidden" || s.display === "none") return false;
  }
  return true; };
const words = el => (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40);
const name = el => `${owner(el)}: ${el.localName} ${words(el)}`.trim();
const groups = [...d.querySelectorAll("setting-group")].filter(g => g.getBoundingClientRect().height > 0);
const id = g => g.getAttribute("groupid") || g.id || "";
const ours = groups.filter(g => id(g).startsWith("nulavio"));
const only = (list, keep, measure) => { const saved = list.map(x => x.style.display);
  list.forEach(x => { if (!keep(x)) x.style.display = "none"; });
  try { return measure(); } finally { list.forEach((x, i) => { x.style.display = saved[i]; }); } };
const report = { viewport: w.innerWidth, groups: ours.map(id), cut: [], broken: [], alone: {} };
report.empty = only(groups, () => false, extra);
// Nulavio's groups with the engine's hidden: what they add, and what of theirs the page's edge cuts.
only(groups, g => ours.includes(g), () => {
  report.ours = extra();
  const edge = main.getBoundingClientRect().left + main.clientWidth + report.empty + 1;
  const els = ours.flatMap(g => all(g)).filter(shown);
  for (const el of els) {
    const text = [...el.childNodes].filter(n => n.nodeType === 3 && n.data.trim());
    const target = el.matches("button, a[href], input, select, textarea, [role=button], [role=radio], [role=switch]");
    if (!target && !text.length) continue;
    const r = el.getBoundingClientRect();
    const span = `${Math.round(r.left)}..${Math.round(r.right)} of ${Math.round(edge)}`;
    if (r.right > edge || r.left < -1) report.cut.push(`${name(el)} (${span})`);
    for (const node of text) {
      const range = d.createRange(); range.selectNodeContents(node);
      const lines = new Set([...range.getClientRects()].map(b => Math.round(b.top))).size;
      if (lines > node.data.trim().split(/[\s\-\/.]+/).length) report.broken.push(name(el));
    }
  }
});
// Each of Nulavio's controls alone on the page.
for (const group of ours) {
  only(groups, g => g === group, () => {
    const controls = [...group.querySelectorAll("setting-control")]
      .filter(c => c.getBoundingClientRect().height > 0 && !c.parentElement.closest("setting-control"));
    for (const control of controls) {
      const key = control.querySelector("[id]")?.id || control.firstElementChild?.localName;
      report.alone[key] = only(controls, c => c === control, extra);
    }
  });
}
return report;
"""
)


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsReflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.addClassCleanup(cls.session.cleanup)
        cls.m = cls.session.start()
        settings_page.open_pane(cls.m, "paneAbout")
        cls.m.chrome("document.documentElement.style.minWidth = '0px';")

    def size(self, width: int, text: float) -> None:
        """The page's own width (the window minus what the sidebar takes) and its text zoom."""
        side = self.m.chrome("return innerWidth - gBrowser.selectedBrowser.getBoundingClientRect().width;")
        outer = round(width + side)
        for _ in range(6):
            self.m.send("WebDriver:SetWindowRect", {"width": outer, "height": 900})
            time.sleep(0.25)
            actual = self.m.chrome(settings_page.DOC + "return w.innerWidth;")
            if actual == width:
                break
            outer += width - actual
        self.m.chrome("gBrowser.selectedBrowser.browsingContext.textZoom = arguments[0];", [text])
        time.sleep(0.5)

    def measure(self, pane: str, width: int, text: float = 1) -> dict:
        settings_page.open_pane(self.m, pane)
        self.size(width, text)
        report = self.m.chrome(MEASURE)
        self.assertEqual(report["viewport"], width, "the window did not reach the width")
        self.assertTrue(report["groups"], f"{pane} holds no Nulavio group: the list of panes is out of date")
        return report

    def panes(self) -> tuple[str, ...]:
        return (*PANES, "paneAi" if settings_page.assistant_pane(self.m) == "ai" else "paneNulavioAssistant")

    def test_01_narrow_window_and_large_text_cut_nothing_of_nulavios(self):
        for width, text in ((390, 1), (1180, 2)):
            for pane in self.panes():
                with self.subTest(pane=pane, width=width, text=text):
                    report = self.measure(pane, width, text)
                    self.assertLessEqual(report["ours"], report["empty"], "Nulavio's groups make the page scroll sideways")
                    self.assertEqual(report["cut"], [], "cut by the edge of the page")
                    self.assertEqual(report["broken"], [], "a word broken across lines")

    def test_02_at_320_px_only_the_known_lists_add_to_the_engines_own_scroll(self):
        empty, adding = set(), set()
        for pane in self.panes():
            report = self.measure(pane, 320)
            empty.add(report["empty"])
            adding.update(key for key, extra in report["alone"].items() if extra > report["empty"])
        self.assertGreater(min(empty), 0, "the engine's empty page no longer scrolls sideways at 320 px: tighten this test")
        self.assertEqual(adding, KNOWN_AT_320)


if __name__ == "__main__":
    unittest.main()
