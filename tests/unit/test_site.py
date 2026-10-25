"""nulavio.net static site: no scripts or third parties, strict headers, honest copy."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "site"))

import build_site  # noqa: E402

PAGES = ["index.html", "en/index.html", "404.html"]
SAME_SITE = "https://nulavio.net/"


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


if __name__ == "__main__":
    unittest.main()
