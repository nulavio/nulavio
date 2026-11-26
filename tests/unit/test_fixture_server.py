"""The fixture server's `/page/<name>?frame=<address>` holds a frame with that address, as given (#709)."""

from __future__ import annotations

import html.parser
import sys
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import harness  # noqa: E402


class _Frames(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.srcs.append(dict(attrs)["src"])


class PageFrameTest(unittest.TestCase):
    def setUp(self):
        self.server = object.__new__(harness.FixtureServer)  # only route() is used: no socket is opened
        self.server.port = 1

    def frames(self, address: str) -> tuple[list[str], bytes | None]:
        body, _ctype, _extra = self.server.route("/page/home?" + urllib.parse.urlencode({"frame": address}))
        if body is None:
            return [], None
        parser = _Frames()
        parser.feed(body.decode())
        return parser.srcs, body

    def test_the_frame_has_the_address_it_was_given(self):
        for address in (
            "http://127.0.0.1:1/login",
            "http://127.0.0.1:1/login#field",
            "http://127.0.0.1:1/a%2Fb?x=1&y=two+words%20here",
            'https://localhost:1/page/x?q="<b>"&amp=1',
        ):
            with self.subTest(address=address):
                srcs, body = self.frames(address)
                self.assertEqual(srcs, [address])
                self.assertNotIn(b'"<b>"', body)  # the attribute holds: quotes and brackets are escaped

    def test_a_page_without_frame_has_none(self):
        body, _ctype, _extra = self.server.route("/page/home")
        self.assertNotIn(b"<iframe", body)

    def test_an_address_that_is_not_http_or_https_is_refused(self):
        refused = ("javascript:alert(1)", "JavaScript:alert(1)", "\tjavascript:alert(1)", " javascript:x", "data:text/html,x")
        for address in refused:
            with self.subTest(address=address):
                srcs, body = self.frames(address)
                self.assertIsNone(body)  # the route's 404, not a page without its frame
                self.assertEqual(srcs, [])


if __name__ == "__main__":
    unittest.main()
