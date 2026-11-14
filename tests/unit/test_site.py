"""nulavio.net: static pages with no scripts or third parties, strict headers, honest copy, and the waitlist."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "site"))
sys.path.insert(0, str(ROOT / "scripts" / "brand"))

import build_site  # noqa: E402
import verify_live  # noqa: E402
from contrast import ratio  # noqa: E402

# The landing (what Nulavio is at launch, the comparison, the waitlist form), the waitlist pages, the
# link page a sign-up is answered with (site/_worker.js serves it with the key in its address) and
# the engineering document ("Recibo": what is ready today, with captures and excerpts from the tree).
LANDING = {"index.html": "pt-BR", "en/index.html": "en-US"}
WAITLIST = {"lista/index.html": "pt-BR", "en/waitlist/index.html": "en-US"}
LINK = {"lista/link/index.html": "pt-BR", "en/waitlist/link/index.html": "en-US"}
DOCUMENT = {"engenharia/index.html": "pt-BR", "en/engineering/index.html": "en-US"}
PAGES = [*LANDING, *WAITLIST, *LINK, *DOCUMENT, "404.html"]
FORM_LANG = {"pt-BR": "pt-BR", "en-US": "en"}  # the page's locale -> the form's "lang" field
WORKER = ROOT / "site" / "_worker.js"
SAME_SITE = "https://nulavio.net/"
SHOTS = ROOT / "site" / "assets" / "shots"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.data = tag, dict(attrs), parent, [], []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class Tree(HTMLParser):
    """A small DOM: enough to check structure (headings, figures, tables, alt text) without a browser."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", [], None)
        self.current = self.root
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)

    def all(self, tag=None):
        return [n for n in self.root.walk() if tag is None or n.tag == tag]


