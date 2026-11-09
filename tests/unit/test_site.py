"""nulavio.net static site: no scripts or third parties, strict headers, honest copy."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import shutil
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

PAGES = ["index.html", "en/index.html", "404.html"]
LANDING = {"index.html": "pt-BR", "en/index.html": "en-US"}
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

    def test_local_references_resolve(self):
        for page in PAGES:
            html = (self.out / page).read_text(encoding="utf-8")
            for ref in re.findall(r'(?:src|href|srcset)="(/[^"]*)"', html):
                target = ref.lstrip("/")
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
        pt = (self.out / "index.html").read_text(encoding="utf-8")
        en = (self.out / "en/index.html").read_text(encoding="utf-8")
        self.assertIn("não é afiliado à Mozilla", pt)
        self.assertIn("not affiliated with Mozilla", en)
        self.assertIn("Em desenvolvimento", pt)
        self.assertIn("In development", en)
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
        ids = {page: [n.attrs["id"] for n in self.tree(page).all() if "id" in n.attrs] for page in LANDING}
        pt, en = ids.values()
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
            signoff = next((n for n in tree.all() if n.attrs.get("id") == "signoff"), None)
            decorative = {id(n) for n in signoff.walk()} if signoff else set()
            for img in tree.all("img"):
                with self.subTest(page=page, src=img.attrs.get("src")):
                    self.assertIn("alt", img.attrs)
                    if id(img) in decorative:
                        self.assertEqual(img.attrs["alt"], "", "the sign-off symbol is decorative")
                    else:
                        self.assertTrue(img.attrs["alt"].strip())

    def test_figures_tables_and_scroll_regions_are_labelled(self):
        for page in LANDING:
            tree = self.tree(page)
            with self.subTest(page=page):
                figures = tree.all("figure")
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
        for page, locale in LANDING.items():
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
        for page in LANDING:
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
        for scheme, values in (("light", light), ("dark", dark)):
            for pairs, minimum in ((text_pairs, 4.5), (border_pairs, 3.0)):
                for fg, bg in pairs:
                    with self.subTest(scheme=scheme, fg=fg, bg=bg):
                        value = ratio(values[f"--nv-color-{fg}"], values[f"--nv-color-{bg}"])
                        self.assertGreaterEqual(value, minimum)
        site_css = (ROOT / "site" / "site.css").read_text(encoding="utf-8")
        self.assertNotRegex(site_css, r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", "site.css takes every colour from the tokens")


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
        return src

    def test_no_release_no_download_pages(self):
        self.assertIsNone(build_site.release_values(self.source("none", "", "", None)))
        self.assertIsNone(build_site.release_values(self.source("no-key", "159.0.1-0.1", "", None)))
        out = self.tmp / "unreleased"
        files = build_site.build(out)
        for page in build_site.DOWNLOAD_PAGES:
            self.assertNotIn(page, files)
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
                self.assertIn("dnf config-manager addrepo --from-repofile=https://packages.nulavio.net/rpm/nulavio.repo", html)
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
