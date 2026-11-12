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
from collections import Counter
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
ALLOWED_BY_KIND = {"routing": {"nulavio.routing.fallbackProfile", "nulavio.routing.fallbackPath"}}

# Every pref writer in the privileged code: each call (method and first argument) with how many times
# it appears. A new call anywhere, even one that reuses a pinned name, changes a count and fails here
# until it is reviewed: an option could otherwise reach a protection through another module.
PREF_WRITERS = {
    "NulavioConnect.sys.mjs": {"clearUserPref(PREF_PREVIOUS)": 1, "setStringPref(PREF_PREVIOUS)": 1},
    "NulavioGuard.sys.mjs": {"clearUserPref(name)": 1, "setBoolPref(name)": 1, "setIntPref(name)": 1, "setStringPref(name)": 1},
    "NulavioLayout.sys.mjs": {
        'setBoolPref("sidebar.verticalTabs")': 2,
        "setBoolPref(PREF_CHOICE_PENDING)": 4,
        "setBoolPref(PREF_SHELL_START)": 1,
        "setIntPref(PREF_ADOPTION_VERSION)": 1,
        'setStringPref("sidebar.visibility")': 2,
        "setStringPref(PREF_BEFORE_FOCUS)": 1,
    },
    "NulavioPasswords.sys.mjs": {"clearUserPref(PREF_DISMISSED)": 1, "setBoolPref(name)": 1, "setStringPref(PREF_DISMISSED)": 2},
    "NulavioPersonalise.sys.mjs": {
        "clearUserPref(pref)": 1,
        "setBoolPref(pref)": 1,
        "setIntPref(pref)": 1,
        "setStringPref(pref)": 1,
    },
    "NulavioPrivacy.sys.mjs": {
        "setBoolPref(PREF_DNS_CHOSEN)": 2,
        'setIntPref("network.trr.mode")': 1,
        "setIntPref(PREF_SEEDED)": 1,
        'setStringPref("browser.contentblocking.category")': 1,
        'setStringPref("network.trr.custom_uri")': 1,
        'setStringPref("network.trr.uri")': 1,
        "setStringPref(PREF_FIRSTRUN)": 1,
    },
    "NulavioProfiles.sys.mjs": {
        "setBoolPref(PREF_START_CHOOSER)": 1,
        "setIntPref(PREF_START_PROFILE)": 1,
        "setStringPref(PREF_COLORS)": 2,
        "setStringPref(PREF_COLOR_MIGRATION)": 3,
    },
    "NulavioRouting.sys.mjs": {
        "clearUserPref(FALLBACK_PATH_PREF)": 1,
        "clearUserPref(FALLBACK_PREF)": 1,
        "setBoolPref(ENABLED_PREF)": 1,
        "setBoolPref(IN_PAGE_PREF)": 1,
        "setIntPref(FALLBACK_PREF)": 1,
        "setStringPref(FALLBACK_PATH_PREF)": 1,
        "setStringPref(RULES_PREF)": 1,
    },
    "NulavioSearch.sys.mjs": {"setBoolPref(pref)": 1, "setIntPref(PREF_MIGRATION)": 1, "setStringPref(PREF_OPTIN)": 1},
}
# Every nsIPrefBranch mutator, and Preferences.sys.mjs.
WRITER = re.compile(
    r"(?:\.(set(?:Bool|Int|String|Char)Pref|setComplexValue|clearUserPref|lockPref|unlockPref|deleteBranch|resetBranch)"
    r"|\bPreferences\.(set|reset|lock|unlock))\(\s*([^,)]+)"
)
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
                if option["writer"] != "engine":  # keyboard commands: the engine's own extension shortcuts
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
        rules = json.loads((ROOT / "browser" / "config" / "guard-rules.json").read_text(encoding="utf-8"))["rules"]
        sources = {
            "watched": watched_prefs(),
            "forbidden": list(FORBIDDEN),
            "guard-rules": [r["pref"] for r in rules],
            "sensitive": sensitive_prefs(),
            "baseline": [p.name for p in profile.baseline_prefs() if p.category not in {"ui", "theme"}],
        }
        for source, members in sources.items():
            with self.subTest(source=source):
                self.assertGreater(len(members), 5, "a parser that returns nothing would hide a whole source")
                for name in members:
                    self.assertTrue(is_guarded(name, names), name)
        # Names only a source covers (no prefix does): if that source stopped being read, they would pass.
        for name in (
            "browser.formfill.enable",
            "app.normandy.enabled",
            "app.shield.optoutstudies.enabled",
            "nimbus.rollouts.enabled",
        ):
            with self.subTest(name=name):
                self.assertFalse(is_guarded(name, set()), "covered by a prefix: not a probe of its source")
                self.assertTrue(is_guarded(name, names))
                self.assertEqual(violations([{"id": "x", "kind": "cosmetic", "prefs": [name]}], names), [f"x: {name}"])

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
        self.assertEqual(set(re.findall(r"root\.dataset\.(\w+) =", painter)), {"accent", "contrast", "ambience", "transparency"})
        self.assertNotIn("innerHTML", painter)

    def test_the_api_takes_only_declared_values(self):
        schema = json.loads((SHELL / "experiments" / "personalise" / "schema.json").read_text(encoding="utf-8"))[0]
        declared = {o["id"]: o for o in options()}
        functions = {f["name"]: f for f in schema["functions"]}
        self.assertEqual(
            set(functions),
            {
                "state",
                "setDensity",
                "setAccent",
                "setMoreContrast",
                "setNewtabAmbience",
                "setReduceTransparency",
                "openKeyboardShortcuts",
            },
        )
        self.assertEqual(functions["openKeyboardShortcuts"]["parameters"], [])
        for name in ("setNewtabAmbience", "setReduceTransparency"):
            self.assertEqual(functions[name]["parameters"][0]["type"], "boolean")
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


