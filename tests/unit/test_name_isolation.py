"""#796: a search engine's name goes into a sentence isolated, so direction controls in it cannot reorder the sentence.

An engine names itself (an OpenSearch description or an add-on), and Nulavio Search refuses only C0 controls and DEL in
a name. A name that holds U+202E RIGHT-TO-LEFT OVERRIDE, put into "$NAME$ is this profile's search..." as it is, makes
the words after it show in reverse. `inSentence` (browser/shell/lib/names.js) removes the direction controls and wraps
the name in U+2068 FIRST STRONG ISOLATE ... U+2069 POP DIRECTIONAL ISOLATE. Here it runs under Node and fills the
Settings and new-tab sentences that carry an engine's name, in both locales; tests/integration/test_settings_search.py
(06) reads the same sentences on the real page. The callers put the name in through `engineInSentence`, which also adds
the host of an engine that is not a curated provider (#828, tests/unit/test_engine_in_sentence.py).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from node_tool import requires_node  # noqa: E402

SHELL = ROOT / "browser" / "shell"
NAMES = SHELL / "lib" / "names.js"

FSI, PDI = "⁨", "⁩"
# What the helper must not let through: the embeddings and overrides, the isolates and the marks.
CONTROLS = re.compile("[؜‎‏‪-‮⁦-⁩]")
NAME = "‮Mal Arquivo‬ Busca⁧"
SHOWN = "Mal Arquivo Busca"
# A paragraph separator ends the paragraph and the isolate with it: the Hebrew after it would sit outside the isolate.
# Nulavio Search lets U+0085 through (it refuses only C0 and DEL), so each one becomes a space.
SEPARATORS = "\n\r\x1c\x1d\x1e\x85\u2029"
BROKEN = "Mal\x85\u05d0\u05e8\u05db\u05d9\u05d5\u2029Busca\nX"
# The sentences that carry an engine's name, and where they are filled in.
SENTENCES = {
    "chooseDone": "panes",
    "chooseDoneBoth": "panes",
    "chooseUseNamed": "panes",
    "searchAliasReserved": "panes",
    "searchWith": "newtab",
}

# names.js is read as a data: address, which is always a module, so a node that does not tell a .js file's kind by its
# syntax (Node 18) runs it too.
DRIVER = """
const { readFileSync } = await import("node:fs");
const source = readFileSync(process.argv[1], "utf8");
const { inSentence } = await import("data:text/javascript;charset=utf-8," + encodeURIComponent(source));
const names = JSON.parse(process.argv[2]);
console.log(JSON.stringify(names.map(name => inSentence(name))));
"""


def locale(name: str) -> dict:
    return json.loads((SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8"))


def fill(entry: dict, value: str) -> str:
    """The WebExtension substitution, for a message with one placeholder: $NAME$ -> $1 -> the value."""
    (placeholder,) = entry["placeholders"].values()
    text = entry["message"]
    for key in entry["placeholders"]:
        text = re.sub(re.escape(f"${key}$"), lambda _: placeholder["content"], text, flags=re.I)
    return text.replace("$1", value)


def isolated(text: str) -> bool:
    """Every isolate is closed, and no embedding or override is left open: the text after the name keeps its order."""
    depth = 0
    for char in text:
        if char in "⁦⁧⁨":
            depth += 1
        elif char == "⁩":
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0 and char in "‪‫‭‮":
            return False
    return depth == 0


@requires_node
class InSentenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = [NAME, "Mojeek", "", "‏؜‎", BROKEN]
        done = subprocess.run(
            ["node", "--input-type=module", "-e", DRIVER, str(NAMES), json.dumps(names)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.out = dict(zip(names, json.loads(done.stdout), strict=True))

    def test_a_name_is_isolated_and_loses_its_direction_controls(self):
        self.assertEqual(self.out[NAME], FSI + SHOWN + PDI)
        self.assertEqual(self.out["Mojeek"], FSI + "Mojeek" + PDI)
        self.assertEqual(self.out[""], FSI + PDI)
        self.assertEqual(self.out["‏؜‎"], FSI + PDI)

    def test_a_paragraph_separator_in_a_name_does_not_end_the_isolate(self):
        value = self.out[BROKEN]
        self.assertEqual(value, FSI + "Mal \u05d0\u05e8\u05db\u05d9\u05d5 Busca X" + PDI)
        self.assertFalse(set(value) & set(SEPARATORS), ascii(value))

    def test_the_words_after_the_name_keep_their_order_in_every_sentence(self):
        for language in ("en", "pt_BR"):
            messages = locale(language)
            for key in SENTENCES:
                with self.subTest(locale=language, key=key):
                    entry = messages[key]
                    # The name filled in as it is: the U+202E is open until the end of the sentence.
                    self.assertFalse(isolated(fill(entry, NAME)))
                    value = self.out[NAME]
                    if key == "searchAliasReserved":
                        value = f"“{value}”"
                    text = fill(entry, value)
                    self.assertTrue(isolated(text), ascii(text))
                    self.assertEqual(CONTROLS.sub("", text), fill(entry, f"“{SHOWN}”" if key == "searchAliasReserved" else SHOWN))
                    # The words after the name are the message's own, in the order written.
                    after = re.split(r"\$\w+\$", entry["message"], maxsplit=1)[1]
                    self.assertTrue(text.endswith(PDI + ("”" if key == "searchAliasReserved" else "") + after), ascii(text))


class CallersIsolateTest(unittest.TestCase):
    """Every place that puts an engine's name into one of these sentences goes through the helper: `engineInSentence`
    (the same file), which isolates the name with `inSentence` and adds the host of an engine that is not a curated
    provider (#828, tests/unit/test_engine_in_sentence.py)."""

    def test_the_engine_helper_isolates_the_name(self):
        names = NAMES.read_text(encoding="utf-8")
        body = re.search(r"export function engineInSentence\(.*?\n\}", names, re.S).group(0)
        self.assertIn("`“${inSentence(engine?.name)}”` : inSentence(engine?.name);", body)

    def test_settings_isolates_each_engine_name(self):
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        self.assertRegex(
            panes, r"\bengineInSentence\b[^}]*\} = ChromeUtils\.importESModule\(\s*\"resource://[^\"]+/lib/names\.js\""
        )
        self.assertRegex(panes, r"const named = \(engine, quoted = false\) =>\s+engineInSentence\(engine, ")
        self.assertIn('msg("chooseUseNamed", rowInSentence(row))', panes)
        self.assertIn('"chooseDoneBoth" : "chooseDone", row.provider ? rowInSentence(row) : named(chosen))', panes)
        self.assertIn('msg("searchAliasReserved", releasedNow().map(engine => named(engine, true)).join(", "))', panes)
        # The suggestions switch's accessible name carries the engine's name too, after its label.
        self.assertIn('"aria-label": `${msg("engineSuggestLabel")}: ${named(engine)}`', panes)
        self.assertNotRegex(panes, r"\$\{(engine|row)\.name\}")
        for key in [key for key, where in SENTENCES.items() if where == "panes"]:
            with self.subTest(key=key):
                for call in re.findall(rf'"{key}"[^\n]*', panes):
                    self.assertRegex(call, r"\b(rowInSentence|named)\(")

    def test_the_new_tab_isolates_the_engine_name(self):
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        self.assertIn('import { engineInSentence } from "../lib/names.js";', newtab)
        self.assertEqual(len(re.findall(r't\("searchWith", \[engineInSentence\(engine, ', newtab)), 1)
        self.assertEqual(len(re.findall(r't\("searchWith"', newtab)), 1)


if __name__ == "__main__":
    unittest.main()
