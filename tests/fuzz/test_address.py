"""Fuzzing the AI Bridge's address classifier (launcher/nulavio_launcher/ai/policy.py, #149).

Every address an agent asks for is classified before the engine opens it: either refused
(UrlRefused) or given the capabilities it needs. Whatever the address, the classifier never fails
another way, and its reading of a host agrees with the engine's rules where they can be checked
here: an IPv4 host in any of the forms the WHATWG URL parser reads (decimal, octal, hex, fewer
parts) is the same address as Python's ipaddress reads from the dotted form, and a private,
loopback or link-local one needs `local_resources`.

    python3 -I tests/run.py fuzz test_address.py      # needs requirements/fuzz.txt
"""

from __future__ import annotations

import ipaddress
import os
import unittest

from hypothesis import example, given, settings
from hypothesis import strategies as st

from nulavio_launcher.ai.policy import UrlRefused, classify_url

EXAMPLES = int(os.environ.get("NULAVIO_FUZZ_EXAMPLES", "300"))
SCHEMES = st.sampled_from(["http", "https", "HTTP", "about", "view-source", "javascript", "file", "moz-extension", "ftp", ""])
HOSTISH = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-[]:%@\\xX", max_size=40)


def ipv4_forms(address: ipaddress.IPv4Address) -> list[str]:
    """Ways the WHATWG parser reads the same IPv4 address."""
    n = int(address)
    a, b, c, d = address.packed
    return [str(address), str(n), hex(n), f"{a}.{(b << 16) | (c << 8) | d}", f"{a}.{b}.{(c << 8) | d}", f"0{a:o}.{b}.{c}.{d}"]


class AddressFuzzTest(unittest.TestCase):
    @settings(max_examples=EXAMPLES, deadline=None)
    @given(url=st.text(max_size=200))
    @example("http://[::1")
    @example("http://0x7f.1/")
    @example("view-source:view-source:http://127.0.0.1/")
    def test_any_text_is_classified_or_refused(self, url):
        try:
            classify_url(url, resolve=False)
        except UrlRefused:
            pass

    @settings(max_examples=EXAMPLES, deadline=None)
    @given(scheme=SCHEMES, host=HOSTISH, rest=st.text(max_size=30))
    def test_address_shaped_text_is_classified_or_refused(self, scheme, host, rest):
        try:
            classify_url(f"{scheme}://{host}/{rest}", resolve=False)
        except UrlRefused:
            pass

    @settings(max_examples=EXAMPLES, deadline=None)
    @given(address=st.ip_addresses(v=4), form=st.integers(min_value=0, max_value=5))
    def test_an_ipv4_host_in_any_form_is_that_address(self, address, form):
        host = ipv4_forms(address)[form]
        target = classify_url(f"http://{host}/", resolve=False)
        self.assertEqual(target.host, str(address), host)
        local = address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified
        if local:
            self.assertIn("local_resources", target.needs, f"{host} is {address}, on this computer or the local network")


if __name__ == "__main__":
    unittest.main()
