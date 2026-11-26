"""Nulavio Shell built-in add-on: manifest, privacy, i18n and packaging."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import make_shell  # noqa: E402

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
    objects and brackets included, and a bracket inside a string literal not counted."""
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

    def test_the_function_opens_a_new_tab_before_it_removes_the_page_and_says_when_it_cannot(self):
        text = (SHELL / "lib" / "tabs.js").read_text(encoding="utf-8")
        body = text[text.index("export async function closeOwnTab(") :]
        body = body[: body.index("\n}\n")]
        self.assertLess(body.index("browser.tabs.create({ windowId: tab.windowId })"), body.index("browser.tabs.remove(tab.id)"))
        self.assertIn('failed(t("tabCloseFailed"))', body.split("catch", 1)[1])
        self.assertNotIn("about:", body)
        # Only visible tabs count, as in the engine's own last-tab check (#720).
        self.assertIn("browser.tabs.query({ windowId: tab.windowId, hidden: false })", body)
        # A second click while the tab closes does nothing; a failure lets the page try again.
        self.assertLess(body.index("if (closing) {"), body.index("browser.tabs.getCurrent()"))
        self.assertLess(body.index("closing = true;"), body.index("try {"))
        self.assertIn("closing = false;", body.split("catch", 1)[1])
        for name in ("en", "pt_BR"):
            self.assertIn("tabCloseFailed", locale(name))

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
        self.assertIn("this.manager.documentURI", parent)  # the address comes from the engine
        self.assertNotIn("message.data", parent)
        self.assertNotIn("content_scripts", make_shell.manifest())

    def test_the_warning_page_names_only_what_the_module_finds(self):
        """The look-alike warning is opened with the site's address only; the passwords module finds the saved site
        it imitates again, and "continue" remembers the pair the module finds, not one the page names."""
        parent = module_text("NulavioLookalikeParent.sys.mjs")
        self.assertIn("new URLSearchParams({ url })", parent)
        page = (SHELL / "passwords" / "lookalike.js").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'params\.get\("(\w+)"\)', page), ["url"])
        self.assertIn("browser.nulavioPasswords.check(url.href)", page)
        self.assertIn("browser.nulavioPasswords.dismiss(url.href)", page)
        # One title whether or not the module finds a pair: another extension reads a tab's title.
        self.assertNotIn("document.title", page)
        schema = json.loads((SHELL / "experiments" / "passwords" / "schema.json").read_text(encoding="utf-8"))[0]
        params = {f["name"]: [p["name"] for p in f["parameters"]] for f in schema["functions"]}
        self.assertEqual((params["check"], params["dismiss"]), (["url"], ["url"]))


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


if __name__ == "__main__":
    unittest.main()