class CommandsTest(unittest.TestCase):
    """D-UX23: Nulavio's keys are pinned, and none of them unlocks, resumes, grants or turns anything off."""

    def test_the_commands_are_the_declared_ones_with_their_keys(self):
        manifest = json.loads((SHELL / "manifest.json").read_text(encoding="utf-8"))
        declared = next(o for o in options() if o["id"] == "shortcuts")
        self.assertEqual(sorted(manifest["commands"]), sorted(declared["values"]))
        keys = {name: c["suggested_key"]["default"] for name, c in manifest["commands"].items()}
        self.assertEqual(
            keys,
            {
                "_execute_action": "Alt+Shift+P",
                "open-assistant": "Alt+Shift+A",
                "toggle-focus": "Ctrl+Alt+F",
                "lock-profile": "Ctrl+Alt+B",
            },
        )
        self.assertEqual(len(set(keys.values())), len(keys))

    def test_no_key_lowers_a_protection(self):
        source = (SHELL / "background.js").read_text(encoding="utf-8")
        block = source[source.index("// -- Nulavio keys (UX6, D-UX23)") : source.index('// -- "@ia" in the address bar')]
        for forbidden in ("nulavioVault", "unlock", "setStopped(false)", "grant", "autonomy", "nulavioGuard", "Services."):
            self.assertNotIn(forbidden, block)
        # The lock key only opens the menu; the menu runs the same confirmation as its button.
        self.assertIn("browser.action.openPopup(", block)
        popup = (SHELL / "profiles" / "popup.js").read_text(encoding="utf-8")
        take = popup[popup.index("async function takeLockRequest") : popup.index("localize();")]
        self.assertIn("lock.click()", take)
        self.assertNotIn("nulavioVault", take)


class QuickActionsTest(unittest.TestCase):
    def test_quick_actions_are_pinned_and_none_lowers_a_protection(self):
        source = (SHELL / "modules" / "NulavioWindow.sys.mjs").read_text(encoding="utf-8")
        added = re.findall(r'addAction\(\s*("[^"]+"|QUICK_ACTION)', source)
        names = [json.loads(a) if a.startswith('"') else "nulavio-assistant" for a in added]
        declared = next(o for o in options() if o["id"] == "quickActions")
        self.assertEqual(sorted(names), sorted(declared["values"]))
        block = source[source.index('addAction("nulavio-settings"') : source.index("  stop() {")]
        for forbidden in ("NulavioVault", "unlock", "setStopped", "grant", "autonomy", "NulavioGuard", "Services.prefs.set"):
            self.assertNotIn(forbidden, block)
        for name in ("nulavio-quickaction-settings", "nulavio-quickaction-focus"):
            for ftl in (
                ROOT / "browser" / "branding" / "nulavio" / "locales" / "en-US" / "brand.ftl",
                ROOT / "browser" / "l10n" / "pt-BR" / "browser" / "branding" / "nulavio" / "brand.ftl",
            ):
                self.assertRegex(ftl.read_text(encoding="utf-8"), rf"(?m)^{name} = \S")


class RoutingFallbackTest(unittest.TestCase):
    def test_only_links_from_other_apps_use_the_default_destination(self):
        """M5 review: typed addresses (M4b) and links in pages (M5) never move by a default."""
        source = (SHELL / "modules" / "NulavioRouting.sys.mjs").read_text(encoding="utf-8")
        calls = re.findall(r"decide\(\{[^}]*\}\)", source)
        with_fallback = [c for c in calls if "fallbackProfileId" in c]
        self.assertEqual(len(with_fallback), 2, calls)  # handleCommandLine and #dispatchOne (M4a)
        for name in ("routeNavigation(", "#onOpeningRequest(subject) {"):
            body = source[source.index(name) : source.index("\n  }\n", source.index(name))]
            self.assertNotIn("fallbackProfileId", body, name)
        # It applies only in the instance that receives links from other apps (the group's default).
        # Decided from profiles.ini when the command line arrives (the engine's in-memory default is not used).
        self.assertIn('Services.dirsvc.get("UAppData", Ci.nsIFile)', source)
        self.assertNotIn("groupToolkitProfile", source)


class PrefWriterInventoryTest(unittest.TestCase):
    def test_every_privileged_pref_writer_is_pinned(self):
        found: dict[str, dict[str, int]] = {}
        for place in PRIVILEGED_CODE:
            files = [place] if place.is_file() else sorted(p for p in place.rglob("*") if p.suffix in {".mjs", ".js"})
            for path in files:
                calls = Counter(
                    f"{m.group(1) or 'Preferences.' + m.group(2)}({m.group(3).strip()})"
                    for m in WRITER.finditer(path.read_text(encoding="utf-8"))
                )
                if calls:
                    found[path.name] = dict(calls)
        self.assertEqual(found, PREF_WRITERS)

    def test_the_appearance_module_writes_only_inside_set(self):
        source = (SHELL / "modules" / "NulavioPersonalise.sys.mjs").read_text(encoding="utf-8")
        body = source[source.index("  async set(id, value) {") : source.index("  /** Settings > Atalhos")]
        self.assertEqual(len(WRITER.findall(body)), 4)
        self.assertEqual(len(WRITER.findall(source)), 4)
        self.assertEqual(re.findall(r"\bconst \[?pref\]? =", source), ["const [pref] =", "const [pref] ="])


if __name__ == "__main__":
    unittest.main()
