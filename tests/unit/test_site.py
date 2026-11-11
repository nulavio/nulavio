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

# The landing (what Nulavio is at launch, the comparison, the waitlist form), the waitlist pages and the
# engineering document ("Recibo": what is ready today, with captures and excerpts from the tree).
LANDING = {"index.html": "pt-BR", "en/index.html": "en-US"}
WAITLIST = {"lista/index.html": "pt-BR", "en/waitlist/index.html": "en-US"}
DOCUMENT = {"engenharia/index.html": "pt-BR", "en/engineering/index.html": "en-US"}
PAGES = [*LANDING, *WAITLIST, *DOCUMENT, "404.html"]
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
        for pages in (LANDING, WAITLIST, DOCUMENT):
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
        for page in (*LANDING, *WAITLIST, *DOCUMENT):
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
                self.assertEqual(len(forms), 2)
                labelled = {n.attrs.get("for") for n in tree.all("label")}
                for form in forms:
                    self.assertEqual((form.attrs.get("action"), form.attrs.get("method")), ("/api/waitlist", "post"))
                    fields = {n.attrs.get("name"): n for n in form.walk() if n.tag in ("input", "select")}
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
        states = set(re.findall(r'redirect\(lang, (?:leaving \? )?"(\w+)"(?: : "(\w+)")?\)', worker))
        states = {s for pair in states for s in pair if s}
        self.assertEqual(states, {"ok", "left", "invalid", "unavailable"})
        targets = dict(re.findall(r'"?([\w-]+)"?: "(/[\w/]+/)"', re.search(r"const PAGES = \{(.*?)\}", worker).group(1)))
        self.assertEqual(targets, {"pt-BR": "/lista/", "en": "/en/waitlist/"})
        for (page, locale), target in zip(WAITLIST.items(), (targets["pt-BR"], targets["en"]), strict=True):
            tree = self.tree(page)
            with self.subTest(page=page):
                self.assertEqual(target.strip("/") + "/index.html", page)
                notices = {n.attrs.get("id") for n in tree.all() if "notice" in n.classes()}
                self.assertEqual(notices, states, "one message for each answer of site/_worker.js")
                ids = {n.attrs.get("id") for n in tree.all()}
                self.assertLessEqual({"data", "leave"}, ids, "what is kept and how to leave, linked from the landing")
                fields = [
                    {n.attrs.get("name"): n.attrs.get("value") for n in f.walk() if n.tag == "input"} for f in tree.all("form")
                ]
                leave = [f for f in fields if f.get("action") == "leave"]
                self.assertEqual(len(leave), 1)
                self.assertEqual(leave[0]["lang"], FORM_LANG[locale])
        css = (ROOT / "site" / "landing.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.notice \{[^}]*display: none", "a message shows only when its fragment is the target")
        self.assertIn(".notice:target", css)

    def test_only_the_api_reaches_the_worker(self):
        routes = json.loads((self.out / "_routes.json").read_text(encoding="utf-8"))
        self.assertEqual(routes, {"version": 1, "include": ["/api/*"], "exclude": []})
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

    @classmethod
    def setUpClass(cls):
        driver = ROOT / "tests" / "lib" / "waitlist_worker_driver.mjs"
        done = subprocess.run(["node", str(driver), str(WORKER)], capture_output=True, text=True, timeout=60, check=True)
        cls.cases = json.loads(done.stdout)

    def rows(self, *names: str) -> list[tuple]:
        """The table after the statements of these cases ran, in order, in SQLite (what D1 runs)."""
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        for name in names:
            for statement in self.cases[name]["statements"]:
                db.execute(statement["sql"], statement["args"])
        return db.execute("SELECT email, lang, platform, joined FROM waitlist ORDER BY joined, email").fetchall()

    def test_join_keeps_the_address_the_language_the_platform_and_the_time(self):
        self.assertEqual((self.cases["join"]["status"], self.cases["join"]["location"]), (303, "/lista/#ok"))
        ((email, lang, platform, joined),) = self.rows("join")
        self.assertEqual((email, lang, platform), ("Ana@Example.org", "pt-BR", "fedora"))
        self.assertRegex(joined, r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(len(self.cases["join"]["statements"][-1]["args"]), 4, "nothing else is stored: no IP, no user agent")

    def test_joining_twice_is_one_sign_up_that_keeps_its_place(self):
        first = self.rows("join")
        again = self.rows("join", "join_again_other_case")
        self.assertEqual(len(again), 1, "the same address in another letter case is the same sign-up")
        self.assertEqual(again[0][3], first[0][3], "the first date stays: it is the place in line")
        self.assertEqual(again[0][1:3], ("en", "fedora"), "the language follows the last form; a platform given is not erased")
        self.assertEqual(self.cases["join_again_other_case"]["location"], "/en/waitlist/#ok", "same answer as a new sign-up")

    def test_leaving_deletes_and_answers_the_same_for_an_unknown_address(self):
        self.assertEqual(self.rows("join", "leave"), [])
        self.assertEqual(len(self.rows("join", "leave_absent")), 1)
        self.assertEqual(self.cases["leave"]["location"], "/en/waitlist/#left")
        self.assertEqual(self.cases["leave_absent"]["location"], "/lista/#left")

    def test_values_are_bound_and_unknown_ones_fall_back(self):
        rows = self.rows("join", "join_unknown_platform", "unknown_lang")
        kept = {(email, lang, platform) for email, lang, platform, _ in rows}
        self.assertEqual(
            kept, {("Ana@Example.org", "pt-BR", "fedora"), ("bruno@example.org", "en", ""), ("carla@example.org", "pt-BR", "")}
        )
        self.assertEqual(self.cases["unknown_lang"]["location"], "/lista/#ok", "the redirect never follows the form's own text")
        for case in self.cases.values():
            for statement in case["statements"]:
                self.assertNotIn("example.org", statement["sql"], "addresses travel as bound parameters")

    def test_what_is_refused_stores_nothing(self):
        expected = {
            "invalid_email": (303, "/en/waitlist/#invalid"),
            "no_dot_in_domain": (303, "/lista/#invalid"),
            "too_long_email": (303, "/lista/#invalid"),
            "honeypot": (303, "/en/waitlist/#ok"),  # a bot is told it worked
            "cross_site": (403, None),
            "wrong_content_type": (415, None),
            "too_large": (413, None),
            "get": (405, None),
            "no_database": (303, "/en/waitlist/#unavailable"),
            "database_down": (303, "/lista/#unavailable"),
        }
        for name, (status, location) in expected.items():
            case = self.cases[name]
            with self.subTest(case=name):
                self.assertEqual((case["status"], case["location"]), (status, location))
                self.assertEqual(case["statements"], [])
        self.assertEqual(self.cases["get"]["headers"].get("allow"), "POST")
        self.assertEqual(self.cases["no_fetch_metadata"]["location"], "/en/waitlist/#ok", "an older browser still gets in")

    def test_answers_carry_their_own_headers(self):
        for name in ("join", "invalid_email", "cross_site", "get"):
            headers = self.cases[name]["headers"]
            with self.subTest(case=name):
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertEqual(headers["referrer-policy"], "no-referrer")
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                self.assertIn("default-src 'none'", headers["content-security-policy"])

    def test_other_paths_fall_through_to_the_static_files(self):
        self.assertEqual((self.cases["other_api_path"]["status"], self.cases["other_api_path"]["body"]), (404, "the 404 page"))


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

    def source(self, name: str, version: str, fpr: str, key: str | None) -> Path:
        src = self.tmp / name
        (src / "packaging").mkdir(parents=True)
        release = json.loads((ROOT / "packaging" / "release.json").read_text(encoding="utf-8"))
        release.update(version=version, key_fingerprint=fpr)
        (src / "packaging" / "release.json").write_text(json.dumps(release), encoding="utf-8")
        if key is not None:
            (src / build_site.PUBLIC_KEY).parent.mkdir(parents=True)
            (src / build_site.PUBLIC_KEY).write_text(key, encoding="utf-8")
        (src / build_site.REPO_FILE).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / build_site.REPO_FILE, src / build_site.REPO_FILE)
        return src

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
