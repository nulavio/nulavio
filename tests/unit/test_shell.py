"""Nulavio Shell built-in add-on: manifest, privacy, i18n and packaging."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import make_shell  # noqa: E402
from node_tool import requires_node  # noqa: E402

SHELL = ROOT / "browser" / "shell"
ALLOWED_PERMISSIONS = {"activeTab", "downloads", "management", "menus", "privacy", "search"}
FLOW_E_TYPES = {".appimage", ".sh", ".run", ".desktop", ".deb", ".rpm", ".flatpakref"}  # docs/brand/ux-flows.md


def locale(name: str) -> dict:
    return json.loads((SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8"))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = make_shell.manifest()

    def test_identity(self):
        self.assertEqual(self.manifest["manifest_version"], 3)
        self.assertEqual(self.manifest["browser_specific_settings"]["gecko"]["id"], "shell@nulavio.net")
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_least_privilege(self):
        self.assertEqual(set(self.manifest["permissions"]), ALLOWED_PERMISSIONS)
        for key in (
            "host_permissions",
            "optional_permissions",
            "optional_host_permissions",
            "content_scripts",
            "web_accessible_resources",
            "externally_connectable",
            "content_security_policy",
        ):
            self.assertNotIn(key, self.manifest, f"{key} widens the Shell's reach or relaxes its CSP")

    def test_no_remote_resources_or_inline_code(self):
        for page in SHELL.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertNotRegex(text, r"""(src|href)=["']https?:""", "remote resource")
                self.assertNotRegex(text, r"<script(?![^>]*\bsrc=)", "inline script")
                self.assertNotIn("style=", text, "inline style")
        for script in [*SHELL.rglob("*.js"), *SHELL.rglob("*.mjs")]:
            text = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertNotRegex(
                    text, r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", "HTML injection sink"
                )
                self.assertNotRegex(
                    text,
                    r"\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon|newChannel|loadSubScript",
                    "the Shell makes no network requests",
                )
                self.assertNotRegex(text, r"\beval\(|new Function\(")
                # The only resource a privileged module reads itself: the engine's own profile icons.
                for match in __import__("re").finditer(r"asyncFetch\(\s*\{\s*uri:\s*`([^`]+)`", text):
                    self.assertTrue(match.group(1).startswith("chrome://browser/content/profiles/assets/"), match.group(1))

    def test_flow_e_has_no_open_action(self):
        warning = (SHELL / "warning" / "warning.js").read_text(encoding="utf-8")
        self.assertNotIn("downloads.open", warning)
        self.assertNotIn("downloads.open", json.dumps(self.manifest))

    def test_risky_types_cover_flow_e(self):
        source = (SHELL / "lib" / "risky.js").read_text(encoding="utf-8")
        listed = set(re.findall(r'"(\.[a-z0-9]+)"', source))
        self.assertTrue(listed >= FLOW_E_TYPES, FLOW_E_TYPES - listed)


