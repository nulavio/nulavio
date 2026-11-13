"""Search discovery uses the pages that are actually published, never private link pages."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from test_site import Tree, build_site

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
BASE = "https://nulavio.net/"


class DiscoveryTest(unittest.TestCase):
    def test_sitemap_lists_only_published_canonical_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            build_site.build(out)
            sitemap = ET.parse(out / "sitemap.xml")
            urls = [n.text for n in sitemap.findall("s:url/s:loc", NS)]
            expected = {BASE + p for p in ("", "en/", "lista/", "en/waitlist/", "engenharia/", "en/engineering/")}
            if (out / "baixar/index.html").exists():
                expected |= {BASE + "baixar/", BASE + "en/download/"}
            self.assertEqual(set(urls), expected)
            self.assertEqual(len(urls), len(expected))
            alternatives = {}
            for entry in sitemap.findall("s:url", NS):
                url = entry.find("s:loc", NS).text
                alternatives[url] = {a.attrib["hreflang"]: a.attrib["href"] for a in entry.findall("x:link", NS)}
                self.assertEqual(set(alternatives[url]) - {"x-default"}, {"pt-BR", "en"})
                for target in alternatives[url].values():
                    self.assertIn(target, expected)
            for group in alternatives.values():
                for target in group.values():
                    self.assertEqual(alternatives[target], group, "language links must be reciprocal")
            self.assertIn("Sitemap: https://nulavio.net/sitemap.xml", (out / "robots.txt").read_text())

    def test_sitemap_omits_downloads_before_a_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build_site, "release_values", return_value=None):
            out = Path(tmp) / "site"
            build_site.build(out)
            urls = {n.text for n in ET.parse(out / "sitemap.xml").findall("s:url/s:loc", NS)}
            self.assertNotIn(BASE + "baixar/", urls)
            self.assertNotIn(BASE + "en/download/", urls)
            self.assertEqual(len(urls), 6)

    def test_sitemap_respects_noindex_even_when_a_page_has_a_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "index.html").write_text('<head><link rel="canonical" href="https://nulavio.net/"></head>')
            (out / "private.html").write_text(
                '<head><meta name="robots" content="FOLLOW, NOINDEX">'
                '<link rel="canonical" href="https://nulavio.net/private.html"></head>'
            )
            build_site.write_sitemap(out, {"index.html": "pt-BR", "private.html": "pt-BR"})
            self.assertEqual([n.text for n in ET.parse(out / "sitemap.xml").findall("s:url/s:loc", NS)], [BASE])

    def test_sitemap_refuses_offsite_canonicals_and_unpublished_translations(self):
        cases = [
            '<link rel="canonical" href="https://example.org/">',
            '<link rel="canonical" href="https://nulavio.net/">'
            '<link rel="alternate" hreflang="en" href="https://nulavio.net/missing/">',
        ]
        for head in cases:
            with self.subTest(head=head), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "index.html").write_text(f"<head>{head}</head>")
                with self.assertRaises(build_site.BuildError):
                    build_site.write_sitemap(out, {"index.html": "pt-BR"})

    def test_faq_answers_and_software_are_machine_readable_without_scripts(self):
        for page in ("index.html", "en/index.html"):
            tree = Tree((build_site.ROOT / "site" / page).read_text())
            websites = [n for n in tree.all() if n.attrs.get("itemtype") == "https://schema.org/WebSite"]
            self.assertEqual(len(websites), 1, page)
            descriptions = [
                n.attrs["content"]
                for n in tree.all("meta")
                if n.attrs.get("name") in {"description", "twitter:description"} or n.attrs.get("property") == "og:description"
            ]
            self.assertEqual(len(descriptions), 3)
            self.assertEqual(len(set(descriptions)), 1)
            software = [n for n in tree.all() if n.attrs.get("itemtype") == "https://schema.org/SoftwareApplication"]
            self.assertEqual(len(software), 1, page)
            self.assertTrue(any(n.attrs.get("itemprop") == "description" and n.text().strip() for n in software[0].walk()))
            faq = [n for n in tree.all() if n.attrs.get("itemtype") == "https://schema.org/FAQPage"]
            self.assertEqual(len(faq), 1, page)
            questions = [n for n in faq[0].walk() if n.attrs.get("itemtype") == "https://schema.org/Question"]
            self.assertEqual(len(questions), len(tree.all("details")), page)
            for question in questions:
                self.assertEqual(question.attrs.get("itemprop"), "mainEntity")
                self.assertTrue(question.attrs.get("id"))
                self.assertTrue(any(n.attrs.get("itemprop") == "name" and n.text().strip() for n in question.walk()))
                answers = [n for n in question.walk() if n.attrs.get("itemprop") == "acceptedAnswer"]
                self.assertEqual(len(answers), 1)
                self.assertEqual(answers[0].attrs.get("itemtype"), "https://schema.org/Answer")
                self.assertTrue(any(n.attrs.get("itemprop") == "text" and n.text().strip() for n in answers[0].walk()))
            self.assertEqual(tree.all("script"), [])


if __name__ == "__main__":
    unittest.main()
