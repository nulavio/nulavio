"""The settings page's Nulavio groups at a narrow window and at 200 % text (WCAG 1.4.10 and 1.4.4, issue #108).

The page is the engine's and its groups are drawn by the engine's widgets, so what is measured is what Nulavio adds:
each pane with the engine's groups hidden, against the same page with every group hidden.

* At 390 px, at 320 px and at 200 % text in a window of ordinary width, Nulavio's groups add no sideways scroll to
  the engine's page (which scrolls by itself when narrow, with nothing in it), none of their controls or texts is
  cut by the edge of the page, and no word of theirs is broken across lines.
* A list's row is the engine's box item, which keeps the name and the buttons on one line and wraps neither. In a
  narrow page the buttons are a row of their own under the name, still work there, and go back beside the name when
  the page is wide again (issue #128).
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
PROFILES = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles'
# The profile list as drawn: each row's class, its name's width and lines, and where its buttons are.
LIST = (
    settings_page.DOC
    + """
const rows = [...d.querySelectorAll("#nulavio-profile-list > moz-box-item")].filter(r => r.getBoundingClientRect().height > 0);
return rows.map(r => {
  const label = r.shadowRoot?.querySelector(".label");
  const range = d.createRange();
  if (label) range.selectNodeContents(label);
  return { row: r.classList[0], name: r.label ?? "",
    lines: label ? new Set([...range.getClientRects()].map(b => Math.round(b.top))).size : 0,
    buttons: [...r.querySelectorAll(":scope > moz-button")].map(b => `${b.slot || "below"}:${b.dataset.action}`) };
});
"""
)

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
const report = { viewport: w.innerWidth, groups: ours.map(id), cut: [], broken: [] };
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
        for width, text in ((390, 1), (320, 1), (1180, 2)):
            for pane in self.panes():
                with self.subTest(pane=pane, width=width, text=text):
                    report = self.measure(pane, width, text)
                    self.assertLessEqual(report["ours"], report["empty"], "Nulavio's groups make the page scroll sideways")
                    self.assertEqual(report["cut"], [], "cut by the edge of the page")
                    self.assertEqual(report["broken"], [], "a word broken across lines")

    def test_02_a_rows_buttons_go_under_its_name_in_a_narrow_page_and_still_work(self):
        self.m.chrome(f'return {PROFILES}.create({{ templateId: "work", name: "Trabalho" }}).then(() => true);')
        settings_page.open_pane(self.m, "paneNulavioProfiles")
        profiles = lambda: [row for row in self.m.chrome(LIST) if row["row"] in ("nulavio-profile", "nulavio-row-actions")]  # noqa: E731
        beside = [
            {"row": "nulavio-profile", "name": "Pessoal", "lines": 1, "buttons": ["actions:edit", "actions:delete-here"]},
            {
                "row": "nulavio-profile",
                "name": "Trabalho",
                "lines": 1,
                "buttons": ["actions:open", "actions:edit", "actions:delete"],
            },
        ]
        below = [
            {"row": "nulavio-profile", "name": "Pessoal", "lines": 1, "buttons": []},
            {"row": "nulavio-row-actions", "name": "", "lines": 0, "buttons": ["below:edit", "below:delete-here"]},
            {"row": "nulavio-profile", "name": "Trabalho", "lines": 1, "buttons": []},
            {"row": "nulavio-row-actions", "name": "", "lines": 0, "buttons": ["below:open", "below:edit", "below:delete"]},
        ]
        for width, wanted in ((1180, beside), (390, below), (320, below), (1180, beside)):
            with self.subTest(width=width):
                self.size(width, 1)
                self.assertTrue(harness.wait_until(lambda wanted=wanted: profiles() == wanted, 10), profiles())
        # A button under its name does what it did beside it: the editor opens for that profile, and closes.
        self.size(390, 1)
        harness.wait_until(lambda: profiles() == below, 10)
        edit = '#nulavio-profile-list moz-button[data-action="edit"][data-profile]:not([data-action="delete-here"])'
        settings_page.click(self.m, edit)
        editor = lambda: [row["row"] for row in self.m.chrome(LIST)].count("nulavio-profile-editor")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: editor() == 1, 10), self.m.chrome(LIST))
        settings_page.click(self.m, edit)
        self.assertTrue(harness.wait_until(lambda: editor() == 0, 10), self.m.chrome(LIST))


if __name__ == "__main__":
    unittest.main()
