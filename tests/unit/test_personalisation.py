"""UX6 safe personalisation: no option can turn a protection off.

Every option Nulavio offers is declared once in browser/shell/shared/options.json. These tests
prove, from that one list, that no option writes a protection pref (the Guard's lists, the
forbidden map, the baseline and a guarded prefix set), and they pin every pref writer in every
privileged module, so a new writer anywhere needs a reviewed change here.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nulavio_launcher import profile  # noqa: E402
from test_prefs_and_guard import FORBIDDEN  # noqa: E402

OPTIONS = SHELL / "shared" / "options.json"
KINDS = {"cosmetic", "routing", "command", "quick-action"}

# Prefixes and names an option may never write: protections, what sites can see about the
# system (LookAndFeel), telemetry and remote control, and Nulavio's own protection prefs.
GUARDED_PREFIXES = (
    "privacy.",
    "network.",
    "security.",
    "browser.safebrowsing.",
    "dom.security.",
    "browser.contentblocking.",
    "browser.search.",
    "signon.",
    "extensions.",
    "xpinstall.",
    "app.update.",
    "services.settings.",
    "fission.",
    "media.peerconnection.",
    "devtools.",
    "remote.",
    "marionette.",
    "general.config.",
    "permissions.",
    "identity.",
    "datareporting.",
    "toolkit.telemetry.",
    "browser.ml.",
    "ui.",
    "browser.display.document_color_use",
    "layout.css.prefers-reduced-transparency.enabled",
    "browser.startup.homepage",
    "browser.newtabpage.enabled",
    "nulavio.ai.",
    "nulavio.assistant.",
    "nulavio.guard.",
    "nulavio.passwords.",
    "nulavio.dns.",
    "nulavio.privacy.",
    "nulavio.routing.",
    "nulavio.vault.",
    "nulavio.profile.",
    "nulavio.profiles.",
    "nulavio.search.",
    "nulavio.connect.",
)

# The only guarded prefs an option may write, each tied to the one kind whose behaviour tests cover it.
ALLOWED_BY_KIND = {"routing": {"nulavio.routing.fallbackProfile"}}

# Every Services.prefs writer in the privileged code, by its first argument. A new writer anywhere
# fails here until it is reviewed: an option could otherwise reach a protection through another module.
PREF_WRITERS = {
    "NulavioConnect.sys.mjs": {"PREF_PREVIOUS"},
    "NulavioGuard.sys.mjs": {"name"},
    "NulavioLayout.sys.mjs": {
        '"sidebar.verticalTabs"',
        '"sidebar.visibility"',
        "PREF_ADOPTION_VERSION",
        "PREF_CHOICE_PENDING",
        "PREF_SHELL_START",
    },
    "NulavioPasswords.sys.mjs": {"name", "PREF_DISMISSED"},
    # Only the declared pref of an option in options.json (test_the_appearance_writer_takes_its_pref_from_the_list).
    "NulavioPersonalise.sys.mjs": {"pref"},
    "NulavioPrivacy.sys.mjs": {
        '"browser.contentblocking.category"',
        '"network.trr.custom_uri"',
        '"network.trr.mode"',
        '"network.trr.uri"',
        "PREF_DNS_CHOSEN",
        "PREF_FIRSTRUN",
        "PREF_SEEDED",
    },
    "NulavioProfiles.sys.mjs": {"PREF_COLORS", "PREF_COLOR_MIGRATION"},
    "NulavioRouting.sys.mjs": {"ENABLED_PREF", "IN_PAGE_PREF", "RULES_PREF"},
    "NulavioSearch.sys.mjs": {"PREF_MIGRATION", "PREF_OPTIN", "pref"},
}
WRITER = re.compile(r"\.(?:set(?:Bool|Int|String|Char)Pref|clearUserPref|lockPref|unlockPref)\(\s*([^,)]+)")
PRIVILEGED_CODE = (SHELL / "modules", ROOT / "browser" / "branding" / "nulavio", SHELL / "experiments", SHELL / "background.js")


def options() -> list[dict]:
    return json.loads(OPTIONS.read_text(encoding="utf-8"))["options"]


def locale(name: str) -> dict:
    return json.loads((SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8"))


def watched_prefs() -> list[str]:
    source = (SHELL / "modules" / "NulavioGuard.sys.mjs").read_text(encoding="utf-8")
    block = source[source.index("WATCHED_PREFS = Object.freeze([") :]
    return re.findall(r'"([^"]+)"', block[: block.index("]);")])


def sensitive_prefs() -> list[str]:
    source = (SHELL / "modules" / "NulavioProfiles.sys.mjs").read_text(encoding="utf-8")
    block = source[source.index("SENSITIVE_PREFS = Object.freeze({") :]
    return re.findall(r'^\s*"([^"]+)":', block[: block.index("});")], re.M)


def guarded_names() -> set[str]:
    rules = json.loads((ROOT / "browser" / "config" / "guard-rules.json").read_text(encoding="utf-8"))["rules"]
    baseline = [p.name for p in profile.baseline_prefs() if p.category not in {"ui", "theme"}]
    return set(watched_prefs()) | set(FORBIDDEN) | {r["pref"] for r in rules} | set(sensitive_prefs()) | set(baseline)


def is_guarded(pref: str, names: set[str]) -> bool:
    if pref in names or pref.startswith(GUARDED_PREFIXES):
        return True
    # WATCHED_PREFS entries ending in "." watch a whole branch.
    return any(name.endswith(".") and pref.startswith(name) for name in names)


def violations(entries: list[dict], names: set[str]) -> list[str]:
    """Each option pref that is guarded and not the reviewed exception of its kind."""
    found = []
    for option in entries:
        allowed = ALLOWED_BY_KIND.get(option["kind"], set())
        for pref in option.get("prefs", []):
            if is_guarded(pref, names) and pref not in allowed:
                found.append(f"{option['id']}: {pref}")
    return found


class _Ids(HTMLParser):
    """Element ids and their data-option value in a static page."""

    def __init__(self):
        super().__init__()
        self.by_id: dict[str, str | None] = {}
        self.marked: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.by_id[attrs["id"]] = attrs.get("data-option")
        if "data-option" in attrs:
            self.marked.append(attrs["data-option"])


def page_ids(relative: str) -> _Ids:
    parser = _Ids()
    parser.feed((SHELL / relative).read_text(encoding="utf-8"))
    return parser


class OptionListTest(unittest.TestCase):
    def test_every_option_is_declared_once_with_a_valid_domain(self):
        entries = options()
        ids = [o["id"] for o in entries]
        self.assertEqual(len(ids), len(set(ids)), ids)
        pt, en = locale("pt_BR"), locale("en")
        for option in entries:
            with self.subTest(option=option["id"]):
                self.assertIn(option["kind"], KINDS)
                self.assertTrue(option["values"], "an option needs its values")
                self.assertEqual(len(option["values"]), len(set(map(json.dumps, option["values"]))))
                self.assertIn(option["default"], option["values"])
                self.assertIn(option["labelKey"], pt)
                self.assertIn(option["labelKey"], en)
                self.assertTrue((SHELL / "modules" / f"{option['writer']}.sys.mjs").exists(), option["writer"])
                if option["writer"] == "NulavioPersonalise":
                    # One pref, one pref value per choice, and the default is the cleared pref.
                    self.assertEqual(len(option["prefs"]), 1)
                    self.assertIn(option["prefType"], {"int", "bool", "string"})
                    self.assertEqual(len(option["prefValues"]), len(option["values"]))
                    self.assertEqual(option["prefValues"].count(None), 1)
                    self.assertIsNone(option["prefValues"][option["values"].index(option["default"])])
                    kinds = {"int": int, "bool": bool, "string": str}
                    for value in option["prefValues"]:
                        if value is not None:
                            self.assertIs(type(value), kinds[option["prefType"]], value)

    def test_no_option_writes_a_protection_pref(self):
        self.assertEqual(violations(options(), guarded_names()), [])

    def test_the_protection_check_fails_closed(self):
        names = guarded_names()
        for pref in (
            "privacy.trackingprotection.enabled",
            "ui.useAccessibilityTheme",
            "ui.prefersReducedTransparency",
            "signon.rememberSignons",
            "nulavio.ai.anything",
            "browser.safebrowsing.malware.enabled",
            "network.trr.mode",
            "xpinstall.signatures.required",
        ):
            with self.subTest(pref=pref):
                bad = [{"id": "x", "kind": "cosmetic", "prefs": [pref]}]
                self.assertEqual(violations(bad, names), [f"x: {pref}"])
        # The routing exception is the one pref its kind is reviewed for, nothing next to it.
        self.assertEqual(violations([{"id": "r", "kind": "routing", "prefs": ["nulavio.routing.fallbackProfile"]}], names), [])
        self.assertEqual(
            violations([{"id": "r", "kind": "routing", "prefs": ["nulavio.routing.enabled"]}], names),
            ["r: nulavio.routing.enabled"],
        )
        self.assertEqual(
            violations([{"id": "c", "kind": "cosmetic", "prefs": ["nulavio.routing.fallbackProfile"]}], names),
            ["c: nulavio.routing.fallbackProfile"],
        )

    def test_the_guarded_set_reads_every_source(self):
        names = guarded_names()
        # One from each source, so a parser that silently returns nothing fails here.
        for name in (
            "network.proxy.type",  # WATCHED_PREFS
            "security.OCSP.enabled",  # FORBIDDEN
            "security.sandbox.content.level",  # guard-rules.json
            "privacy.sanitize.sanitizeOnShutdown",  # SENSITIVE_PREFS
        ):
            self.assertTrue(is_guarded(name, names), name)
        self.assertGreater(len(sensitive_prefs()), 5)
        self.assertGreater(len(watched_prefs()), 10)

    def test_every_option_control_is_marked_both_ways(self):
        declared = {o["id"]: o for o in options()}
        pages: dict[str, _Ids] = {}
        for option in declared.values():
            for location in option["ui"]:
                page, _, element = location.partition("#")
                parsed = pages.setdefault(page, page_ids(page))
                with self.subTest(location=location):
                    self.assertIn(element, parsed.by_id)
                    self.assertEqual(parsed.by_id[element], option["id"])
        for page in ("settings/settings.html", "newtab/newtab.html", "profiles/popup.html"):
            parsed = pages.setdefault(page, page_ids(page))
            for marked in parsed.marked:
                self.assertIn(marked, declared, f"{page}: data-option={marked} is not in options.json")


class AppearanceApiTest(unittest.TestCase):
    def test_the_appearance_writer_takes_its_pref_from_the_list(self):
        source = (SHELL / "modules" / "NulavioPersonalise.sys.mjs").read_text(encoding="utf-8")
        self.assertIn('"resource://builtin-addons/nulavio-shell/shared/options.json"', source)
        self.assertIn("const [pref] = entry.prefs;", source)
        self.assertIn('found.writer !== "NulavioPersonalise"', source)
        for forbidden in ("ui.useAccessibilityTheme", "ui.prefersReducedTransparency", "document_color_use"):
            self.assertNotIn(f'"{forbidden}"', source)

    def test_every_shell_page_paints_the_appearance_first(self):
        for page in sorted(SHELL.rglob("*.html")):
            if "dev" in page.relative_to(SHELL).parts:
                continue  # the component gallery shows the production CSS only
            scripts = re.findall(r'<script type="module" src="([^"]+)"', page.read_text(encoding="utf-8"))
            with self.subTest(page=str(page.relative_to(SHELL))):
                self.assertTrue(scripts and scripts[0].endswith("lib/appearance.js"), scripts)
        painter = (SHELL / "lib" / "appearance.js").read_text(encoding="utf-8")
        # Only looks: two attributes on <html>, nothing else on the page.
        self.assertEqual(set(re.findall(r"root\.dataset\.(\w+) =", painter)), {"accent", "contrast"})
        self.assertNotIn("innerHTML", painter)

    def test_the_api_takes_only_declared_values(self):
        schema = json.loads((SHELL / "experiments" / "personalise" / "schema.json").read_text(encoding="utf-8"))[0]
        declared = {o["id"]: o for o in options()}
        functions = {f["name"]: f for f in schema["functions"]}
        self.assertEqual(set(functions), {"state", "setDensity", "setAccent", "setMoreContrast"})
        self.assertEqual(functions["setDensity"]["parameters"][0]["enum"], declared["density"]["values"])
        self.assertEqual(functions["setAccent"]["parameters"][0]["enum"], declared["accent"]["values"])
        self.assertEqual(functions["setMoreContrast"]["parameters"][0]["type"], "boolean")
        self.assertEqual(declared["moreContrast"]["values"], [False, True])

    def test_the_options_match_the_token_variants(self):
        tokens = json.loads((ROOT / "docs" / "brand" / "tokens.json").read_text(encoding="utf-8"))
        variants = tokens["$extensions"]["nulavio.variants"]
        declared = {o["id"]: o for o in options()}
        accent = variants["accent"]
        self.assertEqual(declared["accent"]["prefs"], [accent["pref"]])
        self.assertEqual(declared["accent"]["values"], [accent["base"], *accent["values"]])
        self.assertEqual(declared["accent"]["prefValues"][1:], [v["prefValue"] for v in accent["values"].values()])
        contrast = variants["contrast"]
        self.assertEqual(declared["moreContrast"]["prefs"], [contrast["pref"]])
        self.assertEqual(declared["moreContrast"]["prefValues"], [None, contrast["values"]["more"]["prefValue"]])


class PrefWriterInventoryTest(unittest.TestCase):
    def test_every_privileged_pref_writer_is_pinned(self):
        found: dict[str, set[str]] = {}
        for place in PRIVILEGED_CODE:
            files = [place] if place.is_file() else sorted(p for p in place.rglob("*") if p.suffix in {".mjs", ".js"})
            for path in files:
                for argument in WRITER.findall(path.read_text(encoding="utf-8")):
                    found.setdefault(path.name, set()).add(argument.strip())
        self.assertEqual(found, PREF_WRITERS)


if __name__ == "__main__":
    unittest.main()
