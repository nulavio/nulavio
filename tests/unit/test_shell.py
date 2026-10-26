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


MODULES = SHELL / "modules"


def module_text(name: str) -> str:
    return (MODULES / name).read_text(encoding="utf-8")


class PrivilegedApiTest(unittest.TestCase):
    """The Shell's experiment APIs: what they reach, and nothing more."""

    def setUp(self):
        self.manifest = make_shell.manifest()

    def test_only_the_two_documented_apis(self):
        apis = self.manifest["experiment_apis"]
        self.assertEqual(set(apis), {"nulavioSearch", "nulavioProfiles", "nulavioRouting"})
        for name, api in apis.items():
            with self.subTest(api=name):
                self.assertEqual(api["parent"]["scopes"], ["addon_parent"], "no API code runs in content processes")
                self.assertEqual(api["parent"]["paths"], [[name]])
                self.assertNotIn("child", api)
                self.assertTrue((SHELL / api["parent"]["script"]).is_file())
                schema = json.loads((SHELL / api["schema"]).read_text(encoding="utf-8"))
                self.assertEqual([ns["namespace"] for ns in schema], [name])
        self.assertEqual(apis["nulavioSearch"]["parent"]["events"], ["startup"])
        self.assertNotIn("events", apis["nulavioProfiles"]["parent"])
        self.assertNotIn("events", apis["nulavioRouting"]["parent"])

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

    def test_profile_selector_is_on_the_toolbar_with_a_shortcut(self):
        self.assertEqual(self.manifest["action"]["default_area"], "navbar")
        self.assertEqual(self.manifest["action"]["default_popup"], "profiles/popup.html")
        self.assertEqual(self.manifest["commands"]["_execute_action"]["suggested_key"]["default"], "Alt+Shift+P")

    def test_every_module_error_has_a_message(self):
        en = locale("en")
        text = "".join(module_text(n.name) for n in MODULES.glob("*.sys.mjs"))
        codes = set(re.findall(r'fail\("([a-z-]+)"', text)) | {"disabled", "unregistered", "unexpected"}
        for code in codes:
            self.assertIn(f"err_{code.replace('-', '_')}", en, code)


class SearchProvidersTest(unittest.TestCase):
    """docs/adr/0002-nulavio-search.md: who search goes to, and when."""

    def setUp(self):
        self.text = module_text("NulavioSearch.sys.mjs")
        block = self.text[self.text.index("export const PROVIDERS") : self.text.index("export class SearchSettingsError")]
        self.providers = {
            key: dict(re.findall(r'(\w+): ("[^"]*"|null|true|false)', body))
            for key, body in re.findall(r"(\w+): Object\.freeze\(\{(.*?)\}\)", block, re.S)
        }

    def test_curated_providers(self):
        self.assertEqual(set(self.providers), {"duckduckgo", "brave", "mojeek", "kagi"})
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


class ProfileTemplatesTest(unittest.TestCase):
    def setUp(self):
        self.text = module_text("NulavioProfiles.sys.mjs")

    def listed(self, name: str) -> list[str]:
        block = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]\);", self.text, re.S).group(1)
        return re.findall(r'"([a-z-]+)"', block)

    def test_templates_use_offered_icons_and_colours(self):
        avatars, colors = set(self.listed("AVATARS")), set(self.listed("COLORS"))
        templates = re.findall(r'id: "(\w+)", avatar: "([a-z-]+)", color: "(\w+)"', self.text)
        self.assertEqual([t[0] for t in templates], ["personal", "work", "banking", "research"])
        for template_id, avatar, color in templates:
            with self.subTest(template=template_id):
                self.assertIn(avatar, avatars)
                self.assertIn(color, colors)
        names = (SHELL / "lib" / "names.js").read_text(encoding="utf-8")
        for template_id, *_ in templates:
            key = re.search(rf'{template_id}: "(\w+)"', names).group(1)
            self.assertIn(key, locale("en"))

    def test_no_temporary_profile_until_it_exists(self):
        self.assertNotIn("temporary", [t for t in self.listed("TEMPLATES")])
        self.assertNotRegex(self.text, r'id: "temporary"')

    def test_colours_are_design_tokens(self):
        tokens = json.loads((ROOT / "docs" / "brand" / "tokens.json").read_text(encoding="utf-8"))
        for theme in ("light", "dark"):
            self.assertEqual(set(self.listed("COLORS")) | {"on"}, set(tokens["color"][theme]["identity"]) - {"$description"})
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
        for key in ("experiment_apis", "action", "commands", "options_ui"):
            self.assertNotIn(key, manifest)
        self.assertFalse([f for f in files if f.split("/")[0] in ("experiments", "modules", "settings", "profiles", "routing")])
        self.assertIn("newtab/newtab.html", files)
        self.assertEqual(manifest["permissions"], make_shell.manifest()["permissions"])

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


if __name__ == "__main__":
    unittest.main()
