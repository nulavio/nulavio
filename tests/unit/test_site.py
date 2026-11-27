"""nulavio.net: static pages with no scripts or third parties, strict headers, honest copy, and the waitlist."""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import html as html_module
import inspect
import io
import json
import os
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
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import build_site  # noqa: E402
import verify_live  # noqa: E402
import waitlist_remove  # noqa: E402
from contrast import ratio  # noqa: E402
from node_tool import requires_node  # noqa: E402

# The landing (what Nulavio is at launch, the comparison, the waitlist form), the waitlist pages, the
# link page a sign-up is answered with (site/_worker.js serves it with the key in its address) and
# the engineering document ("Recibo": what is ready today, with captures and excerpts from the tree).
LANDING = {"index.html": "pt-BR", "en/index.html": "en-US"}
WAITLIST = {"lista/index.html": "pt-BR", "en/waitlist/index.html": "en-US"}
LINK = {"lista/link/index.html": "pt-BR", "en/waitlist/link/index.html": "en-US"}
DOCUMENT = {"engenharia/index.html": "pt-BR", "en/engineering/index.html": "en-US"}
# PrivacyTests.org's fingerprinting probes side by side, generated from tests/fixtures/privacytests/ (#437).
COMPARISON = {"engenharia/impressao-digital/index.html": "pt-BR", "en/engineering/fingerprinting/index.html": "en-US"}
PAGES = [*LANDING, *WAITLIST, *LINK, *DOCUMENT, *COMPARISON, "404.html"]
FORM_LANG = {"pt-BR": "pt-BR", "en-US": "en"}  # the page's locale -> the form's "lang" field
WORKER = ROOT / "site" / "_worker.js"
SAME_SITE = "https://nulavio.net/"
SHOTS = ROOT / "site" / "assets" / "shots"
# The latest real-site regression run (tests/regression/run_sites.py), behind the landing's compatibility figure.
SITE_RUN = ROOT / "docs" / "research" / "evidence" / "site-regression-2026-11-20.json"
MONTHS = {
    "pt": [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ],
    "en": [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
}
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
        # The document's status is the one packaging/release.json gives (#189).
        pt, en = (self.read(page) for page in DOCUMENT)
        released = build_site.release_values(ROOT)
        if released:
            self.assertIn(f"Alpha pública</strong> · {released['release_version']}", pt)
            self.assertIn(f"Public alpha</strong> · {released['release_version']}", en)
        else:
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
        # have yet is marked as coming, and the compatibility figure is the latest real-site run's:
        # the pages it reached with the protections on, its month, and "none broke" only while it found no breakage
        # (frontend audit N-01, N-04; #202).
        run = json.loads(SITE_RUN.read_text(encoding="utf-8"))
        reached = sum(site["reached_with_protections"] for site in run["sites"].values())
        broken = sum(site["breakage"] for site in run["sites"].values())
        self.assertEqual((reached, broken), (run["summary"]["reached_with_protections"], run["summary"]["breakages"]))
        year, month = (int(part) for part in run["date"].split("-")[:2])
        for page, soon, when, intact, packages in (
            (
                "index.html",
                "Em breve",
                f"{MONTHS['pt'][month - 1]} de {year}",
                "nenhum quebrou",
                "Pacotes assinados para Fedora e Ubuntu",
            ),
            (
                "en/index.html",
                "Coming soon",
                f"{MONTHS['en'][month - 1]} {year}",
                "none broke",
                "Signed packages for Fedora and Ubuntu",
            ),
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
                figure = next(
                    n.parent for n in tree.all("dt") if "sites" in n.text() and ("testados" in n.text() or "tested" in n.text())
                )
                label = next(n.text() for n in figure.children if isinstance(n, Node) and n.tag == "dt")
                number = next(n.text() for n in figure.children if isinstance(n, Node) and n.tag == "dd")
                self.assertEqual(number.strip(), str(reached))
                self.assertIn(when, label)
                self.assertEqual(intact in label, broken == 0, label)
                self.assertNotIn(packages, self.read(page))
        absolute = re.compile(r"(?i)\b(100\s?%|unhackable|imune|immune|totalmente seguro|completely secure|garantid|guarantee)")
        for page in PAGES:
            self.assertIsNone(absolute.search((self.out / page).read_text(encoding="utf-8")), page)
        # The project runs servers (the waitlist's worker, the package repository): what is true is
        # that the browser, on its own, contacts none of them (docs/security/new-profile-connections.md).
        # So a sentence that denies a Nulavio server says it of the browser (#872). Each block is
        # checked apart, because text() joins neighbouring cells with no space between them.
        no_server = re.compile(
            r"(?i)\b(no (nulavio )?servers?\b|there is no (nulavio )?server|has no server"
            r"|sem servidor|não (existe|há|tem) (nenhum )?servidor|nenhum servidor)"
        )
        browser = re.compile(r"(?i)\b(browser|navegador)")
        blocks = {"p", "li", "td", "th", "dt", "dd", "h1", "h2", "h3", "h4", "figcaption", "blockquote", "title"}
        unqualified = []
        for page in sorted(f for f in self.files if f.endswith(".html")):
            tree = self.tree(page)
            texts = [n.text() for n in tree.all() if n.tag in blocks]
            texts += [n.attrs.get("content") or "" for n in tree.all("meta")]
            for text in texts:
                for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
                    if no_server.search(sentence) and not browser.search(sentence):
                        unqualified.append(f"{page}: {sentence}")
        self.assertEqual(unqualified, [])

    # -- landing page structure (spec §7, §9) ---------------------------------------------

    def read(self, page: str) -> str:
        return (self.out / page).read_text(encoding="utf-8")

    def tree(self, page: str) -> Tree:
        return Tree(self.read(page))

    def test_no_placeholder_is_left(self):
        for page in PAGES:
            self.assertNotIn("{{", self.read(page), page)

    def test_both_languages_have_the_same_ids(self):
        for pages in (LANDING, WAITLIST, LINK, DOCUMENT, COMPARISON):
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
        for page in (*LANDING, *WAITLIST, *LINK, *DOCUMENT, *COMPARISON):
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
        # The fingerprinting comparison's marks (#437): on the table and in the tinted Nulavio column.
        border_pairs += [
            (mark, bg) for mark in ("accent-default", "status-critical", "text-secondary") for bg in ("bg-surface", "accent-tint")
        ]
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
        for page in (*LANDING, *COMPARISON):
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

    def test_engineering_pages_count_the_site_run_as_its_evidence_does(self):
        # Claim 2.7 retells the latest real-site run: the pages reached, the pages flagged and the unflagged
        # pages checked must be the evidence's counts, recomputed from its per-site rows (#202).
        run = json.loads(SITE_RUN.read_text(encoding="utf-8"))
        sites = run["sites"].values()
        flagged = sum(1 for site in sites if site["flags"])
        checked = sum(1 for site in sites if not site["flags"] and site["triage"] != "No difference that matters.")
        reached = sum(site["reached_with_protections"] for site in sites)
        summary = run["summary"]
        self.assertEqual(
            (flagged, checked, reached),
            (summary["flagged"], summary["checked_unflagged"], summary["reached_with_protections"]),
        )
        words = {
            "pt": "zero um dois três quatro cinco seis sete oito nove dez onze doze treze catorze quinze",
            "en": "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen",
        }
        words = {lang: names.split(" ") for lang, names in words.items()}
        for page, lang, flagged_text, checked_text in (
            ("engenharia/index.html", "pt", "{} páginas foram sinalizadas", "outras {} foram conferidas"),
            ("en/engineering/index.html", "en", "{} pages were flagged", "{} more were checked"),
        ):
            with self.subTest(page=page):
                claim = next(n for n in self.tree(page).all() if n.attrs.get("id") == "s2-7")
                text = " ".join(claim.text().split())
                self.assertIn(flagged_text.format(words[lang][flagged]).lower(), text.lower())
                self.assertIn(checked_text.format(words[lang][checked]), text)
                self.assertIn(f" {reached} ", text)
                self.assertIn(SITE_RUN.name, text)

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


@requires_node
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

    def test_addresses_keep_to_a_plain_character_set(self):
        """Letters, digits and . _ % + - before the @; letters, digits and hyphens in each label after it.

        An address is later handled outside the worker (read, removed by hand, mailed to), so the
        worker keeps out every character that means something to a shell or to SQL, not only those
        its own bound parameters would have survived."""
        refused = {name: case for name, case in self.cases.items() if name.startswith("refused_")}
        self.assertGreater(len(refused), 50)
        for name, case in refused.items():
            with self.subTest(case=name):
                self.assertEqual((case["status"], case["location"], case["statements"]), (303, "/en/waitlist/#invalid", []))
        plain = self.cases["plain_characters"]
        self.assertRegex(plain["location"], self.LINK_RE)
        db = self.database("plain_characters")
        self.assertEqual([email for email, *_ in self.entries(db)], ["ana.maria+lista_1%x-y@sub-domain.example.com.br"])

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


class WaitlistRemovalTest(unittest.TestCase):
    """scripts/site/waitlist_remove.py, how the maintainer removes an entry by hand (CONTRIBUTING, "Website")."""

    # Addresses that may be on the list: today's plain ones, and ones from before the worker narrowed what it
    # takes (any character but whitespace and @), with every printable ASCII character that is not a letter or
    # a digit, and control characters: ESC, DEL, NUL, U+001F and U+0085 (whitespace to Python, not to the worker).
    OTHERS = ("ana@example.org", "Bruno@Example.org", "carla.souza+lista@exemplo.com.br")
    CONTROL = (
        "a\x1b[2Jb@example.org",
        "a\x7fb@example.org",
        "a\x00b@example.org",
        "a\x7f\x00\x1bc@example.org",
        "\x1fa@example.org\x1f",
        "\x85a@example.org",
        "a@exa\x9bmple.org",
    )
    ODD = (
        *(f"a{c}b@example.org" for c in "!\"#$%&'()*+,-./:;<=>?[\\]^_`{|}~"),
        "o'brien@example.org",
        "'@example.org",
        "é@exemplo.br",
        *CONTROL,
        "a\x00bb@example.org",  # differs from a\x00b@… only after the NUL
    )

    SQL = (
        r"^DELETE FROM waitlist WHERE email = CAST\(X'([0-9a-f]+)' AS TEXT\)( AND hex\(email\) = '[0-9A-F]+'|); "
        r"DELETE FROM waitlist_links WHERE email = CAST\(X'\1' AS TEXT\)\2$"
    )

    @classmethod
    def setUpClass(cls):
        cls.schema = re.findall(r'"(CREATE TABLE IF NOT EXISTS waitlist(?:_links)? \(.*?\))"', WORKER.read_text(encoding="utf-8"))
        assert len(cls.schema) == 2, cls.schema

    def listed(self, addresses: list[str]) -> sqlite3.Connection:
        """SQLite with the worker's tables and these addresses, each with a link."""
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        for sql in self.schema:
            db.execute(sql)
        for n, email in enumerate(addresses):
            db.execute("INSERT INTO waitlist VALUES (?, 'en', '', ?)", (email, f"2026-11-{n % 28 + 1:02d}T00:00:00Z"))
            db.execute("INSERT INTO waitlist_links VALUES (?, ?)", (email, f"{n:064x}"))
        return db

    def removing(self, address: str, *, answers=("y",), args=()):
        """What main() printed and sent to the runner, with this address typed at the prompt."""
        typed = iter([address, *answers])
        sent = []

        def read(prompt):
            return next(typed)

        def run(argv):
            sent.append(argv)
            return 0

        out = io.StringIO()
        status = waitlist_remove.main(list(args), read=read, run=run, out=out)
        return status, sent, out.getvalue()

    def test_exactly_the_entry_and_its_link_go_whatever_the_address_holds(self):
        for address in [*self.ODD, *self.OTHERS]:
            with self.subTest(address=address):
                db = self.listed([*self.ODD, *self.OTHERS])
                status, sent, _ = self.removing(address.upper() if address == "ana@example.org" else address)
                self.assertEqual(status, 0)
                (argv,) = sent
                self.assertIsInstance(argv, list, "an argument list, never a shell")
                self.assertEqual(argv[:6], ["wrangler", "d1", "execute", "nulavio-waitlist", "--remote", "--command"])
                self.assertEqual(len(argv), 7, "the SQL is one argument")
                self.assertRegex(argv[6], self.SQL, "the SQL holds none of the address's characters")
                db.executescript(argv[6])
                left = {email for (email,) in db.execute("SELECT email FROM waitlist")}
                linked = {email for (email,) in db.execute("SELECT email FROM waitlist_links")}
                self.assertEqual(left, {*self.ODD, *self.OTHERS} - {address})
                self.assertEqual(linked, left)

    def test_an_address_not_on_the_list_removes_nothing(self):
        db = self.listed(self.OTHERS)
        _, (argv,), _ = self.removing("d'ora@example.org")
        db.executescript(argv[6])
        self.assertEqual(len(db.execute("SELECT * FROM waitlist").fetchall()), len(self.OTHERS))

    def test_the_address_never_comes_from_the_command_line(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            waitlist_remove.main(["ana@example.org"], read=lambda prompt: "", run=lambda argv: 0, out=io.StringIO())
        self.assertEqual(raised.exception.code, 2)

    def test_it_asks_first_and_can_only_show(self):
        status, sent, out = self.removing("ana@example.org", answers=("n",))
        self.assertEqual((status, sent), (2, []))
        self.assertIn("Nothing removed.", out)
        status, sent, out = self.removing("ana@example.org", answers=(), args=("--dry-run",))
        self.assertEqual((status, sent), (0, []))
        self.assertIn("Address: 'ana@example.org'", out)
        status, sent, _ = self.removing("ana@example.org", answers=(), args=("--yes", "--database", "other"))
        self.assertEqual((status, sent[0][3]), (0, "other"))

    def test_only_what_the_worker_never_stored_is_refused(self):
        """Whitespace inside, no @, too long: the older pattern refused these too. Control characters are shown, not refused."""
        spaces = ["a b@example.org", "a\tb@example.org", "a\u00a0b@example.org", "a\u2028b@example.org"]
        for address in ["", *spaces, "no-at", "a" * 250 + "@x.org"]:
            with self.subTest(address=address):
                status, sent, out = self.removing(address)
                self.assertEqual((status, sent), (2, []))
                self.assertIn("Refused", out)
        status, sent, out = self.removing("a\x1b[2Jb@example.org", answers=(), args=("--dry-run",))
        self.assertEqual(status, 0)
        self.assertIn("Address: 'a\\x1b[2Jb@example.org'", out, "spelled out")
        self.assertNotIn("\x1b", out, "nothing reaches the terminal as is")

    def test_it_trims_what_the_worker_trims_and_nothing_more(self):
        trimmed = (
            ("\ufeffana@example.org\r", "ana@example.org"),
            (" \t\x1fa@example.org\x1f ", "\x1fa@example.org\x1f"),
            ("\x85a@example.org", "\x85a@example.org"),
        )
        for typed, meant in trimmed:
            with self.subTest(typed=typed):
                _, (argv,), _ = self.removing(typed)
                self.assertIn(meant.encode("utf-8").hex(), argv[6])
                self.assertEqual(argv[6].count("X'"), 2)

    def test_a_file_on_standard_input_reaches_the_sql_byte_for_byte(self):
        """The real input(): a file holding ESC, DEL and NUL, with a byte order mark, as CONTRIBUTING says to give it."""
        address = "a\x1b[2J\x7f\x00b@example.org"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "address.txt"
            path.write_bytes(b"\xef\xbb\xbf" + address.encode("utf-8") + b"\n")
            with path.open("rb") as stdin:
                done = subprocess.run(
                    [sys.executable, "-I", str(ROOT / "scripts" / "site" / "waitlist_remove.py"), "--dry-run"],
                    stdin=stdin,
                    capture_output=True,
                    timeout=30,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8"},
                )
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout.decode("ascii")  # ascii(): nothing else reaches the terminal
        self.assertIn(f"CAST(X'{address.encode('utf-8').hex()}' AS TEXT)", out)
        self.assertIn(f"hex(email) = '{address.encode('utf-8').hex().upper()}'", out)

    def test_a_missing_wrangler_is_said_plainly(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(waitlist_remove.run_wrangler([str(ROOT / "no-such-wrangler")]), 2)
        self.assertIn("was not found", out.getvalue())

    def test_the_documented_read_shows_every_address_as_printable_ascii(self):
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        read = r'To read the list: `wrangler d1 execute nulavio-waitlist --remote --command "([^"]+)"`'
        (query,) = re.findall(read, contributing)
        self.assertNotIn("SELECT *", query)
        db = self.listed([*self.ODD, *self.OTHERS])
        rows = db.execute(query).fetchall()
        self.assertEqual(len(rows), len(self.ODD) + len(self.OTHERS))
        shown = {email for email, *_ in rows}
        for email, *rest in rows:
            with self.subTest(email=email):
                self.assertRegex("".join(map(str, [email, *rest])), r"^[ -~]*$")
        for address in [*self.ODD, *self.OTHERS]:
            plain = all(" " <= c <= "~" for c in address)
            self.assertIn(address if plain else "hex:" + address.encode("utf-8").hex().upper(), shown)

    def test_contributing_points_to_the_script_and_holds_no_sql_to_fill_in(self):
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("scripts/site/waitlist_remove.py", contributing)
        self.assertNotRegex(contributing, r"(?i)DELETE FROM waitlist", "the address is never pasted into SQL by hand")


# What scripts/site/build_site.py reads, traced while it builds (#661). The hook logs every file a
# process opens (Python's "open" audit event, imports included) and every process it starts. The
# build runs in a child of the test with the hook installed first; the python3 -c child the build
# starts for `prefs explain` gets the same hook put ahead of its own code.
TRACE_HOOK = """import json as _json, os as _os, sys as _sys
def _nulavio_trace(event, args, _log=open({log!r}, "a", encoding="utf-8", buffering=1)):
    try:
        if event == "open" and isinstance(args[0], (str, bytes)):
            _log.write("open\\t" + _json.dumps(_os.path.abspath(_os.fsdecode(args[0]))) + "\\n")
        elif event == "subprocess.Popen":
            cwd = _os.path.abspath(_os.fsdecode(args[2])) if args[2] is not None else _os.getcwd()
            _log.write("run\\t" + _json.dumps([cwd, [_os.fsdecode(a) for a in args[1]]]) + "\\n")
        elif event in ("os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork"):
            _log.write("other\\t" + event + "\\n")
    except Exception:
        pass  # an exception in an audit hook would abort the call it audits
_sys.addaudithook(_nulavio_trace)
"""
TRACE_BUILD = """import pathlib, re, subprocess, sys
root, out, hook = sys.argv[1:4]
exec(hook)
_run = subprocess.run
def _traced(argv, *args, **kwargs):
    argv = [str(a) for a in argv]
    code = python_code_at(argv) if pathlib.Path(argv[0]).name.startswith("python") else None
    if code is not None:
        argv[code] = hook + argv[code]
    return _run(argv, *args, **kwargs)
subprocess.run = _traced
sys.path.insert(0, str(pathlib.Path(root) / "scripts" / "site"))
import build_site
build_site.build(pathlib.Path(out))
"""


def python_code_at(argv: list[str]):  # no "| None": its source also runs in the child, without the __future__ import
    """Where the code of python3 [flags] -c <code> is in argv, or None: only flags that take no value may
    come before -c (python3 tool.py -c x runs tool.py, and -c x is its argument)."""
    at = argv.index("-c") if "-c" in argv else 0
    return at + 1 if at and all(re.fullmatch(r"-[bBdEIOqsSuv]+", a) for a in argv[1:at]) else None


def links_met(name: str, hops: int = 40) -> set[str]:
    """Each symlink met while resolving name, by its own path: repointing one changes what is read."""
    parts = Path(name).parts
    for i in range(2, len(parts) + 1):
        prefix = os.path.join(*parts[:i])  # no link before it, so normpath reads its ".." right
        if os.path.islink(prefix) and hops:
            rest = os.path.join(os.path.dirname(prefix), os.readlink(prefix), *parts[i:])
            return {os.path.normpath(prefix), *links_met(rest, hops - 1)}
    return set()


def traced_build_inputs(test: unittest.TestCase) -> set[str]:
    """The files of this tree that a build of the site reads, relative to the root.

    What the trace cannot see: directory listings (the import system lists every directory on
    sys.path, so counting them would demand a glob over each), a file only checked for existence,
    what git and gpg read (git reads .git; gpg is handed its file, which counts), and branches of
    the build this tree does not take (a file read only once release.json names something else).
    """
    with tempfile.TemporaryDirectory(prefix="nulavio-site-trace-") as tmp:
        log, out = Path(tmp) / "trace.log", Path(tmp) / "site"
        hook = TRACE_HOOK.format(log=str(log))
        result = subprocess.run(
            [sys.executable, "-I", "-c", inspect.getsource(python_code_at) + TRACE_BUILD, str(ROOT), str(out), hook],
            capture_output=True, text=True, timeout=300, cwd=tmp,
        )  # fmt: skip
        test.assertEqual(result.returncode, 0, result.stderr[-2000:])
        lines = log.read_text(encoding="utf-8").splitlines()
    return trace_inputs(test, lines)


def trace_inputs(test: unittest.TestCase, lines: list[str], root: Path = ROOT) -> set[str]:
    """The files under root that a TRACE_HOOK log says were read, relative to root."""
    read, other = set(), []
    for line in lines:
        kind, _, value = line.partition("\t")
        if kind == "open":
            read.add(json.loads(value))
        elif kind == "run":
            cwd, argv = json.loads(value)
            name = Path(argv[0]).name
            if name.startswith("python"):
                # A traced python logs its own opens; its arguments are code and options, not files.
                code = python_code_at(argv)
                if code is None or "_nulavio_trace" not in argv[code]:
                    other.append(f"untraced python: {argv[:4]}")
            elif name in ("git", "gpg"):
                read.update(os.path.abspath(os.path.join(cwd, arg)) for arg in argv[1:])
            else:
                other.append(f"unknown program: {argv[0]}")
        else:
            other.append(value)
    test.assertEqual(other, [], "the build starts a process this trace does not follow: teach traced_build_inputs about it")
    inputs = set()
    for path in {Path(p) for name in read for p in (name, os.path.realpath(name), *links_met(name))}:
        if path.parent.name == "__pycache__" and path.suffix == ".pyc":
            path = path.parent.parent / (path.name.split(".", 1)[0] + ".py")  # x.cpython-312.pyc is x.py
        if not path.is_relative_to(root) or not (path.is_file() or path.is_symlink()):  # a link to a directory too
            continue
        relative = path.relative_to(root).as_posix()
        if not relative.startswith(".git/"):
            inputs.add(relative)
    return inputs


def hooked_trace(test: unittest.TestCase, root: Path, code: str) -> set[str]:
    """What trace_inputs makes of a python3 child that runs code in root under TRACE_HOOK."""
    log = root / "trace.log"
    result = subprocess.run(
        [sys.executable, "-I", "-c", TRACE_HOOK.format(log=str(log)) + code],
        capture_output=True, text=True, timeout=60, cwd=root,
    )  # fmt: skip
    test.assertEqual(result.returncode, 0, result.stderr[-2000:])
    return trace_inputs(test, log.read_text(encoding="utf-8").splitlines(), root)


def path_filter_matches(patterns: list[str], path: str) -> bool:
    """GitHub's paths filter: * stops at "/", ** crosses it, **/ also matches at the root; the last
    matching pattern decides, "!" excludes (fnmatch would let * cross "/").

    GitHub reads ?, + and [] its own way (? makes the character before it optional), so a pattern
    with one is refused, not guessed at.
    """
    included = False
    for pattern in patterns:
        negative = pattern.startswith("!")
        glob = pattern[1:] if negative else pattern
        if re.search(r"[?+\[\]]", glob):
            raise ValueError(f"{pattern!r}: teach path_filter_matches GitHub's ?, + and [] first")
        regex = "".join(
            "(?:.*/)?" if token == "**/" else ".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
            for token in re.findall(r"\*\*/|\*\*|\*|[^*]+", glob)
        )
        if re.fullmatch(regex, path, re.S):
            included = not negative
    return included


def unwatched(inputs: set[str], patterns: list[str]) -> list[str]:
    return sorted(path for path in inputs if not path_filter_matches(patterns, path))


class SiteWorkflowTest(unittest.TestCase):
    """.github/workflows/site.yml: only main deploys, in the site environment, and the workflow hands the token to one step.

    The workflow is read by indentation with comments dropped, so a guard counts only as a key of
    the block it belongs to: moved into a comment or into another job, it no longer does. This is a
    narrow reader for this one file, not a YAML parser, and it cannot tell what a step's script does
    with the token once it has it: that is read in review.
    """

    def setUp(self):
        self.text = (ROOT / ".github/workflows/site.yml").read_text(encoding="utf-8")
        lines = (re.sub(r"\s+#.*$", "", line) for line in self.text.splitlines())  # a comment after a value
        self.lines = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]

    @staticmethod
    def indent(line):
        return len(line) - len(line.lstrip())

    def block(self, lines, key):
        """The lines nested under `key` (a line of `lines` at their shallowest indentation)."""
        level = min(self.indent(line) for line in lines)
        start = next(i for i, line in enumerate(lines) if self.indent(line) == level and line.strip() == key) + 1
        rest = lines[start:]
        stop = next((i for i, line in enumerate(rest) if self.indent(line) <= level), len(rest))
        return rest[:stop]

    def keys(self, lines):
        level = min(self.indent(line) for line in lines)
        return [line.strip() for line in lines if self.indent(line) == level]

    def test_only_a_push_to_main_or_a_manual_run_starts_it(self):
        triggers = self.block(self.lines, "on:")
        self.assertEqual(self.keys(triggers), ["push:", "workflow_dispatch:"])
        self.assertEqual(self.keys(self.block(triggers, "push:"))[0], "branches: [main]")

    def push_paths(self):
        paths = self.block(self.block(self.block(self.lines, "on:"), "push:"), "paths:")
        for line in paths:  # one-line items only: YAML folds a continued line into the entry above
            if self.indent(line) != self.indent(paths[0]) or not line.lstrip().startswith("- "):
                raise ValueError(f"{line.strip()!r}: push_paths reads one-line list items only")
        entries = [line.strip().removeprefix("- ").strip() for line in paths]
        return [e[1:-1] if len(e) > 1 and e[0] == e[-1] and e[0] in "'\"" else e for e in entries]

    def test_a_push_that_changes_anything_the_build_reads_runs_it(self):
        # #661: the build counted the defaults in browser/config/prefs/baseline.js and ran the
        # launcher, which reads it, but a push that changed only that file deployed nothing.
        inputs = traced_build_inputs(self)
        for known in ("browser/config/prefs/baseline.js", "launcher/nulavio_launcher/cli.py", "scripts/release/whats_new.py"):
            self.assertIn(known, inputs, "the trace no longer sees what the build reads")
        self.assertEqual(unwatched(inputs, self.push_paths()), [], "add these to the push paths of site.yml")

    def test_the_trace_counts_a_symlink_the_build_reads_and_its_target(self):
        # A push that only points the link elsewhere changes the site too.
        with tempfile.TemporaryDirectory(prefix="nulavio-site-trace-") as tmp:
            root = Path(os.path.realpath(tmp))
            (root / "site").mkdir()
            (root / "site/logo.svg").write_text("<svg/>", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs/logo.svg").symlink_to("../site/logo.svg")
            inputs = hooked_trace(self, root, "open('docs/logo.svg').close()")
        self.assertEqual(inputs, {"docs/logo.svg", "site/logo.svg"})

    def test_the_trace_counts_a_symlink_met_on_the_way_to_the_target(self):
        # site/assets/icon.svg goes through docs/current: repointing docs/current changes the icon.
        with tempfile.TemporaryDirectory(prefix="nulavio-site-trace-") as tmp:
            root = Path(os.path.realpath(tmp))
            (root / "site/real").mkdir(parents=True)
            (root / "site/real/icon.svg").write_text("<svg/>", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs/current").symlink_to("../site/real")
            (root / "site/assets").mkdir()
            (root / "site/assets/icon.svg").symlink_to("../../docs/current/icon.svg")
            inputs = hooked_trace(self, root, "open('site/assets/icon.svg').close()")
        self.assertEqual(inputs, {"site/assets/icon.svg", "docs/current", "site/real/icon.svg"})

    def test_only_a_python_whose_code_is_its_own_c_counts_as_traced(self):
        # python3 tool.py -c x runs tool.py, with -c x as its argument: the hook would not run.
        self.assertEqual(python_code_at(["python3", "-I", "-B", "-c", "code", "prefs"]), 4)
        for argv in (["python3", "tool.py", "-c", "x"], ["python3", "-m", "tool", "-c", "x"], ["python3", "-W", "-c", "x"]):
            with self.subTest(argv=argv):
                self.assertIsNone(python_code_at(argv))
                line = "run\t" + json.dumps(["/", [*argv[:-1], "_nulavio_trace"]])
                with self.assertRaisesRegex(AssertionError, "untraced python"):
                    trace_inputs(self, [line])

    def test_the_trace_does_not_take_a_traced_pythons_arguments_for_files(self):
        # prefs explain runs in the root with --category tracking: a scratch file named tracking
        # there is not read. A traced python logs its own opens; gpg is handed its file.
        with tempfile.TemporaryDirectory(prefix="nulavio-site-trace-") as tmp:
            root = Path(os.path.realpath(tmp))
            (root / "tracking").write_text("", encoding="utf-8")
            (root / "key.asc").write_text("", encoding="utf-8")
            argv = ["python3", "-I", "-B", "-c", "_nulavio_trace", "prefs", "explain", "--category", "tracking"]
            code = f"import sys\nsys.audit('subprocess.Popen', 'python3', {argv!r}, None, None)\n"
            code += "sys.audit('subprocess.Popen', 'gpg', ['gpg', '--show-keys', 'key.asc'], None, None)\n"
            self.assertEqual(hooked_trace(self, root, code), {"key.asc"})

    def test_the_trace_reads_a_file_name_with_a_line_break(self):
        with tempfile.TemporaryDirectory(prefix="nulavio-site-trace-") as tmp:
            root = Path(os.path.realpath(tmp))
            (root / "a\nb").mkdir()
            (root / "a\nb/x.txt").write_text("", encoding="utf-8")
            self.assertEqual(hooked_trace(self, root, "open('a\\nb/x.txt').close()"), {"a\nb/x.txt"})

    def test_the_matcher_refuses_the_characters_github_reads_its_own_way(self):
        # GitHub: ? makes the character before it optional, + repeats it, [] is a class of one
        # character. Read as fnmatch would, baselin?.js would count baseline.js as watched.
        for pattern in ("browser/config/prefs/baselin?.js", "browser/config/prefs/baselin+.js", "browser/[bc]onfig/**"):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                path_filter_matches([pattern], "browser/config/prefs/baseline.js")
        self.assertTrue(path_filter_matches(["**/README.md"], "README.md"), "**/ matches at the root too")
        # * already crosses a line break in a name; ** and **/ cross it as well.
        self.assertTrue(path_filter_matches(["site/**"], "site/a\nb/x.txt"))
        self.assertTrue(path_filter_matches(["**/x.txt"], "a\nb/x.txt"))

    def test_the_push_paths_are_read_single_or_double_quoted(self):
        self.lines = [
            "on:", "  push:", "    branches: [main]", "    paths:",
            '      - "site/**"', "      - 'browser/config/prefs/**'", "      - launcher/**",
            "  workflow_dispatch:",
        ]  # fmt: skip
        self.assertEqual(self.push_paths(), ["site/**", "browser/config/prefs/**", "launcher/**"])

    def test_the_push_paths_refuse_an_entry_continued_on_the_next_line(self):
        # YAML folds the two lines into one pattern, browser/config/prefs/** extra, which baseline.js does not match.
        self.lines = ["on:", "  push:", "    paths:", "      - browser/config/prefs/**", "        extra", "  workflow_dispatch:"]
        with self.assertRaisesRegex(ValueError, "extra"):
            self.push_paths()

    def test_the_paths_check_finds_an_input_the_workflow_does_not_watch(self):
        patterns = ["site/**", "launcher/**", "scripts/site/**"]  # its own list: site.yml may watch browser/**
        inputs = {"browser/config/prefs/baseline.js", "launcher/nulavio_launcher/cli.py", "site/en/index.html"}
        self.assertEqual(unwatched(inputs, patterns), ["browser/config/prefs/baseline.js"])
        self.assertFalse(path_filter_matches(["site/*"], "site/en/index.html"), "* stops at /")
        self.assertFalse(path_filter_matches(["launcher/**", "!launcher/x.py"], "launcher/x.py"))

    def test_the_deploy_job_runs_on_main_in_the_site_environment_with_read_access_only(self):
        self.assertIn("permissions: {}", self.keys(self.lines))
        jobs = self.block(self.lines, "jobs:")
        self.assertEqual(self.keys(jobs), ["deploy:"])
        deploy = self.block(jobs, "deploy:")
        keys = self.keys(deploy)
        self.assertIn("if: ${{ github.ref == 'refs/heads/main' }}", keys)
        self.assertIn("environment: site", keys)  # limited to main, holds CLOUDFLARE_API_TOKEN (#182)
        self.assertEqual(self.keys(self.block(deploy, "permissions:")), ["contents: read"])

    def test_the_workflow_hands_the_token_only_to_the_deploy_step(self):
        # Counted in the raw file, comments included: a "#" inside a quoted value or a run script is
        # not a comment, and GitHub evaluates the expressions there. Any use of the secrets context
        # counts (secrets.X, secrets['X'], toJSON(secrets)), and so does a "secrets:" key (inherit).
        uses = [m.group(0) for m in re.finditer(r"\$\{\{.*?\}\}", self.text, re.S) if re.search(r"\bsecrets\b", m.group(0))]
        self.assertEqual(uses, ["${{ secrets.CLOUDFLARE_API_TOKEN }}"])
        self.assertIsNone(re.search(r"^\s*-?\s*secrets\s*:", self.text, re.M))
        steps = self.block(self.block(self.block(self.lines, "jobs:"), "deploy:"), "steps:")
        deploy_step = self.block(steps, "- name: Deploy to Cloudflare Pages (production)")
        env = [line.strip() for line in self.block(deploy_step, "env:")]
        self.assertIn("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}", env)
        # A step can hand a value on to the later steps through these files; this workflow uses none.
        self.assertIsNone(re.search(r"GITHUB_(ENV|OUTPUT|STATE)", self.text))


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
        release.pop("flatpak_bundle", None)
        # Off unless a case turns it on (with the certificate it needs): the tree's release.json names an APK
        # from 160.0-0.5 on, and a case about something else must not depend on it.
        release.pop("companion_apk", None)
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

    def test_no_flatpak_bundle_is_offered_until_flathub(self):
        # #467: the bundle never updated itself (R75), so the pages offer none until Flathub (#88-#91), tell people who
        # installed one that it gets no fixes, and how to move; a release.json that names a bundle is refused.
        src = self.source("fp-named", "159.0.1-0.1", self.fpr, self.armored, apt=True)
        release = json.loads((src / "packaging" / "release.json").read_text(encoding="utf-8"))
        release["flatpak_bundle"] = "nulavio-159.0.1-0.1.x86_64.flatpak"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        with self.assertRaisesRegex(build_site.BuildError, "#467"):
            build_site.release_values(src)
        values = build_site.release_values(self.source("fp-none", "159.0.1-0.1", self.fpr, self.armored, apt=True))
        out = self.tmp / "fp-site"
        real = build_site.release_values
        build_site.release_values = lambda src: values
        try:
            build_site.build(out)
        finally:
            build_site.release_values = real
        pages = {page: (out / page).read_text(encoding="utf-8") for page in build_site.DOWNLOAD_PAGES}
        for page, text in pages.items():
            with self.subTest(page=page):
                self.assertNotIn("<!--flatpak:", text)
                self.assertNotIn(".x86_64.flatpak", text)
                self.assertNotIn("flatpak install", text)
                self.assertIn("Flathub", text)
                self.assertIn("flatpak uninstall --user net.nulavio.Nulavio", text)  # to remove a bundle installed before
                self.assertIn("~/.var/app/net.nulavio.Nulavio", text)
                self.assertIn('href="#remove"', text)
        for page in build_site.DOWNLOAD_PAGES:
            self.assertIn('id="install-flatpak-h"', pages[page])
        ids = [re.findall(r'id="([^"]+)"', pages[page]) for page in build_site.DOWNLOAD_PAGES]
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

    def test_the_engineering_pages_say_which_release_is_out_or_that_none_is(self):
        # #189: they said "no release to download" while the download pages offered one.
        values = build_site.release_values(self.source("eng-released", "159.0.1-0.1", self.fpr, self.armored))
        pages = {}
        real = build_site.release_values
        for name, released in (("on", values), ("off", None)):
            out = self.tmp / f"eng-{name}"
            build_site.release_values = lambda src, released=released: released
            try:
                build_site.build(out)
            finally:
                build_site.release_values = real
            pages[name] = {page: (out / page).read_text(encoding="utf-8") for page in DOCUMENT}
        none = {"pt-BR": "sem versão para baixar", "en-US": "no release to download"}
        for page, locale in DOCUMENT.items():
            on, off = pages["on"][page], pages["off"][page]
            with self.subTest(page=page):
                for html in (on, off):
                    self.assertNotIn("<!--release:", html)
                    self.assertNotIn("<!--/release:", html)
                    self.assertEqual(html.count('<meta name="description"'), 1)
                self.assertIn("159.0.1-0.1", on)
                self.assertNotIn(none[locale], on)
                self.assertNotIn("F-Droid's review", on)
                self.assertNotIn("revisão do F-Droid", on)
                self.assertIn(none[locale], off)
                self.assertNotIn("159.0.1-0.1", off)
                tree = Tree(on)
                description = next(n.attrs["content"] for n in tree.root.walk() if n.attrs.get("name") == "description")
                self.assertIn("159.0.1-0.1", description)
        ids = [re.findall(r'id="([^"]+)"', pages["on"][page]) for page in DOCUMENT]
        self.assertEqual(ids[0], ids[1], "both languages have the same sections")

    def test_whats_new_pages_follow_the_published_version(self):
        # #198: an index and a page per published version, in both languages, from packaging/whats-new/.
        real = build_site.release_values
        current = real(ROOT)
        self.assertIsNotNone(current, "the tree names a published release")
        built = {}
        for name, values in (("on", current), ("off", None), ("older", {**current, "release_version": "159.0.1-0.1"})):
            out = self.tmp / f"whats-new-{name}"
            build_site.release_values = lambda src, values=values: values
            try:
                built[name] = (out, set(build_site.build(out)))
            finally:
                build_site.release_values = real
        # A published version older than every record: no pages, and the download pages link to none.
        older_out, older_files = built["older"]
        self.assertFalse({f for f in older_files if f.startswith(("novidades/", "en/whats-new/"))})
        for page in build_site.DOWNLOAD_PAGES:
            self.assertNotIn("whats-new/", (older_out / page).read_text(encoding="utf-8").replace("novidades/", "whats-new/"))
        out, files = built["on"]
        version = current["release_version"]
        pages = ["novidades/index.html", "en/whats-new/index.html",
                 f"novidades/{version}/index.html", f"en/whats-new/{version}/index.html"]  # fmt: skip
        self.assertLessEqual(set(pages), files)
        self.assertFalse({f for f in built["off"][1] if f.startswith(("novidades/", "en/whats-new/"))})
        sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
        for page in pages:
            html = (out / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertNotIn("<script", html)
                self.assertNotIn("style=", html)
                self.assertNotIn("{{", html)
                for url in re.findall(r'(?:src|href|srcset)="(https?://[^"]+)"', html):
                    self.assertTrue(url.startswith(SAME_SITE), url)
                for ref in re.findall(r'(?:src|href|srcset)="(/[^"#]*)"', html):
                    target = out / ref.lstrip("/")
                    self.assertTrue(target.is_file() or (target / "index.html").is_file(), ref)
                self.assertIn(f"<body>\n{build_site.EMAIL_OFF[0]}\n", html)
                self.assertIn(f"<loc>https://nulavio.net/{page.removesuffix('index.html')}</loc>", sitemap)
        record = json.loads((ROOT / "packaging" / "whats-new" / f"{version}.json").read_text(encoding="utf-8"))
        en = (out / f"en/whats-new/{version}/index.html").read_text(encoding="utf-8")
        pt = (out / f"novidades/{version}/index.html").read_text(encoding="utf-8")
        self.assertIn(html_module.escape(record["en-US"]["summary"], quote=True), en)
        self.assertIn(html_module.escape(record["pt-BR"]["summary"], quote=True), pt)
        self.assertEqual(re.findall(r'id="([^"]+)"', en), re.findall(r'id="([^"]+)"', pt), "same sections in both")
        for page in build_site.DOWNLOAD_PAGES:  # the download pages link to the version's notes
            self.assertIn(f"whats-new/{version}/" if page.startswith("en/") else f"novidades/{version}/",
                          (out / page).read_text(encoding="utf-8"))  # fmt: skip

    def test_the_companion_shows_once_a_published_release_carries_its_apk(self):
        # ADR 0014: the download pages offer the APK and its certificate's SHA-256 only from the
        # first release whose assets have it (release_metadata.py sets companion_apk).
        src = self.source("companion", "160.0-0.5", self.fpr, self.armored)
        (src / "site" / "keys").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "site" / "keys" / "nulavio-companion.der", src / "site" / "keys")
        self.assertEqual(build_site.release_values(src)["companion"], "off")
        release = json.loads((src / "packaging" / "release.json").read_text(encoding="utf-8"))
        release["companion_apk"] = "nulavio-companion-0.1.0.apk"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        on = build_site.release_values(src)
        fpr = hashlib.sha256((ROOT / "site" / "keys" / "nulavio-companion.der").read_bytes()).hexdigest()
        self.assertEqual((on["companion"], on["companion_apk"], on["companion_fpr"]), ("on", "nulavio-companion-0.1.0.apk", fpr))
        release["companion_apk"] = "https://evil.example/x.apk"
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        with self.assertRaises(build_site.BuildError):
            build_site.release_values(src)
        pages = {}
        real = build_site.release_values
        for name, values in (("on", on), ("off", {**on, "companion": "off"})):
            out = self.tmp / f"companion-site-{name}"
            build_site.release_values = lambda src, values=values: values
            try:
                build_site.build(out)
            finally:
                build_site.release_values = real
            pages[name] = {page: (out / page).read_text(encoding="utf-8") for page in build_site.DOWNLOAD_PAGES}
        for page in build_site.DOWNLOAD_PAGES:
            with self.subTest(page=page):
                self.assertNotIn("<!--companion:", pages["on"][page])
                self.assertIn('id="companion"', pages["on"][page])
                self.assertIn(fpr, pages["on"][page])
                self.assertIn("apksigner verify --print-certs nulavio-companion-0.1.0.apk", pages["on"][page])
                self.assertNotIn('id="companion"', pages["off"][page])
                self.assertNotIn("<!--companion:", pages["off"][page])
        ids = [re.findall(r'id="([^"]+)"', pages["on"][page]) for page in build_site.DOWNLOAD_PAGES]
        self.assertEqual(ids[0], ids[1], "both languages have the same sections")

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
                # Also as dnf prints it, without spaces, and the red "Signing key not found" it shows first (#120).
                self.assertIn(self.fpr, html)
                self.assertIn("Signing key not found", html)
                # The key from the release assets is checked against that fingerprint before import (audit R5),
                # by the block itself, not only by the reader's eyes (#744).
                self.assertLess(html.index("gpg --show-keys --with-colons"), html.index("gpg --import nulavio-packages.asc"))
                self.assertLess(html.index(f'f == "{self.fpr}")'), html.index("gpg --import nulavio-packages.asc"))
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

    def test_gpgs_english_message_on_the_pt_page_is_marked_english(self):
        # #651: a screen reader reads the quoted terminal text in English, as the terminal prints it.
        html = (ROOT / "site/baixar/index.html").read_text(encoding="utf-8")
        tags = re.findall(r"<code([^>]*)>Good signature</code>", html)
        self.assertTrue(tags)
        for attrs in tags:
            self.assertIn('lang="en"', attrs)

    def test_the_manual_check_is_plain_commands(self):
        # #651 (review of PR #733): the four lines before #651 also ran in Fish, and a shell variable
        # (`sig=$(...)`) made Fish 3 refuse the whole paste ("Unsupported use of '='"). Commands joined by `&&`
        # and `|` run in bash, zsh and Fish 3; no assignment, no command substitution.
        for page in build_site.DOWNLOAD_PAGES:
            with self.subTest(page=page):
                html = (ROOT / "site" / page).read_text(encoding="utf-8")
                block = html_module.unescape(re.search(r'<section id="verify".*?<code>(.*?)</code>', html, re.S).group(1))
                for line in block.splitlines():
                    self.assertNotRegex(line, r"(^|&&|\||;)\s*[A-Za-z_][A-Za-z0-9_]*=", "a shell variable")
                self.assertNotIn("$(", block)
                self.assertNotIn("`", block)

    def test_the_key_recovery_keeps_a_secret_key_the_reader_had(self):
        # Review of #752 (round 3): an old key file could hold only the public part of a key whose secret part
        # the reader already had, and `--delete-secret-and-public-key` deletes that secret part as well. The
        # recovery deletes public keys first, says how to tell whether the file brought a secret part, and keeps
        # a secret part when in doubt.
        changelog = (ROOT / "docs/security/changelog.md").read_text(encoding="utf-8")
        entry = next(line for line in changelog.splitlines() if "the key before the import** (#744)" in line)
        self.assertIn("gpg --show-keys nulavio-packages.asc", entry)
        self.assertLess(entry.index("gpg --delete-key <fingerprint>"), entry.index("--delete-secret-and-public-key"))
        self.assertIn("leave it in place", entry)

    def test_the_manual_check_prints_checksums_only_for_the_release_key(self):
        # #651: pasted as a block, the check must print no checksum result after a failed signature or one
        # by another key, even one already in the reader's keyring. The block is run as a paste runs it.
        def site(name: str, fpr: str, key: str) -> Path:
            values = build_site.release_values(self.source(name, "159.0.1-0.1", fpr, key))
            built = self.tmp / f"{name}-site"
            real = build_site.release_values
            build_site.release_values = lambda src: values
            try:
                build_site.build(built)
            finally:
                build_site.release_values = real
            return built

        out = site("manual-check", self.fpr, self.armored)
        other_home = self.tmp / "gnupg-other"
        if not other_home.exists():
            throwaway_key(other_home)
        other = subprocess.run(["gpg", "--homedir", str(other_home), "--batch", "--quiet", "--armor", "--export"],
                               capture_output=True, text=True, check=True).stdout  # fmt: skip
        other_secret = subprocess.run(["gpg", "--homedir", str(other_home), "--batch", "--quiet", "--pinentry-mode",
                                       "loopback", "--passphrase", "", "--armor", "--export-secret-keys"],
                                      capture_output=True, text=True, check=True).stdout  # fmt: skip
        self.assertIn("PRIVATE KEY BLOCK", other_secret)
        # The release key, then a block holding it and three bytes that are no OpenPGP packet.
        binary = subprocess.run(["gpg", "--homedir", str(self.tmp / "gnupg"), "--batch", "--export", self.fpr],
                                capture_output=True, check=True).stdout  # fmt: skip
        enarmored = subprocess.run(["gpg", "--batch", "--enarmor"], input=binary + b"\x01\x02\x03", env={
            "PATH": os.environ.get("PATH", os.defpath), "GNUPGHOME": str(self.tmp / "gnupg")},
            capture_output=True, check=True).stdout.decode("ascii")  # fmt: skip
        unreadable = self.armored + enarmored.replace("PGP ARMORED FILE", "PGP PUBLIC KEY BLOCK")
        # The case's precondition: gpg lists the release key alone, and then exits non-zero.
        listed = subprocess.run(["gpg", "--batch", "--show-keys", "--with-colons", "-"], input=unreadable,
                                capture_output=True, text=True, env={"PATH": os.environ.get("PATH", os.defpath),
                                "GNUPGHOME": str(self.tmp / "gnupg"), "LC_ALL": "C"})  # fmt: skip
        self.assertNotEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual([line.split(":")[0] for line in listed.stdout.splitlines() if line[:4] in ("pub:", "sec:")],
                         ["pub"], listed.stdout)  # fmt: skip

        def run(page: str, case: str, signer: Path, key: str, tamper: bool = False, keyring: str = "",
                built: Path = out, extra_sig: bool = False, shell: str = "bash", prelude: str = "") -> str:  # fmt: skip
            work = self.tmp / f"check-{case}-{page.split('/')[0]}-{shell}"
            home = work / "gnupg"
            home.mkdir(parents=True, mode=0o700)
            (work / "nulavio-packages.keys").write_text("the reader's own file\n", encoding="ascii")
            if key:
                (work / "nulavio-packages.asc").write_text(key, encoding="ascii")
            sums = work / "SHA256SUMS"

            def package(data: bytes) -> None:
                (work / "nulavio.rpm").write_bytes(data)
                sums.write_text(f"{hashlib.sha256(data).hexdigest()}  nulavio.rpm\n", encoding="ascii")

            package(b"the package\n")
            gpg = ["gpg", "--homedir", str(signer), "--batch", "--quiet", "--yes"]
            armor = [] if extra_sig else ["--armor"]  # binary signatures concatenate into one file
            subprocess.run([*gpg, *armor, "--detach-sign", "-o", str(work / "SHA256SUMS.asc"), str(sums)], check=True)
            if extra_sig:  # a second signature, over other bytes: gpg prints our VALIDSIG, then BADSIG, and exits 1
                other_sig = subprocess.run([*gpg, "--detach-sign", "-o", "-"], input=b"other bytes\n",
                                           capture_output=True, check=True).stdout  # fmt: skip
                with (work / "SHA256SUMS.asc").open("ab") as f:
                    f.write(other_sig)
            if tamper:  # another package, and the list changed to match it, under the old signature
                package(b"another package\n")
            env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(work), "GNUPGHOME": str(home), "LC_ALL": "C"}
            if keyring:
                subprocess.run(["gpg", "--batch", "--quiet", "--import"], input=keyring, text=True, env=env, check=True)
            html = (built / page).read_text(encoding="utf-8")
            block = re.search(r'<section id="verify".*?<code>(.*?)</code>', html, re.S).group(1)
            blocks.add(block)
            before = primary_keys(env)
            ran = subprocess.run([shell], input=prelude + html_module.unescape(block) + "\n", cwd=work, env=env,
                                 capture_output=True, text=True, timeout=60)  # fmt: skip
            keyrings[case, page, shell] = (before, primary_keys(env))
            # Review of #752: the block writes no file of its own, so a file the reader had keeps its content.
            self.assertEqual((work / "nulavio-packages.keys").read_text(encoding="ascii"), "the reader's own file\n")
            return ran.stdout

        def primary_keys(env: dict[str, str]) -> list[str]:
            """The fingerprints of the primary keys in the reader's keyring, in order."""
            listing = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"], env=env,
                                     capture_output=True, text=True).stdout  # fmt: skip
            lines = listing.splitlines()
            return [lines[i + 1].split(":")[9] for i, line in enumerate(lines)
                    if line.startswith("pub:") and i + 1 < len(lines) and lines[i + 1].startswith("fpr:")]  # fmt: skip

        blocks: set[str] = set()
        keyrings: dict[tuple[str, str, str], tuple[list[str], list[str]]] = {}
        # The block is pasted into bash, and into Fish where it is installed (test_the_manual_check_is_plain_commands).
        shells = ["bash", *(["fish"] if shutil.which("fish") else [])]
        for page, sh in itertools.product(build_site.DOWNLOAD_PAGES, shells):
            with self.subTest(page=page, shell=sh):
                ours = self.tmp / "gnupg"
                self.assertIn("nulavio.rpm: OK", run(page, "good", ours, self.armored, shell=sh))
                # The key file is imported once its fingerprint matched, and only then (#744).
                self.assertEqual(keyrings["good", page, sh], ([], [self.fpr]))
                if sh == "bash":  # Review of #752: with noclobber set, no redirection into a file stops the block.
                    self.assertIn("nulavio.rpm: OK", run(page, "noclobber", ours, self.armored, prelude="set -o noclobber\n"))
                # Signed by a key the reader already has: gpg says "Good signature", the list is still not ours.
                self.assertNotIn("nulavio.rpm", run(page, "foreign", other_home, self.armored, keyring=other, shell=sh))
                # The key file swapped for another one, with that key's signature.
                self.assertNotIn("nulavio.rpm", run(page, "swapped", other_home, other, shell=sh))
                # #744: the swapped key is not imported, so the reader's keyring stays as it was: empty, ...
                self.assertEqual(keyrings["swapped", page, sh], ([], []))
                # ... or holding the release key already.
                self.assertNotIn("nulavio.rpm", run(page, "swapped-with-key", other_home, other, keyring=self.armored,
                                                    shell=sh))  # fmt: skip
                self.assertEqual(keyrings["swapped-with-key", page, sh], ([self.fpr], [self.fpr]))
                # #744: the release key with another key beside it in the file: the block stops before the import.
                self.assertNotIn("nulavio.rpm", run(page, "bundled", ours, self.armored + other, shell=sh))
                self.assertEqual(keyrings["bundled", page, sh], ([], []))
                # Review of #752: a secret key beside the release key is listed as "sec", not "pub"; in either order
                # it stops the block, and neither key reaches the keyring.
                secret_cases = (("bundled-secret", self.armored + other_secret), ("secret-first", other_secret + self.armored))
                for case, key in secret_cases:
                    self.assertNotIn("nulavio.rpm", run(page, case, ours, key, shell=sh))
                    self.assertEqual(keyrings[case, page, sh], ([], []))
                # Review of #752: gpg lists the release key, then fails on the rest of the file. The listing's exit
                # status stops the block too, as it did before #744; awk alone would have passed it.
                self.assertNotIn("nulavio.rpm", run(page, "unreadable", ours, unreadable, shell=sh))
                self.assertEqual(keyrings["unreadable", page, sh], ([], []))
                # The list changed after it was signed.
                self.assertNotIn("nulavio.rpm", run(page, "tampered", ours, self.armored, tamper=True, shell=sh))
                # gpg found our valid signature but failed on another one, and exited non-zero.
                self.assertNotIn("nulavio.rpm", run(page, "gpg-failed", ours, self.armored, extra_sig=True, shell=sh))
                # No key file: the key setup fails, and the block stops there, even with the key already in the keyring.
                self.assertNotIn("nulavio.rpm", run(page, "no-key-file", ours, "", keyring=self.armored, shell=sh))
        self.assertEqual(len(blocks), 1, "both languages give the same commands")

        # A key that signs with a subkey: VALIDSIG names the subkey first and the pinned primary key last.
        sub_home = self.tmp / "gnupg-subkey"
        sub_home.mkdir(mode=0o700)
        gpg = ["gpg", "--homedir", str(sub_home), "--batch", "--quiet", "--passphrase", ""]
        subprocess.run([*gpg, "--quick-generate-key", "Throwaway <s@example.invalid>", "ed25519", "cert", "1d"], check=True)
        listing = subprocess.run([*gpg, "--with-colons", "--list-keys"], capture_output=True, text=True, check=True).stdout
        primary = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        subprocess.run([*gpg, "--quick-add-key", primary, "ed25519", "sign", "1d"], check=True)
        sub_key = subprocess.run([*gpg, "--armor", "--export", primary], capture_output=True, text=True, check=True).stdout
        sub_site = site("manual-check-subkey", primary, sub_key)
        for page in build_site.DOWNLOAD_PAGES:
            with self.subTest(page=page, signer="subkey"):
                self.assertIn("nulavio.rpm: OK", run(page, "subkey", sub_home, sub_key, built=sub_site))


if __name__ == "__main__":
    unittest.main()