def tokens(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """Light (:root) and dark (prefers-color-scheme: dark) values of the colour tokens in tokens.css."""
    light = dict(re.findall(r"(--nv-color-[\w-]+):\s*(#[0-9A-Fa-f]{6})", css.split("@media")[0]))
    dark_block = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{(.*?)\n\}", css, re.S).group(1)
    dark = {**light, **dict(re.findall(r"(--nv-color-[\w-]+):\s*(#[0-9A-Fa-f]{6})", dark_block))}
    return light, dark


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "site"
        cls.files = set(build_site.build(cls.out))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_pages_are_static_and_first_party(self):
        for page in PAGES:
            html = (self.out / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertRegex(html, r'<html lang="(pt-BR|en)"')
                self.assertIn("<title>", html)
                self.assertNotIn("<script", html)
                self.assertNotIn("style=", html)
                self.assertNotRegex(html, r"\bon[a-z]+=", "inline event handler")
                for url in re.findall(r'(?:src|href|srcset)="(https?://[^"]+)"', html):
                    self.assertTrue(url.startswith(SAME_SITE), f"third-party resource {url}")

    def test_addresses_are_kept_from_email_obfuscation(self):
        """Every page opts out of Cloudflare's address rewriting, which adds a script the site's policy blocks."""
        opened, closed = build_site.EMAIL_OFF
        for page in sorted(f for f in self.files if f.endswith(".html")):
            html = (self.out / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertEqual((html.count(opened), html.count(closed)), (1, 1))
                self.assertIn(f"<body>\n{opened}\n", html)
                self.assertIn(f"\n{closed}\n</body>", html)
                inside = html[html.index(opened) : html.index(closed)]
                self.assertEqual(html.count("@nulavio.net"), inside.count("@nulavio.net"), "an address outside the opt-out")
        # The security address is on the engineering pages since the landing (#16); it must reach them intact.
        for page in ("engenharia/index.html", "en/engineering/index.html"):
            self.assertIn("mailto:security@nulavio.net", (self.out / page).read_text(encoding="utf-8"))

    def test_local_references_resolve(self):
        for page in PAGES:
            html = (self.out / page).read_text(encoding="utf-8")
            for ref in re.findall(r'(?:src|href|srcset)="(/[^"]*)"', html):
                target = ref.lstrip("/").partition("#")[0]
                with self.subTest(page=page, ref=ref):
                    if not target or target.endswith("/"):
                        self.assertIn(f"{target}index.html", self.files)
                    else:
                        self.assertIn(target, self.files)

    def test_security_headers(self):
        headers = (self.out / "_headers").read_text(encoding="utf-8")
        csp = re.search(r"Content-Security-Policy: (.+)", headers).group(1)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe", csp)
        self.assertNotIn("script-src", csp, "the site has no scripts to allow")
        self.assertIn("form-action 'self'", csp, "the waitlist forms post to this origin and nowhere else")
        self.assertIn("Referrer-Policy: no-referrer", headers)
        self.assertIn("X-Content-Type-Options: nosniff", headers)
        self.assertRegex(headers, r"Strict-Transport-Security: max-age=\d+")
        self.assertNotIn("preload", headers, "HSTS preload is hard to undo; decide it explicitly")

    def test_security_txt(self):
        import datetime as dt

        self.assertIn(".well-known/security.txt", self.files)
        fields = {}
        for line in (self.out / ".well-known" / "security.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition(": ")
                fields[key] = value
        self.assertEqual(fields["Contact"], "mailto:security@nulavio.net")
        self.assertEqual(fields["Canonical"], "https://nulavio.net/.well-known/security.txt")
        expires = dt.datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00"))
        now = dt.datetime.now(dt.UTC)
        self.assertGreater(expires, now, "security.txt expired: renew it (RFC 9116)")
        self.assertLess(expires - now, dt.timedelta(days=366), "RFC 9116 recommends less than a year")

    def test_copy_is_honest(self):
        for pages in (LANDING, DOCUMENT):
            pt, en = (self.read(page) for page in pages)
            self.assertIn("não é afiliado à Mozilla", pt)
            self.assertIn("not affiliated with Mozilla", en)
        pt, en = (self.read(page) for page in DOCUMENT)
        self.assertIn("Em desenvolvimento", pt)
        self.assertIn("In development", en)
        # The landing sells the launch, and still says what a browser cannot do: no anonymity
        # (Tor Browser's job), and one trade-off in plain words under every feature.
        pt, en = (self.read(page) for page in LANDING)
        self.assertIn("use o Tor Browser", pt)
        self.assertIn("use Tor Browser", en)
        for page, label in (("index.html", "Sem letra miúda:"), ("en/index.html", "No fine print:")):
            tree = self.tree(page)
            features = [n for n in tree.all("section") if "feature" in n.classes()]
            self.assertGreaterEqual(len(features), 5)
            for feature in features:
                fine = [n for n in feature.walk() if "fine" in n.classes()]
                self.assertEqual(len(fine), 1, feature.attrs)
                self.assertIn(label, fine[0].text())
        # Selling the launch stops where the download starts: what the published alpha does not
        # have yet is marked as coming, and the compatibility figure says when it was measured
        # (frontend audit N-01, N-04).
        for page, soon, when, packages in (
            ("index.html", "Em breve", "outubro de 2026", "Pacotes assinados para Fedora e Ubuntu"),
            ("en/index.html", "Coming soon", "October 2026", "Signed packages for Fedora and Ubuntu"),
        ):
            with self.subTest(page=page):
                tree = self.tree(page)
                unlock = next(n for n in tree.all("ul") if "unlock" in n.classes())
                methods = [n.text() for n in unlock.walk() if n.tag == "li"]
                coming = [m for m in methods if "FIDO2" in m or "biometr" in m]
                self.assertEqual(len(coming), 2, methods)
                self.assertTrue(all(soon in m for m in coming), coming)
                for node in tree.all():
                    if node.tag in ("p", "td") and "FIDO2" in node.text():
                        self.assertRegex(node.text(), f"(?i){soon}", node.text())
                figure = next(n.text() for n in tree.all("dt") if "50" in n.parent.text() and "sites" in n.text())
                self.assertIn(when, figure)
                self.assertNotIn(packages, self.read(page))
        absolute = re.compile(r"(?i)\b(100\s?%|unhackable|imune|immune|totalmente seguro|completely secure|garantid|guarantee)")
        for page in PAGES:
            self.assertIsNone(absolute.search((self.out / page).read_text(encoding="utf-8")), page)

    # -- landing page structure (spec §7, §9) ---------------------------------------------

    def read(self, page: str) -> str:
        return (self.out / page).read_text(encoding="utf-8")

    def tree(self, page: str) -> Tree:
        return Tree(self.read(page))

    def test_no_placeholder_is_left(self):
        for page in PAGES:
            self.assertNotIn("{{", self.read(page), page)

    def test_both_languages_have_the_same_ids(self):
        for pages in (LANDING, WAITLIST, LINK, DOCUMENT):
            ids = {page: [n.attrs["id"] for n in self.tree(page).all() if "id" in n.attrs] for page in pages}
            pt, en = ids.values()
            with self.subTest(pages=list(pages)):
                self.assertEqual(len(pt), len(set(pt)), "duplicate ids")
                self.assertEqual(pt, en)

    def test_one_h1_and_heading_levels_do_not_skip(self):
        for page in PAGES:
            levels = [int(level) for level in re.findall(r"<h([1-6])\b", self.read(page))]
            with self.subTest(page=page):
                self.assertEqual(levels.count(1), 1)
                self.assertEqual(levels[0], 1)
                for before, after in itertools.pairwise(levels):
                    self.assertLessEqual(after, before + 1, levels)

    def test_images_have_alt_text(self):
        for page in PAGES:
            tree = self.tree(page)
            # Decorative: the sign-off symbol, and what sits inside a drawing that is one image with its own label.
            drawings = [n for n in tree.all() if n.attrs.get("role") == "img" and n.tag != "svg"]
            around = [*drawings, *(n for n in tree.all() if n.attrs.get("id") == "signoff")]
            decorative = {id(n) for parent in around for n in parent.walk()}
            for img in tree.all("img"):
                with self.subTest(page=page, src=img.attrs.get("src")):
                    self.assertIn("alt", img.attrs)
                    if id(img) in decorative:
                        self.assertEqual(img.attrs["alt"], "", "decorative: the label is on the drawing around it")
                    else:
                        self.assertTrue(img.attrs["alt"].strip())

    def test_figures_tables_and_scroll_regions_are_labelled(self):
        for page in (*LANDING, *WAITLIST, *LINK, *DOCUMENT):
            tree = self.tree(page)
            with self.subTest(page=page):
                figures = tree.all("figure")
                if page in DOCUMENT:
                    self.assertGreaterEqual(len(figures), 5)
                for figure in figures:
                    self.assertTrue(any(n.tag == "figcaption" for n in figure.walk()), figure.attrs)
                for table in tree.all("table"):
                    self.assertTrue(any(n.tag == "caption" for n in table.walk()))
                    for th in (n for n in table.walk() if n.tag == "th"):
                        self.assertIn(th.attrs.get("scope"), ("col", "row"), th.text())
                for node in tree.all():
                    if node.attrs.get("tabindex") == "0":
                        self.assertTrue(node.attrs.get("aria-label") or node.attrs.get("aria-labelledby"), node.attrs)
                    if node.attrs.get("role") == "img" and node.tag != "svg":
                        # a drawing of the interface made of HTML: one image, described in a sentence or more
                        self.assertGreater(len(node.attrs.get("aria-label", "")), 60, node.attrs)
                for svg in (n for n in tree.all("svg") if n.attrs.get("role") == "img"):
                    # the <title> is the name and the <desc> the description: never one long name
                    for attr, kind in (("aria-labelledby", "title"), ("aria-describedby", "desc")):
                        ids = svg.attrs.get(attr, "").split()
                        kinds = [n.tag for n in svg.walk() if n.attrs.get("id") in ids]
                        self.assertEqual(kinds, [kind], (attr, svg.attrs))

    def test_shots_match_the_manifest_and_transcripts_are_on_the_page(self):
        manifest = json.loads((SHOTS / "manifest.json").read_text(encoding="utf-8"))
        entries = {f["file"]: f for f in manifest["files"]}
        self.assertNotIn(str(Path.home()), json.dumps(manifest), "the manifest must not hold personal paths")
        for shot in sorted(SHOTS.glob("*.webp")):
            with self.subTest(shot=shot.name):
                self.assertIn(shot.name, entries)
                self.assertEqual(hashlib.sha256(shot.read_bytes()).hexdigest(), entries[shot.name]["sha256"])
        for page, locale in DOCUMENT.items():
            tree = self.tree(page)
            onscreen = [" ".join(n.text().split()) for n in tree.all() if "onscreen" in n.classes()]
            used = set(re.findall(r'/assets/shots/([^"]+)', self.read(page)))
            for name in used:
                self.assertIn(name, entries, f"{page} uses a shot that is not in the manifest")
            for key, by_locale in manifest["figures"].items():
                transcript = by_locale.get(locale, {}).get("transcript")
                if transcript and any(key in n or entries[n].get("figure") == key for n in used):
                    with self.subTest(page=page, figure=key):
                        self.assertIn(" ".join(transcript.split()), onscreen)

    def test_excerpts_are_generated_from_the_tree(self):
        headers = (ROOT / "site" / "_headers").read_text(encoding="utf-8")
        e1 = build_site.excerpt_e1(ROOT)
        for page in DOCUMENT:
            tree = self.tree(page)
            pres = {n.parent.attrs.get("aria-label"): n.text() for n in tree.all("pre")}
            with self.subTest(page=page):
                e2 = next(text for label, text in pres.items() if "_headers" in (label or ""))
                lines = [line for line in e2.splitlines() if line.strip()]
                self.assertGreaterEqual(len(lines), 5)
                for line in lines:
                    self.assertIn(line, headers)
                self.assertIn(e1, pres.values(), "E1 must be the command's own output at this tree")

    def test_contrast_pairs_from_the_tokens(self):
        light, dark = tokens((ROOT / "browser" / "startpage" / "tokens.css").read_text(encoding="utf-8"))
        text_pairs = [("text-primary", "bg-canvas"), ("text-primary", "bg-sunken"), ("text-primary", "bg-surface")]
        text_pairs += [("text-secondary", bg) for bg in ("bg-canvas", "bg-surface", "bg-sunken")]
        text_pairs += [("text-muted", "bg-canvas")]  # the revision line sits on the canvas only
        text_pairs += [("status-warning", bg) for bg in ("bg-canvas", "bg-surface", "bg-sunken")]
        border_pairs = [("border-control", bg) for bg in ("bg-canvas", "bg-surface", "bg-sunken")]
        border_pairs += [("focus", "bg-canvas"), ("focus", "bg-sunken")]
        # The landing (site/landing.css). Text: buttons, the Nulavio column of the comparison, the
        # notices, the mock-ups' own chrome. Icons, large type and control edges need 3:1.
        text_pairs += [("accent-on", "accent-default"), ("text-muted", "bg-surface")]
        tinted = ("accent-tint", "status-warningTint", "bg-raised")
        text_pairs += [(fg, bg) for fg in ("text-primary", "text-secondary") for bg in tinted]
        text_pairs += [("security-guard-text", "security-guard-fill"), ("status-criticalText", "bg-surface")]
        text_pairs += [("band-text", "band-bg"), ("band-meta", "band-bg"), ("control-selected-text", "control-selected-fill")]
        text_pairs += [(f"identityGlyph-{hue}", f"identityTile-{hue}") for hue in ("lima", "sky", "sand", "violet")]
        border_pairs += [("accent-default", bg) for bg in ("bg-canvas", "bg-surface", "bg-sunken", "accent-tint")]
        border_pairs += [("status-warning", "accent-tint"), ("text-muted", "accent-tint"), ("status-critical", "bg-surface")]
        border_pairs += [("control-selected-edge", "bg-sunken"), ("security-temporary-edge", "bg-canvas")]
        for scheme, values in (("light", light), ("dark", dark)):
            for pairs, minimum in ((text_pairs, 4.5), (border_pairs, 3.0)):
                for fg, bg in pairs:
                    with self.subTest(scheme=scheme, fg=fg, bg=bg):
                        value = ratio(values[f"--nv-color-{fg}"], values[f"--nv-color-{bg}"])
                        self.assertGreaterEqual(value, minimum)
        for sheet in build_site.STYLESHEETS:
            css = (ROOT / "site" / sheet).read_text(encoding="utf-8")
            self.assertNotRegex(css, r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", f"{sheet} takes every colour from the tokens")

    # -- landing and waitlist -------------------------------------------------------------

    def test_stamped_numbers_come_from_the_tree(self):
        prefs = (ROOT / "browser" / "config" / "prefs" / "baseline.js").read_text(encoding="utf-8")
        defaults = len(re.findall(r"^// @why ", prefs, re.M))
        self.assertEqual(build_site.default_count(ROOT), defaults, "every counted default is an annotated one")
        for page in LANDING:
            numbers = [n.text().strip() for n in self.tree(page).all("dd")]
            with self.subTest(page=page):
                self.assertIn(str(defaults), numbers)
                self.assertIn(f"uBlock Origin {build_site.ublock_version(ROOT)}", self.read(page))
                self.assertIn(f"Firefox {build_site.firefox_version(ROOT)}", self.read(page))

    def test_link_preview_image_is_ours_and_has_the_declared_size(self):
        for page in LANDING:
            html = self.read(page)
            image = re.search(r'<meta property="og:image" content="([^"]+)">', html).group(1)
            with self.subTest(page=page):
                self.assertTrue(image.startswith(SAME_SITE), image)
                data = (self.out / image.removeprefix(SAME_SITE)).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                size = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
                declared = tuple(
                    int(re.search(rf'og:image:{side}" content="(\d+)"', html).group(1)) for side in ("width", "height")
                )
                self.assertEqual(size, declared)

    def test_waitlist_forms_post_to_this_origin(self):
        accepted = re.search(r"PLATFORMS = new Set\(\[(.*?)\]\)", WORKER.read_text(encoding="utf-8")).group(1)
        platforms = set(accepted.replace('"', "").split(", "))
        for page, locale in {**LANDING, **WAITLIST}.items():
            tree = self.tree(page)
            forms = tree.all("form")
            with self.subTest(page=page):
                self.assertEqual(len(forms), 2 if page in LANDING else 1)  # the landing asks twice; nothing leaves by address
                labelled = {n.attrs.get("for") for n in tree.all("label")}
                for form in forms:
                    self.assertEqual((form.attrs.get("action"), form.attrs.get("method")), ("/api/waitlist", "post"))
                    fields = {n.attrs.get("name"): n for n in form.walk() if n.tag in ("input", "select")}
                    self.assertNotIn("action", fields, "no form asks to leave by address")
                    self.assertEqual(fields["lang"].attrs.get("value"), FORM_LANG[locale])
                    self.assertEqual(fields["email"].attrs.get("type"), "email")
                    self.assertIn("required", fields["email"].attrs)
                    self.assertIn(fields["email"].attrs["id"], labelled, "a visible label, not only a placeholder")
                    self.assertEqual(fields["hp"].attrs.get("tabindex"), "-1", "the honeypot is out of the tab order")
                    if "platform" in fields:
                        self.assertIn(fields["platform"].attrs["id"], labelled)
                        options = {n.attrs.get("value") for n in fields["platform"].walk() if n.tag == "option"}
                        self.assertEqual(options, platforms, "the worker accepts exactly the platforms the form offers")
                    self.assertTrue(any(n.tag == "button" and n.attrs.get("type") == "submit" for n in form.walk()))

    def test_waitlist_pages_answer_every_state_of_the_worker(self):
        worker = WORKER.read_text(encoding="utf-8")
        states = set(re.findall(r'redirect\(lang, "(\w+)"\)', worker))
        self.assertEqual(states, {"left", "invalid", "unavailable", "nolink", "leave"})
        targets = dict(re.findall(r'"?([\w-]+)"?: "(/[\w/]+/)"', re.search(r"const PAGES = \{(.*?)\}", worker).group(1)))
        self.assertEqual(targets, {"pt-BR": "/lista/", "en": "/en/waitlist/"})
        for (page, _locale), target in zip(WAITLIST.items(), (targets["pt-BR"], targets["en"]), strict=True):
            tree = self.tree(page)
            with self.subTest(page=page):
                self.assertEqual(target.strip("/") + "/index.html", page)
                notices = {n.attrs.get("id") for n in tree.all() if "notice" in n.classes()}
                self.assertEqual(notices, states - {"leave"}, "one message for each answer of site/_worker.js")
                ids = {n.attrs.get("id") for n in tree.all()}
                self.assertLessEqual({"data", "leave"}, ids, "what is kept and how to leave, linked from the landing")
                self.assertIn("SHA-256", self.read(page), "what is kept names the fingerprint of the link")
        css = (ROOT / "site" / "landing.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.notice \{[^}]*display: none", "a message shows only when its fragment is the target")
        self.assertIn(".notice:target", css)

    def test_the_link_page_is_one_form_that_posts_to_its_own_address(self):
        """What a sign-up is answered with: the worker serves it with the key in the address (?k=…), and
        the key is nowhere in the page. A form with no action posts to the address it is on."""
        worker = WORKER.read_text(encoding="utf-8")
        targets = dict(re.findall(r'"?([\w-]+)"?: "(/[\w/]+/)"', re.search(r"const LINKS = \{(.*?)\}", worker).group(1)))
        self.assertEqual([path.strip("/") + "/index.html" for path in targets.values()], list(LINK))
        for page in LINK:
            tree, html = self.tree(page), self.read(page)
            with self.subTest(page=page):
                (form,) = tree.all("form")
                self.assertEqual(form.attrs.get("method"), "post")
                self.assertNotIn("action", form.attrs)
                fields = {n.attrs.get("name"): n for n in form.walk() if n.tag in ("input", "select")}
                # Nothing is typed here: the address is the proof. One hidden field, so that the form
                # has a body; no honeypot, which would tell a person "done" and delete nothing.
                self.assertEqual({name: n.attrs.get("type") for name, n in fields.items()}, {"leave": "hidden"})
                self.assertTrue(any(n.tag == "button" and n.attrs.get("type") == "submit" for n in form.walk()))
                self.assertIn('<meta name="robots" content="noindex">', html)
                self.assertNotIn('rel="canonical"', html)
                self.assertEqual(
                    re.findall(r'(?:href|src|action)="[^"]*[?&]k=', html), [], "no link out of the page carries a key"
                )
                # The other language's page would need the key, and no page has a script to carry it.
                self.assertEqual([n for n in tree.all("a") if n.attrs.get("hreflang")], [])
                shown = [n for n in tree.all() if "notice" in n.classes()]
                self.assertEqual(
                    [n.classes() >= {"notice-on"} for n in shown], [True], "its message does not wait for a fragment"
                )
                self.assertIn("mailto:security@nulavio.net", html, "what to do when the link is lost")
        self.assertRegex((ROOT / "site" / "landing.css").read_text(encoding="utf-8"), r"\.notice-on \{ display: block; \}")

    def test_only_the_api_and_the_link_pages_reach_the_worker(self):
        routes = json.loads((self.out / "_routes.json").read_text(encoding="utf-8"))
        self.assertEqual(routes, {"version": 1, "include": ["/api/*", "/lista/link/", "/en/waitlist/link/"], "exclude": []})
        self.assertIn("_worker.js", self.files)
        for page in PAGES:
            loads = re.findall(r'(?:src|href)="[^"]*_worker[^"]*"', self.read(page))
            self.assertEqual(loads, [], f"{page}: no page loads the worker, it is server code")

    def test_comparison_names_the_browsers_and_its_date(self):
        for page in LANDING:
            tables = self.tree(page).all("table")
            with self.subTest(page=page):
                self.assertEqual(len(tables), 1)
                columns = [n.text().strip() for n in tables[0].walk() if n.tag == "th" and n.attrs.get("scope") == "col"]
                self.assertEqual(columns[1:], ["Nulavio", "Brave", "LibreWolf", "Mullvad Browser", "Tor Browser"])
                body = next(n for n in tables[0].walk() if n.tag == "tbody")
                for row in (n for n in body.walk() if n.tag == "tr"):
                    cells = [c for c in row.children if isinstance(c, Node) and c.tag == "td"]
                    self.assertEqual(len(cells), 5, row.text())
                    self.assertTrue(all(c.text().strip() for c in cells), "every cell says something in words, not only an icon")
                self.assertRegex(self.read(page), r"(novembro de|November) 20\d\d", "the comparison says when it was made")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class WaitlistWorkerTest(unittest.TestCase):
    """site/_worker.js: what it answers (tests/lib/waitlist_worker_driver.mjs) and what its SQL does in SQLite."""

    LINK_RE = r"^/(lista|en/waitlist)/link/\?k=([A-Za-z0-9_-]{43})$"

    @classmethod
    def setUpClass(cls):
        driver = ROOT / "tests" / "lib" / "waitlist_worker_driver.mjs"
        done = subprocess.run(["node", str(driver), str(WORKER)], capture_output=True, text=True, timeout=60, check=True)
        cls.cases = json.loads(done.stdout)

    def database(self, *names: str, before: tuple[str, ...] = ()) -> sqlite3.Connection:
        """SQLite (what D1 runs) after `before` and then the statements of these cases, in order."""
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        for sql in before:
            db.execute(sql)
        for name in names:
            self.replay(db, name)
        return db

    def replay(self, db: sqlite3.Connection, name: str) -> None:
        for statement in self.cases[name]["statements"]:
            db.execute(statement["sql"], statement["args"])

    @staticmethod
    def entries(db: sqlite3.Connection) -> list[tuple]:
        return db.execute("SELECT email, lang, platform, joined FROM waitlist ORDER BY joined, email").fetchall()

    @staticmethod
    def links(db: sqlite3.Connection) -> dict[str, str]:
        return dict(db.execute("SELECT email, link FROM waitlist_links").fetchall())

    def key(self, name: str) -> str:
        """The key in the link a sign-up was answered with."""
        return re.match(self.LINK_RE, self.cases[name]["location"]).group(2)

    @staticmethod
    def kept(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def test_join_keeps_the_address_the_language_the_platform_and_the_time(self):
        join = self.cases["join"]
        self.assertEqual(join["status"], 303)
        self.assertRegex(join["location"], r"^/lista/link/\?k=[A-Za-z0-9_-]{43}$")
        db = self.database("join")
        ((email, lang, platform, joined),) = self.entries(db)
        self.assertEqual((email, lang, platform), ("Ana@Example.org", "pt-BR", "fedora"))
        self.assertRegex(joined, r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        (insert,) = [s for s in join["statements"] if s["sql"].startswith("INSERT INTO waitlist ")]
        self.assertEqual(len(insert["args"]), 4, "nothing else is stored: no IP, no user agent")
        # Of the link, only the SHA-256 of its key; the key itself is in the answer and nowhere else.
        self.assertEqual(self.links(db), {"Ana@Example.org": self.kept(self.key("join"))})
        self.assertNotIn(self.key("join"), json.dumps(join["statements"]))

    def test_joining_twice_changes_nothing_and_gives_a_link_that_opens_nothing(self):
        first, again = self.database("join"), self.database("join", "join_again_other_case")
        self.assertEqual(self.entries(again), self.entries(first), "not the date, the language or the platform")
        self.assertEqual(self.links(again), self.links(first), "the first link stays the one that works")
        # The answer has the same shape, with a key of its own: the form does not tell who is on the list.
        self.assertRegex(self.cases["join_again_other_case"]["location"], r"^/en/waitlist/link/\?k=[A-Za-z0-9_-]{43}$")
        self.assertNotEqual(self.key("join_again_other_case"), self.key("join"))
        self.assertEqual(
            [s["sql"] for s in self.cases["join_again_other_case"]["statements"]],
            [s["sql"] for s in self.cases["join"]["statements"]],
        )
        after = self.database("join", "join_again_other_case", "leave_with_the_second_link")
        self.assertEqual((self.entries(after), self.links(after)), (self.entries(first), self.links(first)))

    def test_a_request_is_one_transaction_that_always_writes(self):
        # One batch: the fingerprint is recorded only for an address that is not on the list, which
        # holds for two sign-ups at once because the check and the sign-up cannot be told apart.
        for name in ("join", "join_again_other_case", "leave", "leave_unknown_link"):
            case = self.cases[name]
            kinds = [s["sql"].split("(")[0].strip() for s in case["statements"]]
            with self.subTest(case=name):
                self.assertEqual(case["batches"], 1)
                self.assertTrue(all(kind.startswith("CREATE TABLE IF NOT EXISTS") for kind in kinds[:3]), kinds)
                # The last statement rewrites one row with a new random number whatever was found, so
                # that a request that changes nothing does not answer sooner than one that does.
                pulse = case["statements"][-1]
                self.assertEqual(pulse["sql"], "INSERT OR REPLACE INTO waitlist_pulse (id, n) VALUES (1, ?1)")
                self.assertRegex(pulse["args"][0], r"^[A-Za-z0-9_-]{43}$")
        order = [s["sql"] for s in self.cases["join"]["statements"]]
        link, join = (
            next(i for i, sql in enumerate(order) if sql.startswith(start))
            for start in ("INSERT OR REPLACE INTO waitlist_links", "INSERT INTO waitlist ")
        )
        self.assertLess(link, join, "the fingerprint is decided before the sign-up exists")
        pulses = {self.cases[name]["statements"][-1]["args"][0] for name in ("join", "join_again_other_case", "leave")}
        self.assertEqual(len(pulses), 3, "a new number each time: rewriting the same bytes is no write")
        db = self.database("join", "join_again_other_case", "leave")
        self.assertEqual(db.execute("SELECT count(*) FROM waitlist_pulse").fetchone(), (1,), "one row, about nobody")

    def test_leaving_takes_the_link_and_answers_the_same_for_any_key(self):
        # LESIS 3c38916e: POST action=leave with an address deleted its entry, with no proof asked.
        by_address = self.cases["leave_by_address"]
        self.assertEqual(
            (by_address["status"], by_address["location"], by_address["statements"]), (303, "/en/waitlist/#leave", [])
        )
        db = self.database("join", "join_unknown_platform", "leave_unknown_link")
        self.assertEqual(len(self.entries(db)), 2)
        self.replay(db, "leave")
        self.assertEqual([email for email, *_ in self.entries(db)], ["bruno@example.org"])
        self.assertEqual(list(self.links(db)), ["bruno@example.org"], "the fingerprint goes with the entry")
        self.assertEqual(self.cases["leave"]["location"], "/lista/#left")
        self.assertEqual(self.cases["leave_unknown_link"]["location"], "/en/waitlist/#left")
        self.assertEqual(self.cases["leave_with_the_second_link"]["location"], "/en/waitlist/#left")
        for name in ("leave", "leave_unknown_link"):
            statements = [s for s in self.cases[name]["statements"] if s["sql"].startswith("DELETE")]
            args = [arg for statement in statements for arg in statement["args"]]
            self.assertEqual(len(statements), 2)
            self.assertTrue(args and all(re.fullmatch(r"[0-9a-f]{64}", arg) for arg in args), "the database sees the hash only")
            self.assertNotIn(self.cases[name]["location"], json.dumps(self.cases[name]["statements"]))

    def test_an_entry_from_before_links_gets_none_from_a_second_sign_up(self):
        # Otherwise anyone who knows an address on the old list would sign it up again and leave with the new link.
        join = next(
            s["sql"] for s in self.cases["join"]["statements"] if s["sql"].startswith("CREATE TABLE IF NOT EXISTS waitlist (")
        )
        old = "INSERT INTO waitlist VALUES ('ana@example.org', 'pt-BR', '', '2026-11-09T12:00:00Z')"
        db = self.database("join_again_other_case", "leave_with_the_second_link", before=(join, old))
        self.assertEqual(self.entries(db), [("ana@example.org", "pt-BR", "", "2026-11-09T12:00:00Z")])
        self.assertEqual(self.links(db), {})

    def test_an_entry_removed_by_hand_can_sign_up_again(self):
        db = self.database("join")
        db.execute("DELETE FROM waitlist")  # the maintainer, for someone who lost the link; the fingerprint was left behind
        self.replay(db, "join_again_other_case")
        self.assertEqual(self.links(db), {"ana@example.org": self.kept(self.key("join_again_other_case"))})
        self.replay(db, "leave_with_the_second_link")
        self.assertEqual((self.entries(db), self.links(db)), ([], {}))

    def test_the_link_page_is_the_static_page_whatever_the_key(self):
        for name, body in (("link_page", "the link page, pt-BR"), ("link_page_en", "the link page, en")):
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertEqual((case["status"], case["body"], case["statements"]), (200, body, []), "the list is not looked at")
                self.assertRegex(
                    case["files"][0], r"^GET https://nulavio\.net/(lista|en/waitlist)/link/$", "asked for without the key"
                )
        self.assertEqual((self.cases["link_page_head"]["status"], self.cases["link_page_head"]["body"]), (200, ""))
        for name, location in (("link_page_short_key", "/lista/#nolink"), ("link_page_no_key", "/en/waitlist/#nolink")):
            self.assertEqual((self.cases[name]["status"], self.cases[name]["location"]), (303, location))
        for name in ("link_page_no_files", "link_page_files_fail", "link_page_files_miss"):
            self.assertEqual(
                (self.cases[name]["status"], self.cases[name]["body"][:31]), (503, "This page could not be loaded. "), name
            )
        # The same path without its last slash also reaches the worker: it sends the browser to the
        # page's own address, and the static files never see a key.
        bare = self.cases["link_no_slash"]
        self.assertEqual((bare["status"], bare["location"], bare["files"]), (308, self.cases["join"]["location"], []))
        bare = self.cases["link_no_slash_no_key"]
        self.assertEqual((bare["status"], bare["location"], bare["files"]), (308, "/en/waitlist/link/", []))
        # A page of the site: the headers of site/_headers, and never stored or indexed (its address is a key).
        headers = self.cases["link_page"]["headers"]
        for name, value in verify_live.expected_headers(ROOT / "site").items():
            self.assertEqual(headers.get(name), value, name)
        self.assertEqual((headers["cache-control"], headers["x-robots-tag"]), ("no-store", "noindex"))
        self.assertTrue(headers["content-type"].startswith("text/html"))

    def test_values_are_bound_and_unknown_ones_fall_back(self):
        db = self.database("join", "join_unknown_platform", "unknown_lang")
        kept = {(email, lang, platform) for email, lang, platform, _ in self.entries(db)}
        self.assertEqual(
            kept, {("Ana@Example.org", "pt-BR", "fedora"), ("bruno@example.org", "en", ""), ("carla@example.org", "pt-BR", "")}
        )
        self.assertRegex(
            self.cases["unknown_lang"]["location"], r"^/lista/link/\?k=", "the redirect never follows the form's own text"
        )
        for case in self.cases.values():
            for statement in case["statements"]:
                self.assertNotIn("example.org", statement["sql"], "addresses travel as bound parameters")

    def test_what_is_refused_stores_nothing(self):
        expected = {
            "invalid_email": (303, "/en/waitlist/#invalid"),
            "no_dot_in_domain": (303, "/lista/#invalid"),
            "too_long_email": (303, "/lista/#invalid"),
            "cross_site": (403, None),
            "wrong_content_type": (415, None),
            "too_large": (413, None),
            "get": (405, None),
            "no_database": (303, "/en/waitlist/#unavailable"),
            "database_down": (303, "/lista/#unavailable"),
            "leave_short_key": (303, "/lista/#nolink"),
            "leave_cross_site": (403, None),
            "leave_wrong_content_type": (415, None),
            "leave_too_large": (413, None),
            "leave_put": (405, None),
            "leave_no_database": (303, "/en/waitlist/#unavailable"),
            "leave_database_down": (303, "/en/waitlist/#unavailable"),
        }
        for name, (status, location) in expected.items():
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertEqual((case["status"], case["location"]), (status, location))
                self.assertEqual(case["statements"], [])
        # A bot that fills the honeypot is told it worked, with a link like any other; nothing is kept.
        self.assertRegex(self.cases["honeypot"]["location"], r"^/en/waitlist/link/\?k=[A-Za-z0-9_-]{43}$")
        self.assertEqual(self.cases["honeypot"]["statements"], [])
        self.assertEqual(self.cases["get"]["headers"].get("allow"), "POST")
        self.assertEqual(self.cases["leave_put"]["headers"].get("allow"), "GET, HEAD, POST")
        self.assertRegex(self.cases["no_fetch_metadata"]["location"], self.LINK_RE, "an older browser still gets in")

    def test_answers_carry_their_own_headers(self):
        for name in ("join", "leave", "invalid_email", "cross_site", "get", "link_page_short_key"):
            headers = self.cases[name]["headers"]
            with self.subTest(case=name):
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertEqual(headers["referrer-policy"], "no-referrer")
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                self.assertIn("default-src 'none'", headers["content-security-policy"])

    def test_other_paths_fall_through_to_the_static_files(self):
        self.assertEqual((self.cases["other_api_path"]["status"], self.cases["other_api_path"]["body"]), (404, "the 404 page"))


class SiteWorkflowTest(unittest.TestCase):
    """.github/workflows/site.yml: only main deploys, and only the deploy step gets the token."""

    def setUp(self):
        self.text = (ROOT / ".github/workflows/site.yml").read_text(encoding="utf-8")
        self.deploy = self.text.split("\n  deploy:\n", 1)[1]

    def test_the_token_is_a_secret_of_the_site_environment_on_main(self):
        triggers = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertNotIn("pull_request", triggers)
        self.assertIn("if: ${{ github.ref == 'refs/heads/main' }}", self.deploy)
        self.assertIn("\n    environment: site\n", self.deploy)  # accepts only main; holds CLOUDFLARE_API_TOKEN (#182)

    def test_only_the_deploy_step_receives_the_token(self):
        self.assertEqual(self.text.count("secrets."), 1)
        step = self.deploy.split("- name: Deploy to Cloudflare Pages (production)\n", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}", step)


class VerifyLiveTest(unittest.TestCase):
    """scripts/site/verify_live.py, the check after a deploy (.github/workflows/site.yml), against a fake site."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dist = self.tmp / "site"
        build_site.build(self.dist)
        self.headers = verify_live.expected_headers(self.dist)
        self.served = {
            "https://nulavio.net/" + path: (dist_file, dict(self.headers)) for path, dist_file in verify_live.CHECKED.items()
        }

    def fetch(self, url):
        name, headers = self.served[url]
        return 200, headers, (self.dist / name).read_bytes()

    def test_headers_come_from_the_build(self):
        self.assertIn("content-security-policy", self.headers)
        self.assertEqual(self.headers["strict-transport-security"], "max-age=15552000; includeSubDomains")

    def test_the_build_as_built_passes(self):
        self.assertEqual(verify_live.problems(self.dist, "https://nulavio.net/", self.fetch), [])

    def test_an_older_page_or_a_missing_header_fails(self):
        def stale(url):
            status, headers, body = self.fetch(url)
            if url.endswith("/en/"):
                body = b"<!doctype html><title>old</title>"
            if url == "https://nulavio.net/":
                headers = {k: v for k, v in headers.items() if k != "content-security-policy"}
            return status, headers, body

        found = verify_live.problems(self.dist, "https://nulavio.net/", stale)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(any("/en/" in p and "bytes" in p for p in found), found)
        self.assertTrue(any("content-security-policy" in p for p in found), found)

    def test_an_error_status_fails(self):
        def missing(url):
            status, headers, body = self.fetch(url)
            return (404, headers, b"") if url.endswith("security.txt") else (status, headers, body)

        found = verify_live.problems(self.dist, "https://nulavio.net/", missing)
        self.assertEqual(found, ["https://nulavio.net/.well-known/security.txt: HTTP 404"])


def throwaway_key(home: Path) -> tuple[str, str]:
    """A signing key made for the test (no passphrase, never a release key): fingerprint and armored public key."""
    home.mkdir(mode=0o700)
    gpg = ["gpg", "--homedir", str(home), "--batch", "--quiet"]
    uid = "Throwaway <t@example.invalid>"
    subprocess.run([*gpg, "--passphrase", "", "--quick-generate-key", uid, "ed25519", "sign", "1d"], check=True)
    listing = subprocess.run([*gpg, "--with-colons", "--list-keys"], capture_output=True, text=True, check=True).stdout
    fpr = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
    armored = subprocess.run([*gpg, "--armor", "--export", fpr], capture_output=True, text=True, check=True).stdout
    return fpr, armored


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class DownloadPagesTest(unittest.TestCase):
    """The download pages appear only for a published release whose key is in the repository."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.fpr, cls.armored = throwaway_key(cls.tmp / "gnupg")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def source(self, name: str, version: str, fpr: str, key: str | None, apt: bool = False) -> Path:
        src = self.tmp / name
        (src / "packaging").mkdir(parents=True)
        release = json.loads((ROOT / "packaging" / "release.json").read_text(encoding="utf-8"))
        release.update(version=version, key_fingerprint=fpr)
        release.pop("apt_sources", None)
        if apt:
            release["apt_sources"] = "https://nulavio.net/apt/nulavio.sources"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        if key is not None:
            (src / build_site.PUBLIC_KEY).parent.mkdir(parents=True)
            (src / build_site.PUBLIC_KEY).write_text(key, encoding="utf-8")
        (src / build_site.REPO_FILE).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / build_site.REPO_FILE, src / build_site.REPO_FILE)
        if apt and key is not None:
            (src / build_site.SOURCES_FILE).parent.mkdir(parents=True, exist_ok=True)
            sources = (ROOT / build_site.SOURCES_FILE).read_text(encoding="ascii").split("Signed-By:\n")[0]
            block = "".join(" " + (line or ".") + "\n" for line in key.strip("\n").split("\n"))
            (src / build_site.SOURCES_FILE).write_text(sources + "Signed-By:\n" + block, encoding="ascii")
        return src

    def test_the_apt_source_file_names_the_release_key_and_turns_nothing_off(self):
        lines = (ROOT / build_site.SOURCES_FILE).read_text(encoding="ascii").splitlines()
        fields = [line for line in lines if not line.startswith(" ")]
        self.assertEqual(fields, [
            "Types: deb", "URIs: https://packages.nulavio.net/apt", "Suites: stable", "Components: main",
            "Architectures: amd64", "Signed-By:",
        ])  # fmt: skip
        key = (ROOT / build_site.PUBLIC_KEY).read_text(encoding="ascii").strip("\n").split("\n")
        self.assertEqual(build_site.sources_key(ROOT / build_site.SOURCES_FILE), key)
        # One stanza: nothing beside it can name another repository or another key.
        self.assertEqual(sum(1 for line in lines if line.startswith("Types:")), 1)
        self.assertNotIn("", lines)

    def test_ubuntu_appears_only_once_the_apt_repository_is_published(self):
        off = build_site.release_values(self.source("apt-off", "159.0.1-0.1", self.fpr, self.armored))
        on = build_site.release_values(self.source("apt-on", "159.0.1-0.1", self.fpr, self.armored, apt=True))
        self.assertEqual((off["apt"], on["apt"]), ("off", "on"))
        self.assertEqual(on["sources_file"], "https://nulavio.net/apt/nulavio.sources")
        sources = (self.tmp / "apt-on" / build_site.SOURCES_FILE).read_bytes()
        self.assertEqual(on["sources_sha256"], hashlib.sha256(sources).hexdigest(), "the whole file, as the site serves it")
        # A source file that is not the site's, or whose key is not the release key, is refused.
        src = self.source("apt-bucket", "159.0.1-0.1", self.fpr, self.armored, apt=True)
        release = json.loads((src / "packaging" / "release.json").read_text(encoding="utf-8"))
        release["apt_sources"] = "https://packages.nulavio.net/apt/nulavio.sources"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(src)
        src = self.source("apt-other-key", "159.0.1-0.1", self.fpr, self.armored, apt=True)
        sources = src / build_site.SOURCES_FILE
        sources.write_text(re.sub(r"(?m)^ =\S+$", " =AAAA", sources.read_text(encoding="ascii")), encoding="ascii")
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(src)
        pages = {}
        for name, values in (("off", off), ("on", on)):
            out = self.tmp / f"apt-site-{name}"
            real = build_site.release_values
            build_site.release_values = lambda src, values=values: values
            try:
                build_site.build(out)
            finally:
                build_site.release_values = real
            pages[name] = {page: (out / page).read_text(encoding="utf-8") for page in build_site.DOWNLOAD_PAGES}
        for page in build_site.DOWNLOAD_PAGES:
            with self.subTest(page=page):
                for html in (pages["off"][page], pages["on"][page]):
                    self.assertNotIn("<!--apt:", html)
                    self.assertNotIn("<!--/apt:", html)
                    self.assertNotIn("\n\n<h3", html)
                self.assertNotIn("apt update", pages["off"][page])
                self.assertNotIn("nulavio.sources", pages["off"][page])
                self.assertIn("APT", pages["off"][page])  # "not yet: there is no APT repository"
                on_page = pages["on"][page]
                # Downloaded as the user, checked as a whole, and only then put where apt reads it.
                self.assertIn("curl -fsSLO --proto '=https' https://nulavio.net/apt/nulavio.sources", on_page)
                self.assertNotIn("sudo curl", on_page)
                self.assertIn(on["sources_sha256"], on_page)
                self.assertLess(on_page.index("sha256sum nulavio.sources"), on_page.index("sudo install -m 0644 nulavio.sources"))
                self.assertLess(on_page.index("sudo install -m 0644 nulavio.sources"), on_page.index("sudo apt update"))
                self.assertIn("sudo apt install nulavio", on_page)
                self.assertIn("sudo apt remove nulavio\nsudo rm /etc/apt/sources.list.d/nulavio.sources", on_page)
                self.assertNotIn("apt remove", pages["off"][page])
                self.assertIn("Ubuntu 24.04", on_page)
                self.assertNotIn("APT repository</dd>", on_page)
                self.assertNotIn("repositório APT</dd>", on_page)
        ids = [[m for m in re.findall(r'id="([^"]+)"', pages["on"][page])] for page in build_site.DOWNLOAD_PAGES]
        self.assertEqual(ids[0], ids[1], "both languages have the same sections")

    def test_a_repo_file_without_the_checks_or_off_the_site_is_refused(self):
        src = self.source("checks-off", "159.0.1-0.1", self.fpr, self.armored)
        repo_file = src / build_site.REPO_FILE
        repo_file.write_text(repo_file.read_text(encoding="utf-8").replace("gpgcheck=1", "gpgcheck=0"), encoding="utf-8")
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(src)
        src = self.source("bucket", "159.0.1-0.1", self.fpr, self.armored)
        release = json.loads((src / "packaging" / "release.json").read_text(encoding="utf-8"))
        release["repo_file"] = "https://packages.nulavio.net/rpm/nulavio.repo"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(src)

    def test_no_release_no_download_pages(self):
        self.assertIsNone(build_site.release_values(self.source("none", "", "", None)))
        self.assertIsNone(build_site.release_values(self.source("no-key", "159.0.1-0.1", "", None)))
        # The real tree: the pages follow packaging/release.json (out before the first release,
        # in since v160.0-0.1), and a named release must have its key in the repository.
        released = build_site.release_values(ROOT) is not None
        out = self.tmp / "current"
        files = build_site.build(out)
        for page in build_site.DOWNLOAD_PAGES:
            self.assertEqual(page in files, released, page)
        self.assertTrue((out / "en" / "index.html").exists())

    def test_the_key_must_match_the_fingerprint(self):
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(self.source("missing", "159.0.1-0.1", self.fpr, None))
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(self.source("other", "159.0.1-0.1", "A" * 40, self.armored))
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(self.source("bad-version", "alpha", self.fpr, self.armored))

    def test_release_pages(self):
        values = build_site.release_values(self.source("released", "159.0.1-0.1", self.fpr, self.armored))
        self.assertEqual(values["key_fpr"].replace(" ", ""), self.fpr)
        out = self.tmp / "released-site"
        real = build_site.release_values
        build_site.release_values = lambda src: values
        try:
            files = set(build_site.build(out))
        finally:
            build_site.release_values = real
        ids = []
        for page in build_site.DOWNLOAD_PAGES:
            self.assertIn(page, files)
            html = (out / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertNotIn("{{", html)
                self.assertNotIn("<script", html)
                self.assertNotIn("style=", html)
                self.assertIn(values["key_fpr"], html)
                # The key from the release assets is checked against that fingerprint before import (audit R5).
                self.assertLess(html.index("gpg --show-keys --with-fingerprint"), html.index("gpg --import"))
                self.assertIn("dnf config-manager addrepo --from-repofile=https://nulavio.net/rpm/nulavio.repo", html)
                self.assertIn("159.0.1-0.1", html)
                for url in re.findall(r'(?:src|href|srcset)="(https?://[^"]+)"', html):
                    self.assertTrue(url.startswith(SAME_SITE), url)
                for ref in re.findall(r'(?:src|href|srcset)="(/[^"]*)"', html):
                    target = ref.lstrip("/")
                    self.assertIn(f"{target}index.html" if not target or target.endswith("/") else target, files)
                levels = [int(level) for level in re.findall(r"<h([1-6])\b", html)]
                self.assertEqual(levels.count(1), 1)
                ids.append([n.attrs["id"] for n in Tree(html).all() if "id" in n.attrs])
        self.assertEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
