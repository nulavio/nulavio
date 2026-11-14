"""The parameters Nulavio adds to the engine's clean links (#158, docs/research/clean-links.md).

"Copy Clean Link to Highlight" on a local page whose address carries every
parameter of `privacy.query_stripping.strip_list` and the page's own `id=7`:
the link keeps `id=7` and drops the rest. The same address opened directly
still shows the page, and the request carries only `id=7`: Strict mode's query
stripping takes them off a navigation too. Runs on the Nulavio build, with its own defaults.
"""

from __future__ import annotations

import re
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

BASELINE = Path(__file__).resolve().parents[2] / "browser" / "config" / "prefs" / "baseline.js"
ADDED = re.search(r'"privacy\.query_stripping\.strip_list", "([^"]*)"', BASELINE.read_text(encoding="utf-8")).group(1).split()

MENU = """
const item = document.getElementById("context-copy-clean-link-to-highlight");
return { open: document.getElementById("contentAreaContextMenu").state === "open",
         shown: item ? !item.hidden : false, disabled: item ? item.disabled : true };
"""

CLIPBOARD = """
const trans = Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);
trans.init(null);
trans.addDataFlavor("text/plain");
Services.clipboard.getData(trans, Ci.nsIClipboard.kGlobalClipboard, null);
const data = {};
try { trans.getTransferData("text/plain", data); } catch (e) { return null; }
return data.value.QueryInterface(Ci.nsISupportsString).data;
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class CleanLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        query = urllib.parse.urlencode([("id", "7"), *((name, f"t{i}") for i, name in enumerate(ADDED))])
        cls.page = cls.server.url(f"/highlight?{query}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def test_01_the_build_has_the_list(self):
        value = self.m.chrome("return Services.prefs.getStringPref('privacy.query_stripping.strip_list', '');")
        self.assertEqual(value.split(), ADDED)

    def test_02_a_clean_link_drops_each_added_parameter_and_keeps_the_pages_own(self):
        self.m.navigate(self.page)
        self.m.chrome("Services.clipboard.emptyClipboard(Ci.nsIClipboard.kGlobalClipboard);")
        self.m.execute(
            "const r = document.createRange(); r.selectNodeContents(document.getElementById('target'));"
            "getSelection().removeAllRanges(); getSelection().addRange(r);"
            "document.getElementById('target').scrollIntoView({block: 'center'});"
        )
        self.m.context_click("#target")
        try:
            usable = lambda state: state["open"] and state["shown"] and not state["disabled"]  # noqa: E731
            ready = harness.wait_until(lambda: usable(self.m.chrome(MENU)), 10)
            self.assertTrue(ready, self.m.chrome(MENU))
            self.m.chrome(
                "document.getElementById('contentAreaContextMenu')"
                ".activateItem(document.getElementById('context-copy-clean-link-to-highlight'));"
            )
            copied = harness.wait_until(lambda: self.m.chrome(CLIPBOARD) or None, 10)
        finally:
            self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        self.assertTrue(copied, "nothing reached the clipboard")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(copied).query)
        self.assertEqual(query, {"id": ["7"]}, copied)

    def test_03_the_address_with_them_still_opens_the_same_page(self):
        self.m.navigate(self.page)
        self.assertEqual(self.m.title(), "highlight")
        self.assertIn("frase sem igual", self.m.execute("return document.getElementById('target').textContent;"))
        # What reached the server: the page's own parameter, and none of the added ones. Strict mode's query
        # stripping (qps) takes them off the navigation too, as docs/research/clean-links.md says.
        asked = [hit for hit in self.server.hits if hit.startswith("/highlight?")][-1]
        print(f"asked: {asked}", file=sys.stderr)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(asked).query), {"id": ["7"]}, asked)


if __name__ == "__main__":
    unittest.main()