class LocaleTest(unittest.TestCase):
    def test_same_keys_and_placeholders(self):
        en, pt = locale("en"), locale("pt_BR")
        self.assertEqual(set(en), set(pt))
        for key in en:
            with self.subTest(key=key):
                self.assertEqual(set(en[key].get("placeholders", {})), set(pt[key].get("placeholders", {})))
                self.assertTrue(pt[key]["message"].strip())

    def test_every_referenced_key_exists(self):
        keys = set(locale("en"))
        referenced = set()
        for page in SHELL.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            referenced |= set(re.findall(r'data-i18n="([A-Za-z0-9_]+)"', text))
            referenced |= {pair.split(":")[1] for pair in re.findall(r'data-i18n-attr="([^"]+)"', text)}
        for script in SHELL.rglob("*.js"):
            referenced |= set(re.findall(r'\bt\("([A-Za-z0-9_]+)"', script.read_text(encoding="utf-8")))
        referenced |= {m[6:-2] for m in re.findall(r"__MSG_[A-Za-z0-9]+__", json.dumps(make_shell.manifest()))}
        self.assertEqual(referenced - keys, set())

    def test_the_phone_page_names_no_place_the_companion_is_not(self):
        # ADR 0005's release order: the page never sends people to an app they cannot get. F-Droid
        # closed the inclusion request on 2026-11-11 (#207); the signed APK comes with every release
        # that offers pairing (ADR 0014, publish_release.sh refuses one without it) and the download
        # page offers it.
        for name in ("en", "pt_BR"):
            with self.subTest(locale=name):
                hint = locale(name)["phoneScanHint"]["message"]
                self.assertNotIn("F-Droid", hint)
                self.assertNotIn("Play", hint)
                self.assertIn("nulavio.net", hint)

    # design-system.md, Calmaria: no Unicode pseudo-icons in messages or in what the pages draw. They
    # changed with the desktop font and were read aloud; states use SVG icons and words.
    PSEUDO_ICONS = "◇⌑◷◈▤⯃⚠■Ⅱ✓●▸"

    def test_no_unicode_pseudo_icons(self):
        found = []
        for name in ("en", "pt_BR"):
            for key, entry in locale(name).items():
                found += [f"{name}:{key}" for ch in self.PSEUDO_ICONS if ch in entry["message"]]
        for path in [*SHELL.rglob("*.js"), *SHELL.rglob("*.mjs"), *SHELL.rglob("*.html"), *SHELL.rglob("*.css")]:
            code = re.sub(r"/\*.*?\*/|<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)
            code = re.sub(r"(^|\s)//.*", "", code)  # line comments (not "https://")
            found += [f"{path.relative_to(SHELL)}:{ch}" for ch in self.PSEUDO_ICONS if ch in code]
        self.assertEqual(found, [])


MODULES = SHELL / "modules"


def module_text(name: str) -> str:
    return (MODULES / name).read_text(encoding="utf-8")


API_NAMES = ("nulavioSearch", "nulavioProfiles", "nulavioRouting", "nulavioConnect", "nulavioVault", "nulavioAI")
API_NAMES += ("nulavioGuard", "nulavioPrivacy", "nulavioPasswords")
API_NAMES += ("nulavioLayout", "nulavioPersonalise", "nulavioWhatsNew")
API_NAMES += ("nulavioServices",)  # web services on a click, for translation (#156)


class PrivilegedApiTest(unittest.TestCase):
    """The Shell's experiment APIs: what they reach, and nothing more."""

    def setUp(self):
        self.manifest = make_shell.manifest()

    def test_parent_scripts_declare_nothing_at_top_level(self):
        # The engine loads every experiment's parent script into one shared scope: a top-level
        # const/let/class/function in two of them stops the second API from loading.
        for name, api in self.manifest["experiment_apis"].items():
            with self.subTest(api=name):
                source = (SHELL / api["parent"]["script"]).read_text(encoding="utf-8")
                top = re.findall(r"^(?:const|let|var|class|function|async function)\s+(\w+)", source, re.M)
                self.assertEqual(top, [], f"{api['parent']['script']} declares {top} at top level")

    def test_only_the_documented_apis(self):
        apis = self.manifest["experiment_apis"]
        self.assertEqual(set(apis), set(API_NAMES))
        for name, api in apis.items():
            with self.subTest(api=name):
                self.assertEqual(api["parent"]["scopes"], ["addon_parent"], "no API code runs in content processes")
                self.assertEqual(api["parent"]["paths"], [[name]])
                self.assertNotIn("child", api)
                self.assertTrue((SHELL / api["parent"]["script"]).is_file())
                schema = json.loads((SHELL / api["schema"]).read_text(encoding="utf-8"))
                self.assertEqual([ns["namespace"] for ns in schema], [name])
        self.assertEqual(apis["nulavioSearch"]["parent"]["events"], ["startup"])
        self.assertEqual(apis["nulavioGuard"]["parent"]["events"], ["startup"])  # independent of the event page
        self.assertEqual(apis["nulavioPrivacy"]["parent"]["events"], ["startup"])  # defaults before the first page
        self.assertEqual(apis["nulavioProfiles"]["parent"]["events"], ["startup"])  # the engine's profile menus (U-T23)
        self.assertEqual(apis["nulavioRouting"]["parent"]["events"], ["startup"])  # links clicked in pages (M5)
        self.assertNotIn("events", apis["nulavioConnect"]["parent"])
        self.assertNotIn("events", apis["nulavioPersonalise"]["parent"])  # lazy: nothing to do at startup
        self.assertEqual(apis["nulavioWhatsNew"]["parent"]["events"], ["startup"])  # the Help entry and the bar (#198)
        self.assertNotIn("events", apis["nulavioServices"]["parent"])  # only the menus' calls

    def test_an_engine_module_is_imported_from_one_address(self):
        # 160.0-0.5 shipped NulavioWhatsNew importing SessionStore from an address the engine no longer has
        # (resource:///modules/sessionstore/): its start-up failed quietly, so neither the Help menu entry
        # nor the bar after an update appeared (#198). Every module that imports the same engine module
        # must use the same address, the one the others are known to load.
        addresses: dict[str, set[str]] = {}
        for module in (SHELL / "modules").glob("*.mjs"):
            for name, address in re.findall(
                r'^\s+(\w+): "((?:resource|moz-src|chrome)://[^"]+)"', module.read_text(encoding="utf-8"), re.M
            ):
                addresses.setdefault(name, set()).add(address)
        mixed = {name: sorted(found) for name, found in addresses.items() if len(found) > 1}
        self.assertEqual(mixed, {})
        self.assertEqual(addresses["SessionStore"], {"moz-src:///browser/components/sessionstore/SessionStore.sys.mjs"})

    def test_parent_scripts_only_bridge_to_the_modules(self):
        for script in (SHELL / "experiments").rglob("parent.js"):
            text = script.read_text(encoding="utf-8")
            with self.subTest(script=str(script.relative_to(SHELL))):
                imports = re.findall(r'importESModule\("([^"]+)"\)', text)
                for url in imports:
                    self.assertTrue(
                        url.startswith("resource://builtin-addons/nulavio-shell/modules/")
                        or url == "resource://gre/modules/ExtensionParent.sys.mjs",
                        url,
                    )
                self.assertNotIn("Services.prefs.set", text)

    def test_layout_exposes_only_fixed_presets_and_first_run_dismissal(self):
        apis = list(self.manifest["experiment_apis"])
        self.assertLess(apis.index("nulavioLayout"), apis.index("nulavioPrivacy"))
        api = self.manifest["experiment_apis"]["nulavioLayout"]
        self.assertEqual(api["parent"]["events"], ["startup"])
        schema = json.loads((SHELL / api["schema"]).read_text())[0]
        names = {f["name"] for f in schema["functions"]}
        self.assertEqual(
            names,
            {
                "state",
                "apply",
                "dismissChoice",
                "toggleFocus",
                "setImmersive",
                "copyLinkToHighlight",
                "openActions",  # #321: one tab's window, the address bar in its actions mode; nothing runs
            },
        )
        # #459: editing the page's text left the browser for an extension the documentation names.
        self.assertNotIn("toggle-page-editing", self.manifest["commands"])
        self.assertFalse((ROOT / "browser" / "shell" / "modules" / "NulavioPageEdit.sys.mjs").exists())
        self.assertNotIn("toggle-keep-above", self.manifest["commands"])  # #460: left to KWin's own window menu
        actions = next(f for f in schema["functions"] if f["name"] == "openActions")
        self.assertEqual([(a["name"], a["type"]) for a in actions["parameters"]], [("tabId", "integer")])
        # ADR 0009: Immersive is one boolean; the tab only says in which window the outcome is announced.
        switch = next(f for f in schema["functions"] if f["name"] == "setImmersive")
        self.assertEqual([(a["name"], a["type"]) for a in switch["parameters"]], [("on", "boolean"), ("tabId", "integer")])
        for name in ("toggleFocus", "copyLinkToHighlight"):  # the tab the key was pressed in, nothing else (#157)
            fn = next(f for f in schema["functions"] if f["name"] == name)
            self.assertEqual(fn["parameters"], [{"name": "tabId", "type": "integer", "minimum": 0}])
        self.assertEqual(self.manifest["commands"]["copy-link-to-highlight"]["suggested_key"]["default"], "Ctrl+Alt+C")
        for name in ("state", "dismissChoice"):
            fn = next(f for f in schema["functions"] if f["name"] == name)
            self.assertEqual(fn["parameters"], [])
        apply = next(f for f in schema["functions"] if f["name"] == "apply")
        self.assertEqual(apply["parameters"], [{"name": "preset", "type": "string", "enum": ["lateral", "top", "focus"]}])

    def test_the_api_offers_pages_nothing_they_do_not_call(self):
        # Least privilege (ADR 0011): the settings live in the browser's own page, which calls the modules
        # directly. What a Shell page can ask of privileged code is only what some Shell page asks: a function
        # stays in a schema while a page that uses its namespace names it.
        pages = [
            p.read_text(encoding="utf-8")
            for p in SHELL.rglob("*.js")
            if not {"experiments", "modules"} & set(p.relative_to(SHELL).parts)
        ]
        for name, api in self.manifest["experiment_apis"].items():
            schema = json.loads((SHELL / api["schema"]).read_text())[0]
            users = [text for text in pages if re.search(rf"\b{name}\b", text)]
            self.assertTrue(users, f"{name}: no Shell page uses it")
            for fn in schema.get("functions", []):
                with self.subTest(api=name, function=fn["name"]):
                    self.assertTrue(
                        any(re.search(rf"\.{fn['name']}\b", text) for text in users),
                        "no Shell page calls it: remove it from the schema and the parent script",
                    )

    def test_profile_selector_is_on_the_toolbar_with_a_shortcut(self):
        self.assertEqual(self.manifest["action"]["default_area"], "navbar")
        self.assertEqual(self.manifest["action"]["default_popup"], "profiles/popup.html")
        self.assertEqual(self.manifest["commands"]["_execute_action"]["suggested_key"]["default"], "Alt+Shift+P")

    def test_the_first_run_steps_are_the_same_in_the_api_and_the_module(self):
        """ "Usar os padrões" sends every step at once: a schema that allows fewer than there are refuses it, and the
        first run never ends (#241 added "updates", and maxItems had stayed at 7)."""
        steps = json.loads(
            re.search(r"FIRSTRUN_STEPS = Object\.freeze\((\[.*?\])\)", module_text("NulavioPrivacy.sys.mjs")).group(1)
        )
        schema = json.loads((SHELL / "experiments" / "privacy" / "schema.json").read_text(encoding="utf-8"))[0]
        param = next(f for f in schema["functions"] if f["name"] == "firstRunDone")["parameters"][0]
        self.assertEqual(param["items"]["enum"], steps)
        self.assertEqual(param["maxItems"], len(steps))

    def test_every_module_error_has_a_message(self):
        en = locale("en")
        text = "".join(module_text(n.name) for n in MODULES.glob("*.sys.mjs"))
        codes = set(re.findall(r'fail\("([a-z-]+)"', text)) | {"disabled", "unregistered", "unexpected"}
        for code in codes:
            self.assertIn(f"err_{code.replace('-', '_')}", en, code)

    # Codes whose one message reads right for every module that throws them. Add one here only when its message
    # does; otherwise give the module a code of its own.
    SHARED_ERROR_CODES = frozenset(
        {
            "bad-request",
            "credentials-in-url",
            "invalid-name",
            "invalid-profile",
            "invalid-url",
            "locked",
            "name-taken",
            "no-window",
            "not-found",
            "unknown-provider",
        }
    )

    def test_no_module_throws_another_modules_error_code(self):
        """One code is one message: a code two modules throw shows one module's words for the other's error (#486;
        #495 found the delete page's words for locking the profile in use). It only sees `fail("code")`: a code a
        module passes through from another, as NulavioProfiles did with NulavioSearch's (#495), is not seen."""
        modules: dict[str, set[str]] = {}
        for path in MODULES.glob("*.sys.mjs"):
            for code in re.findall(r'fail\("([a-z-]+)"', path.read_text(encoding="utf-8")):
                modules.setdefault(code, set()).add(path.name)
        shared = {code: sorted(names) for code, names in modules.items() if len(names) > 1}
        self.assertEqual({code: names for code, names in shared.items() if code not in self.SHARED_ERROR_CODES}, {})
        self.assertEqual(self.SHARED_ERROR_CODES - set(shared), set(), "an allowed code is no longer shared")


class VaultMethodsPageErrorsTest(unittest.TestCase):
    """#519: `not-found` is the Vault's code for a profile that is gone and for a method that is gone, and the shared
    message ("the list was refreshed") is true of neither on the methods page, which refreshes nothing."""

    def test_the_methods_page_never_shows_the_shared_words_for_a_change_that_failed(self):
        text = (SHELL / "vault" / "methods.js").read_text(encoding="utf-8")
        uses = [m.start() for m in re.finditer(r"errorText\(", text)]
        helpers = [text.index(f"function {name}(") for name in ("readText", "failureText")]
        helpers = [(start, text.index("\n}\n", start)) for start in helpers]
        outside = [i for i in uses if not any(start < i < end for start, end in helpers)]
        self.assertEqual(outside, [], "errorText is called through readText (a read) or failureText (a change)")
        self.assertIn('isGone(e) ? t("vaultGone") : errorText(e)', text)
        self.assertIn('t("methodsMethodGone")', text)

    def test_the_words_exist_in_both_languages_and_say_nothing_about_a_refreshed_list(self):
        for name in ("en", "pt_BR"):
            with self.subTest(locale=name):
                messages = locale(name)
                self.assertIn("methodsMethodGone", messages)
                self.assertIn("vaultGone", messages)
        self.assertNotIn("refresh", locale("en")["methodsMethodGone"]["message"].lower())


class FailureAnnouncementsTest(unittest.TestCase):
    """#546: a temporary window that cannot be launched after its profile was made, and a link that cannot be written to
    the clipboard, are announced as what they are, by the module itself so every entry point says the same."""

    def test_a_launch_that_fails_after_the_profile_was_made_says_so_without_nothing_was_changed(self):
        body = module_text("NulavioProfiles.sys.mjs")
        body = body[body.index("async openTemporary()") :]
        body = body[: body.index("\n  }\n")]
        self.assertLess(body.index('{ op: "create" }'), body.index("runw("))
        launch = body[body.index("try {") : body.index("return {")]
        self.assertIn("runw(", launch)
        self.assertIn('fail("temporary-not-opened")', launch.split("catch", 1)[1])
        for name in ("en", "pt_BR"):
            self.assertIn("err_temporary_not_opened", locale(name))
        self.assertNotIn("nothing was changed", locale("en")["err_temporary_not_opened"]["message"].lower())
        self.assertNotIn("nada foi alterado", locale("pt_BR")["err_temporary_not_opened"]["message"].lower())

    def test_a_link_that_cannot_be_copied_is_announced_by_the_function_every_caller_uses(self):
        body = module_text("NulavioLayout.sys.mjs")
        body = body[body.index("async copyLinkToHighlight(") :]
        body = body[: body.index("\n  },\n")]
        copy = body[body.index("try {\n      lazy.ClipboardHelper.copyString") :]
        self.assertLess(copy.index('announce("linkHighlightNotCopied")'), copy.index('announce("linkHighlightCopied")'))
        self.assertIn("return false;", copy.split("catch", 1)[1].split('announce("linkHighlightCopied")')[0])
        for name in ("en", "pt_BR"):
            self.assertIn("linkHighlightNotCopied", locale(name))
        self.assertEqual(locale("pt_BR")["linkHighlightNotCopied"]["message"], "O link não pôde ser copiado.")


class VaultOtherPagesErrorsTest(unittest.TestCase):
    """#547: the same as #519 for the phone, unlock and create pages. `not-found` is a profile that is gone or one of
    its ways to unlock that is gone, and "the list was refreshed" is true of neither on a page that lists nothing."""

    def helpers_of(self, text, names):
        spans = []
        for name in names:
            start = re.search(rf"(?:async )?function {name}\(", text).start()
            spans.append((start, text.index("\n}\n", start)))
        return spans

    def assert_errortext_only_in(self, page, names):
        text = (SHELL / "vault" / page).read_text(encoding="utf-8")
        spans = self.helpers_of(text, names)
        outside = [m.start() for m in re.finditer(r"errorText\(", text) if not any(a < m.start() < b for a, b in spans)]
        self.assertEqual(outside, [], f"{page}: errorText is reached only through {names}")
        return text

    def test_no_page_shows_the_shared_words_for_a_failure_after_it_loaded(self):
        phone = self.assert_errortext_only_in("phone.js", ["readText", "failure"])
        self.assertIn('t("phoneMethodGone")', phone)
        self.assertIn('t("vaultGone")', phone)
        unlock = self.assert_errortext_only_in("unlock.js", ["failureText", "unreadable"])
        self.assertIn('t("vaultMethodGone")', unlock)
        create = self.assert_errortext_only_in("create.js", ["failureText"])
        self.assertIn('t("vaultCreateGone")', create)

    def test_the_words_exist_in_both_languages_and_say_nothing_about_a_refreshed_list(self):
        for name in ("en", "pt_BR"):
            with self.subTest(locale=name):
                messages = locale(name)
                for key in ("phoneMethodGone", "vaultMethodGone", "vaultCreateGone", "vaultGone"):
                    self.assertIn(key, messages)
        for key in ("phoneMethodGone", "vaultMethodGone", "vaultCreateGone"):
            self.assertNotIn("refresh", locale("en")[key]["message"].lower())
            self.assertNotIn("atualizada", locale("pt_BR")[key]["message"].lower())


class SearchProvidersTest(unittest.TestCase):
    """docs/adr/0002-nulavio-search.md: who search goes to, and when."""

    def setUp(self):
        self.text = module_text("NulavioSearch.sys.mjs")
        block = self.text[self.text.index("export const PROVIDERS") : self.text.index("export const ACCOUNTS")]
        self.providers = {
            key: dict(re.findall(r'(\w+): ("[^"]*"|null|true|false)', body))
            for key, body in re.findall(r"(\w+): Object\.freeze\(\{(.*?)\}\)", block, re.S)
        }

    def test_curated_providers(self):
        # The first-run three, then the ones offered on request (#151 added Ecosia, Qwant and Startpage, checked
        # 2026-11-16 in docs/research/search-providers.md).
        self.assertEqual(set(self.providers), {"duckduckgo", "brave", "mojeek", "kagi", "ecosia", "qwant", "startpage"})
        self.assertEqual({key for key, p in self.providers.items() if p["firstRun"] == "true"}, {"duckduckgo", "brave", "mojeek"})
        for key, p in self.providers.items():
            with self.subTest(provider=key):
                self.assertRegex(p["search"], r'^"https://[a-z0-9.-]+/[^"]*\{searchTerms\}')
                if p["suggest"] != "null":
                    self.assertRegex(p["suggest"], r'^"https://[a-z0-9.-]+/[^"]*\{searchTerms\}')
                self.assertRegex(p["alias"], r'^"@[a-z]+"$')

    def test_paid_service_and_searxng_are_never_added_by_themselves(self):
        self.assertEqual(self.providers["kagi"]["firstRun"], "false")
        self.assertNotIn("searxng", self.providers)
        # example.org/example.com are reserved names (RFC 2606), used in comments only.
        instance = re.search(r"https://(?![a-z0-9.-]*example\.)[a-z0-9.-]*searx[a-z0-9.-]*\.[a-z]+/", self.text)
        self.assertIsNone(instance, "a SearXNG instance is hard-coded")

    def test_no_nulavio_endpoint(self):
        self.assertIsNone(re.search(r"nulavio\.net|nulavio\.(com|org|io)", self.text), "a Nulavio endpoint")

    def test_a_new_profiles_search_choice_is_applied_at_its_first_start_only(self):
        """#151 (and #453's decision): the choice file is read only at a profile's first start; later it is removed
        unread, so a file left in a profile that has run cannot change its search."""
        start = self.text[self.text.index("  startup() {") : self.text.index("  /** A choice file in a profile")]
        self.assertIn("const firstStart = Services.prefs.getIntPref(PREF_MIGRATION, 0) < MIGRATION_VERSION;", start)
        self.assertLess(start.index("const firstStart"), start.index("await this.migrate()"), "read before the migration")
        self.assertRegex(
            start, r"if \(firstStart\) \{\s*await this\.applyPending\(\);\s*\} else \{\s*await this\.#dropPending\(\);"
        )
        for name in ("carryable", "carrySearch", "nulavio-search-carry"):
            self.assertNotIn(name, self.text, "taking a search to other profiles was left out (#453)")

    def test_a_sign_in_is_read_from_a_cookies_name_never_its_value(self):
        """#151: providers with accounts name their session cookie; the module reads only whether it is there."""
        block = self.text[self.text.index("export const ACCOUNTS") : self.text.index("export class SearchSettingsError")]
        accounts = dict(re.findall(r"(\w+): Object\.freeze\(\{(.*?)\}\)", block, re.S))
        self.assertEqual(set(accounts), {"kagi"})
        self.assertIn('cookie: "kagi_session"', accounts["kagi"])
        self.assertIn('signIn: "https://kagi.com/signin"', accounts["kagi"])
        body = self.text[self.text.index("  accounts() {") : self.text.index("  async choose(")]
        self.assertIn("cookie.name === account.cookie", body)
        self.assertNotIn(".value", body, "a cookie's value is read")

    def test_baseline_turns_remote_suggestions_and_trending_off(self):
        baseline = (ROOT / "browser" / "config" / "prefs" / "baseline.js").read_text(encoding="utf-8")
        for pref, value in (
            ("browser.search.suggest.enabled", "false"),
            ("browser.urlbar.suggest.trending", "false"),
            ("browser.search.separatePrivateDefault.featureGate", "true"),
            ("browser.search.separatePrivateDefault.enabled", "true"),
        ):
            self.assertIn(f'user_pref("{pref}", {value});', baseline)

    def test_consent_pref_is_the_one_the_patch_reads(self):
        patch = (ROOT / "browser" / "patches" / "0004-search-require-per-engine-consent-for-suggestions.patch").read_text()
        pref = re.search(r'PREF_OPTIN = "([^"]+)"', self.text).group(1)
        self.assertIn(f'pref: "{pref}"', patch)
        self.assertIn('default: "",', patch, "no engine may have consent by default")
        removed = [line for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(
            [line.strip() for line in removed],
            ["-      SearchSuggestionController.engineOffersSuggestions(engine, fetchTrending)"],
            "the patch may only add a condition, never drop an upstream one",
        )


class DownloadsPanelTest(unittest.TestCase):
    """Flow E in the engine's downloads panel (patch 0007) uses the Shell's list of program file types."""

    def test_the_branding_module_and_the_shell_list_the_same_types(self):
        def listed(path: Path) -> list[str]:
            block = re.search(r"RISKY_EXTENSIONS = Object\.freeze\(\[(.*?)\]\)", path.read_text(encoding="utf-8"), re.S).group(1)
            return re.findall(r'"(\.[a-z]+)"', block)

        shell = listed(SHELL / "lib" / "risky.js")
        branding = listed(ROOT / "browser" / "branding" / "nulavio" / "NulavioDownloads.sys.mjs")
        self.assertEqual(shell, branding)
        self.assertIn(".appimage", shell)

    def test_the_patch_only_closes_open_for_programs(self):
        name = "0007-downloads-never-open-a-program-from-the-downloads-ui.patch"
        patch = (ROOT / "browser" / "patches" / name).read_text(encoding="utf-8")
        added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        self.assertTrue(any("NulavioDownloads.isProgram" in line for line in added))
        self.assertFalse(any("deleteFile" in line for line in added))  # "Show in folder" and "Delete" stay
        self.assertIn(name, (ROOT / "browser" / "patches" / "series").read_text(encoding="utf-8"))


class ProfileTemplatesTest(unittest.TestCase):
    def setUp(self):
        self.text = module_text("NulavioProfiles.sys.mjs")

    def listed(self, name: str) -> list[str]:
        block = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", self.text, re.S).group(1)
        return re.findall(r'"([a-z-]+)"', block)

    def test_templates_use_offered_icons_and_colours(self):
        avatars, colors = set(self.listed("AVATARS")), set(self.listed("COLORS"))
        templates = re.findall(r'id: "(\w+)", avatar: "([a-z-]+)", color: "(\w+)"', self.text)
        self.assertEqual([t[0] for t in templates], ["personal", "work", "banking", "research", "sensitive"])
        for template_id, avatar, color in templates:
            with self.subTest(template=template_id):
                self.assertIn(avatar, avatars)
                self.assertIn(color, colors)
        names = (SHELL / "lib" / "names.js").read_text(encoding="utf-8")
        for template_id, *_ in templates:
            key = re.search(rf'{template_id}: "(\w+)"', names).group(1)
            self.assertIn(key, locale("en"))

    def test_sensitive_template_only_sets_engine_prefs_that_clear_and_block_installs(self):
        block = re.search(r"export const SENSITIVE_PREFS = Object\.freeze\(\{(.*?)\}\);", self.text, re.S).group(1)
        prefs = dict(re.findall(r'"([\w.]+)": (true|false|"\w+")', block))
        self.assertEqual(prefs["privacy.sanitize.sanitizeOnShutdown"], "true")
        self.assertEqual(prefs["privacy.clearOnShutdown_v2.cookiesAndStorage"], "true")
        self.assertEqual(prefs["xpinstall.enabled"], "false")
        # Nothing that weakens a protection (sandbox, TLS, Safe Browsing, updates, signatures).
        for name in prefs:
            self.assertFalse(re.match(r"(security|browser\.safebrowsing|app\.update|extensions\.update|network)\.", name), name)

    def test_no_temporary_profile_until_it_exists(self):
        self.assertNotIn("temporary", [t for t in self.listed("TEMPLATES")])
        self.assertNotRegex(self.text, r'id: "temporary"')

    def test_colours_are_design_tokens(self):
        tokens = json.loads((ROOT / "docs" / "brand" / "tokens.json").read_text(encoding="utf-8"))
        for theme in ("light", "dark"):
            self.assertEqual(
                set(self.listed("COLORS")) | {"on"},
                set(tokens["color"][theme]["identity"]) - {"$description", "edge", "ring"},
            )
        for color in self.listed("COLORS"):
            self.assertIn(f"color_{color}", locale("en"))
        for avatar in self.listed("AVATARS"):
            self.assertIn(f"avatar_{avatar.replace('-', '_')}", locale("en"))


class RoutingTest(unittest.TestCase):
    """Smart Profile Routing wiring (ADR 0003). Decisions are tested on the engine (test_routing.py)."""

    BRANDING = ROOT / "browser" / "branding" / "nulavio"

    def test_handler_runs_before_the_browser_opens_links(self):
        conf = (self.BRANDING / "components.conf").read_text(encoding="utf-8")
        entry = re.search(r'"command-line-handler": "([^"]+)"', conf).group(1)
        # Handlers run in alphabetical order; the browser opens URLs in "m-browser" and "x-default".
        self.assertLess(entry, "m-browser")
        module = re.search(r'"esModule": "resource:///modules/nulavio/([^"]+)"', conf).group(1)
        self.assertTrue((self.BRANDING / module).is_file())
        moz_build = (self.BRANDING / "moz.build").read_text(encoding="utf-8")
        self.assertRegex(moz_build, rf'EXTRA_JS_MODULES\.nulavio \+= \[[^\]]*"{re.escape(module)}"')
        self.assertIn('XPCOM_MANIFESTS += ["components.conf"]', moz_build)

    def test_address_bar_hook_is_small_and_conservative(self):
        patch = (
            ROOT / "browser" / "patches" / "0005-urlbar-let-smart-profile-routing-decide-typed-navigations.patch"
        ).read_text()
        added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        removed = [line for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(removed, [], "the hook only adds code")
        self.assertLessEqual(len(added), 25)
        self.assertIn('    "resource:///modules/nulavio/NulavioUrlbarRouting.sys.mjs",', added)
        hook = (self.BRANDING / "NulavioUrlbarRouting.sys.mjs").read_text(encoding="utf-8")
        self.assertIn("return false;", hook, "an unavailable router must not block typing")
        self.assertIn('"NulavioUrlbarRouting.sys.mjs"', (self.BRANDING / "moz.build").read_text(encoding="utf-8"))
        routing = module_text("NulavioRouting.sys.mjs")
        self.assertIn('if (postData || !["current", "tab", "tabshifted", "window"].includes(where)) {', routing)

    def test_link_menu_is_explicit_and_not_private(self):
        background = (SHELL / "background.js").read_text(encoding="utf-8")
        self.assertIn('targetUrlPatterns: ["http://*/*", "https://*/*"]', background)
        self.assertIn("tab?.incognito", background)
        self.assertIn("browser.nulavioRouting.openIn(", background)

    def test_handler_only_hands_over(self):
        handler = (self.BRANDING / "NulavioCommandLine.sys.mjs").read_text(encoding="utf-8")
        self.assertIn("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs", handler)
        self.assertNotRegex(handler, r"execProcess|sendCommandLine|Services\.prefs\.set")

    def test_never_a_shell_and_never_session_data(self):
        routing = module_text("NulavioRouting.sys.mjs") + module_text("NulavioRouter.sys.mjs")
        forbidden = r"nsIProcess|Subprocess\.|/bin/sh|\bbash\b|Services\.cookies|nsICookie|SessionStore|sessionstore\.js"
        self.assertIsNone(re.search(forbidden, routing), "routing must not run commands or touch sessions")
        self.assertIn('service.execProcess(["--profile", profile.path, ...args])', routing)

    def test_only_plain_url_forms_and_web_schemes_are_routed(self):
        router = module_text("NulavioRouter.sys.mjs")
        self.assertIn('const URL_FLAGS = new Set(["url", "new-tab", "new-window"]);', router)
        self.assertIn('const ROUTABLE_SCHEMES = new Set(["http", "https"]);', router)
        self.assertIn('return stay("private");', router)

    def test_pages_for_a_held_link_read_it_from_the_module(self):
        """Another installed extension can open any Shell page as a tab with a query of its own. The ask, blocked
        and unlock pages take only the id of a held link from their address (the unlock page also a profile to
        unlock, with no link): the link, the rule, the profile and the reason come from the routing module."""
        page = (SHELL / "routing" / "page.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'\.get\("(\w+)"\)', page), ["h"])
        self.assertIn("routing.held(id, `routing/${mode}.html`)", page)
        unlock = (SHELL / "vault" / "unlock.js").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r'params\.get\("(\w+)"\)', unlock))), ["h", "p"])
        self.assertIn('browser.nulavioRouting.held(id, "vault/unlock.html")', unlock)
        routing = module_text("NulavioRouting.sys.mjs")
        opener = routing[routing.index("async #openPage(") :]
        self.assertIn("const id = this.hold(page, params);", opener)
        self.assertIn("{ h: id }", opener)
        vault = module_text("NulavioVault.sys.mjs")
        opener = vault[vault.index("async openUnlockPage(") :]
        self.assertIn('params.set("h", lazy.NulavioRouting.hold("vault/unlock.html"', opener)
        self.assertNotIn('params.set("u"', opener)
        self.assertNotIn('params.set("src"', opener)  # the source is in the held link; the page reads no `src`

    def test_held_and_asked_links_open_in_a_normal_window(self):
        """#670: the pages for a held link (ask, blocked, unlock) and a held link that stays open as the engine opens a
        link from another app: in a normal window of the profile, a new one when only private windows are open; never
        in whichever window was used last, which may be private. Behaviour: test_held_links 08, 09 and 10."""
        routing = module_text("NulavioRouting.sys.mjs")
        page = routing[routing.index("async #openPage(") :]
        page = page[: page.index("\n  }\n")]
        self.assertTrue(page.split("\n", 2)[1].strip().startswith("const win = await this.#browserWindow();"), page)
        # No wait between keeping the link and opening its page: a slow first window must not take a slot of the
        # 64 kept links (evicting one a page already shows) before there is a page to show it.
        after_hold = page[page.index("const id = this.hold(page, params);") :]
        self.assertNotIn("await", after_hold)
        self.assertIn("this.#openFrom(win, `${policy.getURL(page)}?${query}`);", after_hold)
        self.assertEqual(len(re.findall(r"openTrustedLinkIn\(", routing)), 1, "every open goes through #openFrom")
        opener = routing[routing.index("\n  #openFrom(win, url) {") :]
        opener = opener[: opener.index("\n  }\n")]
        self.assertIn("const forceNonPrivate = !lazy.PrivateBrowsingUtils.permanentPrivateBrowsing;", opener)
        self.assertIn('win.openTrustedLinkIn(url, "tab", { forceNonPrivate })', opener)
        self.assertIn("this.#openFrom(await this.#browserWindow(), url);", routing)
        self.assertIn("await this.#openInNormalWindow(url); // held at start-up", routing)

    def test_rules_are_never_inferred(self):
        # Only the settings page, the toolbar selector and the ask page create or change rules.
        for path in SHELL.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\.(addRule|setRuleAction)\(", text):
                with self.subTest(path=str(path.relative_to(SHELL))):
                    self.assertIn(
                        path.relative_to(SHELL).as_posix(),
                        {
                            "settings/settings.js",
                            "profiles/popup.js",
                            "routing/page.js",
                            "experiments/routing/parent.js",
                        },
                    )


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assembled_pages_resolve_every_local_reference(self):
        out = self.tmp / "shell"
        files = set(make_shell.assemble(out))
        for page in out.rglob("*.html"):
            for ref in re.findall(r'(?:src|href|srcset)="([^"]+)"', page.read_text(encoding="utf-8")):
                if ref.startswith("#"):
                    continue  # a section of the same page
                target = (page.parent / ref.split("#")[0]).resolve()
                with self.subTest(page=page.name, ref=ref):
                    self.assertTrue(target.is_file(), f"{ref} missing")
                    self.assertIn(str(target.relative_to(out.resolve())), files)
        for icon in make_shell.manifest()["icons"].values():
            self.assertIn(icon, files)

    def test_unprivileged_variant_for_temporary_installs(self):
        out = self.tmp / "plain"
        files = make_shell.assemble(out, privileged=False)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        for key in ("experiment_apis", "action", "commands", "omnibox", "options_ui"):
            self.assertNotIn(key, manifest)
        # Only the plain-data modules the pages import stay (no experiment, no privileged module).
        self.assertFalse(
            [
                f
                for f in files
                if f.split("/")[0] in ("experiments", "modules", "settings", "profiles", "routing", "vault")
                and f not in make_shell.PLAIN_MODULES
            ]
        )
        self.assertIn("newtab/newtab.html", files)
        self.assertEqual(manifest["permissions"], make_shell.manifest()["permissions"])

    def test_every_relative_import_resolves_in_both_variants(self):
        """CI (Track A): the variant for a distribution Firefox dropped modules/ while lib/ui.js imported
        modules/NulavioAvatars.sys.mjs, so every page and the background failed to load there."""
        pattern = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|^\s*import\s+)["'](\.{1,2}/[^"']+)["']""", re.MULTILINE)
        for privileged in (True, False):
            out = self.tmp / f"imports-{privileged}"
            files = set(make_shell.assemble(out, privileged=privileged))
            for script in sorted(p for p in out.rglob("*") if p.suffix in (".js", ".mjs")):
                if script.relative_to(out).parts[0] in ("experiments", "modules") and privileged:
                    continue  # chrome code: resource:// and moz-src:// imports, checked with the engine
                for ref in pattern.findall(script.read_text(encoding="utf-8")):
                    target = (script.parent / ref).resolve()
                    with self.subTest(privileged=privileged, script=str(script.relative_to(out)), ref=ref):
                        self.assertTrue(target.is_file(), f"{ref} missing")
                        self.assertIn(str(target.relative_to(out.resolve())), files)

    def test_plain_modules_use_no_privileged_global(self):
        for relative in make_shell.PLAIN_MODULES:
            text = (ROOT / "browser" / "shell" / relative).read_text(encoding="utf-8")
            code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
            with self.subTest(module=relative):
                self.assertNotRegex(code, r"\b(?:Services|ChromeUtils|Components|Cc|Ci|Cu|import)\b")

    def test_build_files_list_every_file_under_builtin_addons(self):
        branding = self.tmp / "branding"
        branding.mkdir()
        shell = make_shell.install(branding)
        generated = {"jar.mn", "moz.build"}
        files = sorted(str(p.relative_to(shell)) for p in shell.rglob("*") if p.is_file() and p.name not in generated)
        jar = (shell / "jar.mn").read_text(encoding="utf-8").splitlines()
        self.assertIn("browser.jar:", jar)
        entries = [line.strip() for line in jar if line.startswith("    ")]
        self.assertEqual(entries, [f"builtin-addons/nulavio-shell/{f} ({f})" for f in files])
        self.assertIn('JAR_MANIFESTS += ["jar.mn"]', (shell / "moz.build").read_text(encoding="utf-8"))

    def test_branding_builds_the_shell(self):
        moz_build = (ROOT / "browser" / "branding" / "nulavio" / "moz.build").read_text(encoding="utf-8")
        self.assertRegex(moz_build, r'DIRS \+= \[[^\]]*"shell"')


class GuardModuleTest(unittest.TestCase):
    """Nulavio Guard at run time: what it watches, where its record lives, what it never does."""

    def setUp(self):
        self.source = module_text("NulavioGuard.sys.mjs")
        block = self.source[self.source.index("WATCHED_PREFS = Object.freeze([") :]
        self.watched = re.findall(r'"([^"]+)"', block[: block.index("]);")])

    def watches(self, name: str) -> bool:
        return name in self.watched or any(w.endswith(".") and name.startswith(w) for w in self.watched)

    def test_watches_every_protective_pref_the_launcher_guard_checks(self):
        rules = json.loads((ROOT / "browser" / "config" / "guard-rules.json").read_text(encoding="utf-8"))["rules"]
        # Automation prefs are set (and left in prefs.js) by the AI Bridge for an agent session in a given profile.
        automation = {"remote.prefs.recommended", "marionette.port"}
        for rule in rules:
            if rule["pref"] not in automation:
                self.assertTrue(self.watches(rule["pref"]), rule["pref"])
        for name in ("network.proxy.http", "network.proxy.type", "network.trr.uri", "security.enterprise_roots.enabled"):
            self.assertTrue(self.watches(name), name)

    def test_record_lives_in_the_profile_and_nothing_is_sent(self):
        self.assertIn('RECORD = "nulavio-guard.json"', self.source)
        self.assertIn('"ProfD"', self.source)
        for forbidden in ("fetch(", "XMLHttpRequest", "newChannel", "sendBeacon", "WebSocket"):
            self.assertNotIn(forbidden, self.source)

    def test_undo_only_after_a_click(self):
        review = (SHELL / "guard" / "review.js").read_text(encoding="utf-8")
        background = (SHELL / "background.js").read_text(encoding="utf-8")
        self.assertNotIn("resolve(", background)
        self.assertIn("browser.runtime.onStartup.addListener", background)  # the event page starts with the browser
        self.assertIn('addEventListener("click"', review)
        self.assertEqual(review.count("guard.resolve("), 1)


class LocaleKeysTest(unittest.TestCase):
    def test_no_message_is_defined_twice(self):
        """A key given twice keeps only the last one, so one feature shows another's words (#486: two features'
        `err_invalid_choice`)."""
        for name in ("pt_BR", "en"):
            with self.subTest(locale=name):
                text = (SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8")
                # The engine keeps message names in lower case, so two that differ only in case are one.
                keys = [key.lower() for key, _ in json.loads(text, object_pairs_hook=lambda pairs: pairs)]
                self.assertEqual(sorted({key for key in keys if keys.count(key) > 1}), [])


def call_arguments(text: str, start: int) -> str:
    """The arguments of the call whose `(` ends just before `start`, up to its own `)`: nested calls,
    objects and brackets included, and a bracket inside a string literal, a comment or a regex literal
    not counted. A `/` after an operator or an opening bracket starts a regex literal, otherwise it divides."""
    depth, quote, index = 1, None, start
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                break
        elif text.startswith("/*", index):
            index = text.find("*/", index + 2) + 1
            if index <= 0:
                break
        elif char == "/" and (text[start:index].rstrip()[-1:] or "(") in "([{,;:=!&|?+-*%<>~^":
            klass, index = False, index + 1
            while index < len(text) and (klass or text[index] != "/"):
                if text[index] == "\\":
                    index += 1
                elif text[index] in "[]":
                    klass = text[index] == "["
                index += 1
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:index]
        index += 1
    return text[start:]


class LastTabCloseTest(unittest.TestCase):
    """#700, #720: Close, Cancel and "Don't open" on a page that is its window's only tab. The engine refuses
    `tabs.update` to an about: address from an extension page, so the button did nothing; removing the tab
    closed the window. One function closes every such page."""

    PAGES = (
        "ai/request.js",
        "vault/unlock.js",
        "vault/create.js",
        "guard/review.js",
        "warning/warning.js",
        "passwords/lookalike.js",
        "routing/page.js",
    )
    ABOUT = r"""["'`]about:"""

    def test_the_scan_reads_the_whole_call(self):
        missed = 'tabs.update(Number(id), { url: "about:newtab" });'
        self.assertRegex(call_arguments(missed, missed.index("(") + 1), self.ABOUT)
        quoted = 'tabs.update(tab.id, { url: ")" + "about:blank" }); other("about:x");'
        self.assertEqual(call_arguments(quoted, quoted.index("(") + 1), 'tab.id, { url: ")" + "about:blank" }')
        # A comment or a regex literal is skipped whole: a bracket or a quote in it is not counted (OpenCodeReview, #735).
        for early in (
            'tabs.update(tab.id, /* ) */ { url: "about:newtab" });',
            'tabs.update(tab.id, // )\n  { url: "about:newtab" });',
            'tabs.update(tab.id, { url: s.replace(/[)]/, "") + "about:blank" });',
            'tabs.update(tab.id, { url: s.replace(/\\)/g, "") + "about:blank" });',
        ):
            with self.subTest(early=early):
                self.assertRegex(call_arguments(early, early.index("(") + 1), self.ABOUT)
        for late in (
            'tabs.update(tab.id, { url: web }); // (it\'s a web page)\nother("about:x");',
            'tabs.update(tab.id, /* ( */ { url: web }); other("about:x");',
            'tabs.update(tab.id, { url: web.replace(/[(]/, "") }); other("about:x");',
            'tabs.update(tab.id, { url: n / 2 }); other("about:x");',
        ):
            with self.subTest(late=late):
                self.assertNotRegex(call_arguments(late, late.index("(") + 1), self.ABOUT)

    def test_no_shell_script_loads_an_about_address_into_a_tab(self):
        for script in sorted(p for p in SHELL.rglob("*") if p.suffix in (".js", ".mjs")):
            text = script.read_text(encoding="utf-8")
            for call in re.finditer(r"tabs\.update\(", text):
                with self.subTest(script=str(script.relative_to(SHELL))):
                    self.assertNotRegex(call_arguments(text, call.end()), self.ABOUT)

    def test_every_page_with_close_or_cancel_uses_the_one_function(self):
        for page in self.PAGES:
            text = (SHELL / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertRegex(text, r'import \{ closeOwnTab(?:Soon)? \} from "\.\./lib/tabs\.js";')
                self.assertNotIn("tabs.remove(", text)
                self.assertNotIn("siblings", text)

    def test_the_page_asks_the_background_and_says_when_it_cannot(self):
        text = (SHELL / "lib" / "tabs.js").read_text(encoding="utf-8")
        body = text[text.index("export async function closeOwnTab(") :]
        body = body[: body.index("\n}\n")]
        # The page no longer counts or removes tabs itself (#741): the background decides, one close per window.
        for own in ("tabs.query(", "tabs.remove(", "tabs.create(", "tabs.getCurrent("):
            self.assertNotIn(own, body)
        self.assertIn('(await browser.runtime.sendMessage({ type: "close-own-tab" })) !== true', body)
        self.assertIn('failed(t("tabCloseFailed"))', body.split("catch", 1)[1])
        self.assertNotIn("about:", body)
        # A second click while the tab closes does nothing; a failure lets the page try again.
        self.assertLess(body.index("if (closing) {"), body.index("browser.runtime.sendMessage("))
        self.assertLess(body.index("closing = true;"), body.index("try {"))
        self.assertIn("closing = false;", body.split("catch", 1)[1])
        for name in ("en", "pt_BR"):
            self.assertIn("tabCloseFailed", locale(name))

    def test_the_background_closes_only_the_asking_pages_own_tab(self):
        background = (SHELL / "background.js").read_text(encoding="utf-8")
        self.assertIn('import { tabCloser } from "./lib/tab-closer.js";', background)
        self.assertIn("const closeTab = tabCloser(browser.tabs);", background)
        listener = background[background.index('if (message?.type !== "close-own-tab") {') :]
        listener = listener[: listener.index("\n});\n")]
        # This extension's page, in a tab of its own, top frame; the tab it closes is the sender's, never one it names.
        self.assertIn("sender.id === browser.runtime.id", listener)
        self.assertIn('String(sender.url ?? "").startsWith(browser.runtime.getURL(""))', listener)
        self.assertIn("if (!page || !sender.tab || sender.frameId) {", listener)
        self.assertIn("return closeTab(sender.tab.id, sender.url);", listener)
        self.assertNotIn("message.tab", listener)
        # The one place that removes a Shell page's tab: no other Shell script counts and removes for a close.
        closer = (SHELL / "lib" / "tab-closer.js").read_text(encoding="utf-8")
        self.assertNotRegex(closer, r"(?m)^import ", "the closer runs in the background and in node, with no imports")
        self.assertNotRegex(closer, r"\bbrowser\.\w+\.\w+\(", "the closer only uses the tabs it is given")
        self.assertIn("tabs.query({ windowId, hidden: false })", closer)  # only visible tabs count (#720)

    def test_a_held_link_page_that_could_not_close_never_sends_the_link_twice(self):
        # "Open in …", "Try again" and "Unlock and open" send the link, then close the tab. When only the close
        # fails, the buttons that send it stay off for good; "Don't open" (which only closes) comes back.
        text = (SHELL / "routing" / "page.js").read_text(encoding="utf-8")
        sends = [m.start() for m in re.finditer(r"await (?:routing\.openIn|browser\.nulavioVault\.openUnlockPage)\(", text)]
        self.assertEqual(len(sends), 3)
        for start in sends:
            after = text[start:]
            with self.subTest(call=after[: after.index("(")]):
                self.assertLess(after.index("sent = true;"), after.index("await closeThisTab();"))
                self.assertLess(after.index(";"), after.index("sent = true;"))  # the next statement
        enable = text[text.index("function enableActions(") :]
        self.assertIn('b.disabled = !enabled || (sent && !("close" in b.dataset));', enable[: enable.index("\n}\n")])
        dont_open = r'button\(t\("routingDontOpen"\), "button--quiet", closeThisTab\);\n\s+dontOpen\.dataset\.close = "";'
        self.assertRegex(text, dont_open)
        self.assertEqual(text.count("dataset.close"), 1)


# lib/tab-closer.js against fake tabs: each call settles one turn of the event loop later, so two closes started
# together interleave the same way every run. A window whose last visible tab is removed closes, as in the engine.
# Each tab shows `page:<id>` until the test navigates it. `hold` keeps a removal pending (as a page that warns
# before it is left does while the person answers) until the test lets it go; `fail` makes one removal fail once;
# `beforeQuery` runs once, as a count starts, and `afterQuery` once, right after one. A window left with no visible
# tab closes, whether its last one was removed or dragged out. The module is read as a data: address, which is always a module,
# so a node that does not tell a .js file's kind by its syntax runs it too.
TAB_CLOSER = r"""
const { readFileSync } = await import("node:fs");
const source = readFileSync(process.argv[1], "utf8");
const { tabCloser } = await import("data:text/javascript;charset=utf-8," + encodeURIComponent(source));
const later = () => new Promise(resolve => setImmediate(resolve));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const page = id => `page:${id}`;

function world(windows) {
  const shown = list => list.map(tab => ({ url: page(tab.id), ...tab }));
  const state = new Map(Object.entries(windows).map(([id, list]) => [Number(id), shown(list)]));
  const closed = [];
  const hold = new Map();
  const fail = new Set();
  const w = { closed, hold, fail, beforeQuery: null, afterQuery: null };
  let next = 100;
  const find = id => {
    for (const [windowId, list] of state) {
      const tab = list.find(t => t.id === id);
      if (tab) return { windowId, list, tab };
    }
    throw new Error(`no tab ${id}`);
  };
  w.tabs = {
    async get(id) { await later(); const f = find(id); return { id, windowId: f.windowId, url: f.tab.url }; },
    async query({ windowId, hidden }) {
      const first = w.beforeQuery;
      w.beforeQuery = null;
      first?.();
      await later();
      const found = (state.get(windowId) ?? []).filter(t => Boolean(t.hidden) === hidden).map(t => ({ id: t.id, windowId }));
      const then = w.afterQuery;
      w.afterQuery = null;
      then?.();
      return found;
    },
    async create({ windowId }) {
      await later();
      const list = state.get(windowId);
      if (!list) throw new Error(`no window ${windowId}`);
      const tab = { id: next++, url: "new", fresh: true };
      list.push(tab);
      return { id: tab.id, windowId };
    },
    async remove(id) {
      await later();
      await hold.get(id);
      if (fail.delete(id)) throw new Error("the engine refused");
      const { windowId, list, tab } = find(id);
      list.splice(list.indexOf(tab), 1);
      emptied(windowId, list);
    },
  };
  w.tabsOf = id => state.has(id) ? state.get(id).map(t => t.fresh ? "new" : t.id) : null;
  const emptied = (windowId, list) => {
    if (!list.some(t => !t.hidden)) { state.delete(windowId); closed.push(windowId); }
  };
  w.move = (id, to) => {
    const { windowId, list, tab } = find(id);
    list.splice(list.indexOf(tab), 1);
    state.get(to).push(tab);
    emptied(windowId, list);
  };
  w.drop = id => { const { list, tab } = find(id); list.splice(list.indexOf(tab), 1); }; // the person closes it
  w.navigate = (id, url) => { find(id).tab.url = url; };
  return w;
}

// What each page did from its own document before #741: count, then remove, with nothing shared.
async function perDocument(tabs, id) {
  const tab = await tabs.get(id);
  const visible = await tabs.query({ windowId: tab.windowId, hidden: false });
  if (!visible.some(other => other.id !== id)) await tabs.create({ windowId: tab.windowId });
  await tabs.remove(id);
}

const out = {};

{ // Before: two Shell pages, a window's only tabs, closing at once, each count the other: the window closes.
  const w = world({ 1: [{ id: 1 }, { id: 2 }] });
  await Promise.all([perDocument(w.tabs, 1), perDocument(w.tabs, 2)]);
  out.perDocument = { closed: w.closed, tabs: w.tabsOf(1) };
}
{ // Now: the second close counts after the first removal, and opens the new tab.
  const w = world({ 1: [{ id: 1 }, { id: 2 }] });
  const close = tabCloser(w.tabs);
  out.together = { answers: await Promise.all([close(1, page(1)), close(2, page(2))]), closed: w.closed, tabs: w.tabsOf(1) };
}
{ // Three at once, and a window with other tabs: nothing extra is opened there.
  const w = world({ 1: [{ id: 1 }, { id: 2 }, { id: 3 }], 2: [{ id: 4 }, { id: 5 }] });
  const close = tabCloser(w.tabs);
  await Promise.all([1, 2, 3, 4].map(id => close(id, page(id))));
  out.three = { closed: w.closed, one: w.tabsOf(1), two: w.tabsOf(2) };
}
{ // Only visible tabs count (#720): a window whose other tab is hidden keeps a new tab.
  const w = world({ 1: [{ id: 1 }, { id: 2, hidden: true }] });
  await tabCloser(w.tabs)(1, page(1));
  out.hidden = { closed: w.closed, tabs: w.tabsOf(1) };
}
{ // A removal that fails is reported to its page, and the next close in that window still runs.
  const w = world({ 1: [{ id: 1 }, { id: 2 }] });
  w.fail.add(1);
  const close = tabCloser(w.tabs);
  const [first, second] = await Promise.allSettled([close(1, page(1)), close(2, page(2))]);
  const reason = String(first.reason?.message);
  out.failed = { first: first.status, reason, second: second.value, closed: w.closed, tabs: w.tabsOf(1) };
}
{ // A removal still pending (the person has not answered a page's warning yet) holds the next close in its window
  // for as long as it takes, `wait` or not, and only there; once it is done, the next one counts without it.
  const w = world({ 1: [{ id: 1 }, { id: 2 }], 2: [{ id: 4 }, { id: 5 }] });
  let release;
  w.hold.set(1, new Promise(resolve => (release = resolve)));
  const close = tabCloser(w.tabs, { wait: 20 }); // the bound an earlier version had, which let the next one count
  const order = [];
  const pending = close(1, page(1)).then(() => order.push("held"));
  await pause(20);
  const same = close(2, page(2)).then(() => order.push("same window"));
  await close(4, page(4)).then(() => order.push("other window"));
  await pause(200);
  const whileHeld = { order: [...order], one: w.tabsOf(1) };
  release();
  await Promise.all([pending, same]);
  out.held = { whileHeld, order, closed: w.closed, one: w.tabsOf(1), two: w.tabsOf(2) };
}
{ // A tab moved to another window while its close waited is counted in the window it is now in.
  const w = world({ 1: [{ id: 1 }, { id: 2 }, { id: 3 }], 2: [{ id: 9, hidden: true }] });
  let release;
  w.hold.set(1, new Promise(resolve => (release = resolve)));
  const close = tabCloser(w.tabs);
  const first = close(1, page(1));
  await pause(20);
  const second = close(2, page(2)); // queued behind tab 1, in window 1
  await pause(20);
  w.move(2, 2); // window 2's only visible tab now
  release();
  await Promise.all([first, second]);
  out.moved = { closed: w.closed, one: w.tabsOf(1), two: w.tabsOf(2) };
}
{ // Moved while it was being counted: the window it left had another tab, the one it went to has none.
  const w = world({ 1: [{ id: 1 }, { id: 3 }], 2: [{ id: 9, hidden: true }] });
  w.afterQuery = () => w.move(1, 2);
  await tabCloser(w.tabs)(1, page(1));
  out.movedWhileCounted = { closed: w.closed, one: w.tabsOf(1), two: w.tabsOf(2) };
}
{ // A tab navigated to another page while its close waited is never removed for the page that left.
  const w = world({ 1: [{ id: 1 }, { id: 2 }, { id: 3 }] });
  let release;
  w.hold.set(1, new Promise(resolve => (release = resolve)));
  const close = tabCloser(w.tabs);
  const first = close(1, page(1));
  await pause(20);
  const second = close(2, page(2));
  await pause(20);
  w.navigate(2, "https://work.example/");
  release();
  await first;
  const left = await second.then(() => "removed", e => String(e.message));
  out.navigated = { left, closed: w.closed, one: w.tabsOf(1) };
}
{ // The window's other tab closed by the person right after the count: counted again, a new tab keeps the window.
  const w = world({ 1: [{ id: 1 }, { id: 3 }] });
  w.afterQuery = () => w.drop(3);
  const answer = await tabCloser(w.tabs)(1, page(1));
  out.otherClosedWhileCounted = { answer, closed: w.closed, one: w.tabsOf(1) };
}
{ // Navigated as it was counted, alone in its window: the same look sees it, and no new tab is opened for it.
  const w = world({ 1: [{ id: 1 }] });
  w.beforeQuery = () => w.navigate(1, "https://work.example/");
  const left = await tabCloser(w.tabs)(1, page(1)).then(() => "removed", e => String(e.message));
  out.navigatedWhileCounted = { left, closed: w.closed, one: w.tabsOf(1) };
}
{ // Dragged out alone right after the count, so its old window closed and the new tab could not open there:
  // counted again in the window it went to.
  const w = world({ 1: [{ id: 1 }], 2: [{ id: 9, hidden: true }] });
  w.afterQuery = () => w.move(1, 2);
  const answer = await tabCloser(w.tabs)(1, page(1)).then(String, e => String(e.message));
  out.movedOutAlone = { answer, closed: w.closed, two: w.tabsOf(2) };
}
console.log(JSON.stringify(out));
"""


@requires_node
class TabCloserTest(unittest.TestCase):
    """#741: two Shell pages closing at once, from their own documents, could each count the other and close their
    window. The background now decides every close, one at a time per window (lib/tab-closer.js)."""

    @classmethod
    def setUpClass(cls):
        module = str(SHELL / "lib" / "tab-closer.js")
        done = subprocess.run(["node", "--input-type=module", "-e", TAB_CLOSER, module],
                              capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
        cls.out = json.loads(done.stdout)

    def test_the_fake_shows_the_race_the_pages_had(self):
        # Without this, the next test could pass on a fake that never interleaves.
        self.assertEqual(self.out["perDocument"], {"closed": [1], "tabs": None})

    def test_two_pages_closing_at_once_leave_their_window_on_a_new_tab(self):
        self.assertEqual(self.out["together"], {"answers": [True, True], "closed": [], "tabs": ["new"]})
        self.assertEqual(self.out["three"], {"closed": [], "one": ["new"], "two": [5]})

    def test_only_visible_tabs_count(self):
        self.assertEqual(self.out["hidden"], {"closed": [], "tabs": [2, "new"]})

    def test_a_failed_close_is_reported_and_does_not_block_the_window(self):
        self.assertEqual(
            self.out["failed"],
            {"first": "rejected", "reason": "the engine refused", "second": True, "closed": [], "tabs": [1]},
        )

    def test_a_pending_removal_holds_its_window_until_it_is_done_and_no_other(self):
        held = self.out["held"]
        # While tab 1's removal is pending, tab 2 waits (however long), and window 2 does not.
        self.assertEqual(held["whileHeld"], {"order": ["other window"], "one": [1, 2]})
        self.assertEqual(held["order"], ["other window", "held", "same window"])
        # Tab 2 counted after tab 1 went: window 1 stays, on a new tab.
        self.assertEqual(held["closed"], [])
        self.assertEqual(held["one"], ["new"])
        self.assertEqual(held["two"], [5])

    def test_a_tab_moved_while_it_waited_is_counted_where_it_is(self):
        self.assertEqual(self.out["moved"], {"closed": [], "one": [3], "two": [9, "new"]})

    def test_a_tab_moved_while_it_was_counted_is_counted_again_where_it_is(self):
        self.assertEqual(self.out["movedWhileCounted"], {"closed": [], "one": [3], "two": [9, "new"]})

    def test_the_other_tab_closed_while_it_was_counted_is_counted_again(self):
        self.assertEqual(self.out["otherClosedWhileCounted"], {"answer": True, "closed": [], "one": ["new"]})

    def test_a_tab_navigated_as_it_was_counted_opens_nothing(self):
        left = "the page that asked left its tab"
        self.assertEqual(self.out["navigatedWhileCounted"], {"left": left, "closed": [], "one": [1]})

    def test_a_tab_dragged_out_alone_while_it_was_counted_is_closed_where_it_went(self):
        self.assertEqual(self.out["movedOutAlone"], {"answer": "true", "closed": [1], "two": [9, "new"]})

    def test_a_tab_that_left_the_page_is_never_removed(self):
        self.assertEqual(self.out["navigated"], {"left": "the page that asked left its tab", "closed": [], "one": [2, 3]})


class PasswordsTest(unittest.TestCase):
    """Flows B and D: pinned providers, and a content script that never reads what is typed."""

    def test_provider_data_matches_the_pins(self):
        data = make_shell.providers()["providers"]
        lock = {
            e["key"]: e
            for e in json.loads((ROOT / "browser" / "distribution" / "extensions.lock.json").read_text())["extensions"]
        }
        config = json.loads((ROOT / "browser" / "config" / "providers.json").read_text())["providers"]
        self.assertEqual(set(data), set(config))
        for key, provider in data.items():
            with self.subTest(provider=key):
                ext_key = config[key]["extension"]
                if ext_key is None:
                    self.assertIsNone(provider["extension"])
                    continue
                self.assertEqual(provider["extension"]["sha256"], lock[ext_key]["sha256"])
                self.assertEqual(provider["extension"]["version"], lock[ext_key]["version"])
                self.assertTrue(provider["extension"]["url"].startswith("https://addons.mozilla.org/"))
                self.assertEqual(provider["prefs"]["signon.rememberSignons"], False)

    def test_new_tab_knows_every_provider(self):
        """The new tab's password status names each external provider (review of #478: it had no 1Password)."""
        config = json.loads((ROOT / "browser" / "config" / "providers.json").read_text())["providers"]
        lock = {
            e["key"]: e["id"]
            for e in json.loads((ROOT / "browser" / "distribution" / "extensions.lock.json").read_text())["extensions"]
        }
        expected = {lock[p["extension"]] for p in config.values() if p["extension"]}
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        block = newtab[newtab.index("const PROVIDERS = [") : newtab.index("];", newtab.index("const PROVIDERS = ["))]
        self.assertEqual(set(re.findall(r'\["([^"]+)", "', block)), expected)

    def test_lookalike_check_reads_nothing_from_pages(self):
        child = module_text("NulavioLookalikeChild.sys.mjs")
        code = re.sub(r"//.*", "", child.rsplit("*/", 1)[1])  # without the comments
        page_reads = (".value", "innerText", "textContent", "location", "form", "fetch(", ".key", ".code", ".which", ".data")
        for forbidden in (*page_reads, "clipboard"):
            self.assertNotIn(forbidden, code)
        # Of the document, only whether the person has just interacted with it (the engine's transient user activation).
        self.assertEqual(re.findall(r"document\b\.?\w*", code), ["document.hasValidTransientUserGestureActivation"])
        self.assertEqual(code.count("sendQuery("), 1)
        self.assertNotIn("sendAsyncMessage(", code)
        parent = module_text("NulavioLookalikeParent.sys.mjs")
        # The addresses come from the engine: each document's own address, or its principal's site.
        code = re.sub(r"//.*", "", parent.rsplit("*/", 1)[1])
        self.assertEqual(set(re.findall(r"global\??\.(document\w+)", code)), {"documentURI", "documentPrincipal"})
        self.assertIn("for (let global = this.manager; global; global = global.browsingContext?.parentWindowContext)", code)
        self.assertNotIn("message.data", parent)
        self.assertNotIn("content_scripts", make_shell.manifest())

    def test_lookalike_check_runs_in_every_frame_of_a_web_page(self):
        """The child runs in the tab's page and in its frames, for the documents that have a site or take one from
        the page that made them; never in an extension's page or a browser page."""
        source = module_text("NulavioPasswords.sys.mjs")
        options = source[source.index('registerWindowActor("NulavioLookalike"') :]
        options = options[: options.index("});")]
        matches = json.loads(re.search(r"matches: (\[[^\]]*\])", options).group(1))
        self.assertEqual(matches, ["http://*/*", "https://*/*", "about:blank", "about:srcdoc", "blob:*", "data:*"])
        self.assertIn("allFrames: true,", options)
        # Only an actor that exists hears pageshow (a document shown again); none is made for it.
        self.assertIn("pageshow: { createActor: false }", options)
        self.assertIn('messageManagerGroups: ["browsers"],', options)
        self.assertNotIn("moz-extension", "".join(matches))

    def test_the_warning_page_names_only_what_the_module_finds(self):
        """The look-alike warning is opened with the site's address only, and a flag with no address when the field
        was in a frame; the passwords module finds the saved site it imitates again from its origin, and "continue"
        passes the pair the page shows, which the module remembers only if it still finds that same pair (#762); a
        refusal keeps the page. "Continue" goes to that address or back in the tab's history, never to an address of
        its own."""
        parent = module_text("NulavioLookalikeParent.sys.mjs")
        self.assertIn("new URLSearchParams({ url })", parent)
        self.assertEqual(re.findall(r'query\.set\(("\w+", "\w+")\)', parent), ['"in", "frame"'])
        page = (SHELL / "passwords" / "lookalike.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'params\.get\("(\w+)"\)', page), ["url"])
        self.assertEqual(re.findall(r'params\.has\("(\w+)"\)', page), ["in"])
        # The module needs only the host: the origin stays under the experiment API's length limit.
        self.assertIn('const origin = url ? `${url.origin}/` : "";', page)
        self.assertIn("browser.nulavioPasswords.check(origin)", page)
        self.assertIn("browser.nulavioPasswords.dismiss(origin, site, similar, back)", page)
        # Only a saved choice goes on: an answer of { dismissed: false } is a refusal, as a thrown error is.
        refused = page.index("if (answer?.dismissed !== true) {")
        self.assertLess(refused, page.index("history.back()"))
        self.assertIn('announce(t("lookalikeDismissFailed"), "error");\n      return;', page[refused:])
        # Back only when the engine's session history has an entry before the warning; the module checks it again.
        self.assertIn("await browser.nulavioPasswords.canGoBack()", page)
        self.assertNotIn("history.length", page)
        self.assertEqual(re.findall(r"location\.replace\(([^)]*)\)", page), ["`https://${similar}/`", "url.href"])
        self.assertEqual(page.count("history.back()"), 1)
        # One title whether or not the module finds a pair: another extension reads a tab's title.
        self.assertNotIn("document.title", page)
        schema = json.loads((SHELL / "experiments" / "passwords" / "schema.json").read_text(encoding="utf-8"))[0]
        params = {f["name"]: [p["name"] for p in f["parameters"]] for f in schema["functions"]}
        self.assertEqual(params["dismiss"], ["url", "site", "similar", "back"])
        self.assertEqual((params["check"], params["canGoBack"]), (["url"], []))


class LayoutModuleTest(unittest.TestCase):
    """D-UX2 and UX3E: safe new-profile Lateral adoption, P3-1 listener safety and P3-2 window swap."""

    def test_layout_module_writes_only_sidebar_presets_and_adoption_markers(self):
        source = module_text("NulavioLayout.sys.mjs")
        writes = set(re.findall(r"Services\.prefs\.set(?:Bool|Int|String)Pref\(([^,]+),", source))
        self.assertEqual(
            writes,
            # UX3G N-4 (provisional): the new-profile start-page flag is written with the adoption markers.
            {
                '"sidebar.verticalTabs"',
                '"sidebar.visibility"',
                "PREF_ADOPTION_VERSION",
                "PREF_BEFORE_FOCUS",
                "PREF_CHOICE_PENDING",
                "PREF_IMMERSIVE",  # ADR 0009: the Immersive switch, a layout pref and no protection
                "PREF_SHELL_START",
            },
        )
        self.assertIn('"SwapDocShells"', source)
        self.assertIn('"EndSwapDocShells"', source)
        privacy = module_text("NulavioPrivacy.sys.mjs")
        self.assertLess(privacy.index("lazy.NulavioLayout.adoptInitialLayout()"), privacy.index("setIntPref(PREF_SEEDED"))

    def test_layout_pictures_exist_in_settings_and_in_the_first_run(self):
        """UX6 S1: each preset has its picture on both surfaces (the first-run card and the settings page's picker)."""

        def pictures(page: str) -> dict[str, str]:
            html = (SHELL / page).read_text(encoding="utf-8")
            found = {}
            for label in re.findall(r'<label class="layout-option">(.*?)</label>', html, re.S):
                svg = re.search(r"<svg .*?</svg>", label, re.S).group(0)
                value = re.search(r'type="radio" name="[^"]+" value="([a-z]+)"', label).group(1)
                found[value] = re.sub(r"\s+", " ", svg).strip()
            return found

        # The first-run card draws each arrangement inline; the settings page's picker shows a picture file per
        # arrangement (settings/native). Both exist for the same three.
        self.assertEqual(set(pictures("newtab/newtab.html")), {"lateral", "top", "focus"})
        for value in ("lateral", "top", "focus"):
            self.assertTrue((SHELL / "settings" / "native" / f"layout-{value}.svg").is_file(), value)

    def test_layout_names_bridge_to_the_engine_settings(self):
        # ADR 0008: there is one Settings, and the engine's own two-way "Vertical/Horizontal tabs" control is
        # replaced there by Nulavio's picker (QA B-9's bridge to the engine's words went with the second
        # control). The first-run card's link names the pane the choice lives in.
        for name, pane in (("pt_BR", "Aparência"), ("en", "Appearance")):
            with self.subTest(locale=name):
                msg = {k: v["message"] for k, v in locale(name).items()}
                self.assertIn(pane, msg["layoutChoiceSettings"])

    def test_layout_surfaces_guard_listener_registration(self):
        # The new tab's card listens through the extension API; the settings page's picker subscribes in the module,
        # inside its own try (settings/native/panes.mjs).
        source = (SHELL / "newtab/newtab.js").read_text(encoding="utf-8")
        self.assertRegex(source, r"try\s*\{\s*api\.onChanged\.addListener\(")
        panes = (SHELL / "settings/native/panes.mjs").read_text(encoding="utf-8")
        self.assertRegex(panes, r"try\s*\{\s*stops\.push\(shell\.NulavioLayout\.subscribe\(")


class ImmersiveDevicesTest(unittest.TestCase):
    """#627: Immersive keeps the toolbar while the engine draws an in-use icon in it. Besides capture (camera,
    microphone, screen: the tab's `sharing` attribute), the engine 160 draws one for the location, a serial port and
    a VR device from the browser's `_sharingState` keys `geo`, `serial` and `xr`, on `#geo-sharing-icon`,
    `#serial-sharing-icon` and `#xr-sharing-icon`, for the selected tab only (browser-sitePermissionPanel.js,
    updateSharingIndicator), and marks no tab for them. `test_immersive` 06d drives the real path."""

    SOURCE = (SHELL / "modules" / "NulavioWindow.sys.mjs").read_text(encoding="utf-8")

    def constant(self, name: str) -> list[str]:
        found = re.search(rf"const {name} = Object\.freeze\(\[([^\]]*)\]\);", self.SOURCE)
        self.assertIsNotNone(found, name)
        return re.findall(r'"([^"]+)"', found.group(1))

    def method(self, name: str) -> str:
        start = self.SOURCE.index(f"  {name}(")
        end = self.SOURCE.index("\n  }\n", start)
        return self.SOURCE[start:end]

    def test_every_in_use_icon_of_the_engine_is_read(self):
        self.assertEqual(self.constant("DEVICE_STATES"), ["geo", "serial", "xr"])
        self.assertEqual(self.constant("DEVICE_ICONS"), ["geo-sharing-icon", "serial-sharing-icon", "xr-sharing-icon"])

    def test_the_selected_tab_is_what_counts_and_the_reason_is_sharing(self):
        block = self.method("#immersiveBlock")
        self.assertRegex(
            block,
            r"const devices = win\.gBrowser\.selectedBrowser\?\._sharingState;\s*"
            r"if \(DEVICE_STATES\.some\(key => devices\?\.\[key\]\)\) \{\s*return \"sharing\";",
        )

    def test_a_change_of_icon_decides_again_and_the_observer_goes_with_the_window(self):
        attach = self.SOURCE[self.SOURCE.index("const deviceIcons = new win.MutationObserver") :]
        self.assertRegex(attach, r"^const deviceIcons = new win\.MutationObserver\(\(\) => this\.#applyImmersive\(win\)\);")
        self.assertRegex(attach, r"for \(const id of DEVICE_ICONS\) \{")
        self.assertRegex(attach, r'deviceIcons\.observe\(icon, \{ attributes: true, attributeFilter: \["sharing"\] \}\);')
        self.assertIn("deviceIcons, opened,", self.SOURCE)
        self.assertIn("state.deviceIcons.disconnect();", self.method("#detach"))

    def test_the_docs_name_the_devices_and_no_longer_say_any_device(self):
        risks = (ROOT / "docs/security/residual-risks.md").read_text(encoding="utf-8")
        r64 = next(line for line in risks.splitlines() if line.startswith("| R64 |"))
        principles = (ROOT / "docs/design/ux-principles.md").read_text(encoding="utf-8")
        for name, text in (("R64", r64), ("ux-principles", principles)):
            with self.subTest(doc=name):
                self.assertNotIn("while a device is shared", text)
                for device in ("the camera, the microphone or the screen", "location", "serial"):
                    self.assertIn(device, text)
        adr = (ROOT / "docs/adr/0009-immersive-layout.md").read_text(encoding="utf-8")
        self.assertIn("(#627): while the engine draws its in-use icon for the location, a serial port", adr)
        model = (ROOT / "docs/security/threat-model.md").read_text(encoding="utf-8")
        s6 = model[model.index("### S6") : model.index("### S7")]
        limitations = next(line for line in s6.splitlines() if line.startswith("| Limitations |"))
        self.assertIn("[R64](residual-risks.md)", limitations)
        matrix = (ROOT / "docs/security/threat-matrix.md").read_text(encoding="utf-8")
        self.assertIn("R64", next(line for line in matrix.splitlines() if line.startswith("| S6 |")))


if __name__ == "__main__":
    unittest.main()
