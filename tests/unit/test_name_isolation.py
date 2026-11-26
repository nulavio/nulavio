"""#796: a search engine's name goes into a sentence isolated, so direction controls in it cannot reorder the sentence.

An engine names itself (an OpenSearch description or an add-on), and Nulavio Search refuses only C0 controls and DEL in
a name. A name that holds U+202E RIGHT-TO-LEFT OVERRIDE, put into "$NAME$ is this profile's search..." as it is, makes
the words after it show in reverse. `inSentence` (browser/shell/lib/names.js) removes the direction controls and wraps
the name in U+2068 FIRST STRONG ISOLATE ... U+2069 POP DIRECTIONAL ISOLATE. Here it runs under Node and fills the
Settings and new-tab sentences that carry an engine's name, in both locales; tests/integration/test_settings_search.py
(06) reads the same sentences on the real page.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
NAMES = SHELL / "lib" / "names.js"

FSI, PDI = "⁨", "⁩"
# What the helper must not let through: the embeddings and overrides, the isolates and the marks.
CONTROLS = re.compile("[؜‎‏‪-‮⁦-⁩]")
NAME = "‮Mal Arquivo‬ Busca⁧"
SHOWN = "Mal Arquivo Busca"
# The sentences that carry an engine's name, and where they are filled in.
SENTENCES = {
    "chooseDone": "panes",
    "chooseDoneBoth": "panes",
    "chooseUseNamed": "panes",
    "searchAliasReserved": "panes",
    "searchWith": "newtab",
}

DRIVER = """
const { inSentence } = await import(process.argv[1]);
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


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class InSentenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = [NAME, "Mojeek", "", "‏؜‎"]
        done = subprocess.run(
            ["node", "--input-type=module", "-e", DRIVER, NAMES.as_uri(), json.dumps(names)],
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
    """Every place that puts an engine's name into one of these sentences goes through the helper."""

    def test_settings_isolates_each_engine_name(self):
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        self.assertRegex(panes, r"\binSentence\b[^}]*\} = ChromeUtils\.importESModule\(\s*\"resource://[^\"]+/lib/names\.js\"")
        self.assertIn('msg("chooseUseNamed", inSentence(row.name))', panes)
        self.assertIn('"chooseDoneBoth" : "chooseDone", inSentence(row.name))', panes)
        self.assertIn('msg("searchAliasReserved", releasedNow().map(name => `“${inSentence(name)}”`).join(", "))', panes)
        for key in [key for key, where in SENTENCES.items() if where == "panes"]:
            with self.subTest(key=key):
                for call in re.findall(rf'"{key}"[^\n]*', panes):
                    self.assertIn("inSentence(", call)

    def test_the_new_tab_isolates_the_engine_name(self):
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        self.assertIn('import { inSentence } from "../lib/names.js";', newtab)
        self.assertEqual(re.findall(r't\("searchWith", [^)]*\)\]?\)', newtab), ['t("searchWith", [inSentence(name)])'])


if __name__ == "__main__":
    unittest.main()
