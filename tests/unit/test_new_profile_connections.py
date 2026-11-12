"""The page that lists what a new profile contacts by itself and the list the integration test reads name the same hosts."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import connections  # noqa: E402

HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
# Adding one of these to the list is a decision about a protection, not a list update: each is switched off on purpose.
NEVER_LISTED = {
    "incoming.telemetry.mozilla.org": "telemetry is off in both tracks",
    "normandy.cdn.mozilla.net": "studies are off in both tracks",
    "location.services.mozilla.com": "no region lookup at Mozilla's location service",
    "update.googleapis.com": "no question to Google's update service about a DRM module that is off",
    "edgedl.me.gvt1.com": "where that question was redirected on the day of the record",
}


class NewProfileConnectionsListTest(unittest.TestCase):
    def setUp(self):
        self.entries = connections.entries()

    def every_host(self) -> set[str]:
        hosts = set()
        for entry in self.entries:
            hosts.update(entry["hosts"], entry.get("mirrors_not_recorded", []))
            for by_language in entry.get("hosts_by_language", {}).values():
                hosts.update(by_language)
        return hosts

    def test_the_list_is_well_formed(self):
        ids = [entry["id"] for entry in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in self.entries:
            with self.subTest(entry["id"]):
                self.assertIn(entry["by"], ("engine", "uBlock Origin"))
                self.assertIn(entry.get("scheme", "https"), ("https", "http"))
                self.assertTrue(entry["hosts"])
                names = [*entry["hosts"], *entry.get("mirrors_not_recorded", []), *entry.get("names_only", [])]
                for language, hosts in entry.get("hosts_by_language", {}).items():
                    self.assertRegex(language, r"^[a-z]{2}$")
                    names += hosts
                for name in names:
                    self.assertRegex(name, HOST)

    def test_only_the_network_check_is_plain_http(self):
        plain = [entry["id"] for entry in self.entries if entry.get("scheme", "https") != "https"]
        self.assertEqual(plain, ["network-check"])

    def test_the_page_and_the_list_name_the_same_hosts(self):
        page = connections.PAGE.read_text(encoding="utf-8")
        table = page.split("## The list", 1)[1].split("\n## ", 1)[0]
        rows = [line for line in table.splitlines() if line.startswith("| `")]
        self.assertEqual(len(rows), len(self.entries))
        in_page = set()
        for row in rows:
            in_page.update(re.findall(r"`([^`]+)`", row.split("|")[1]))
        self.assertEqual(in_page, self.every_host())
        for entry in self.entries:
            for name in entry.get("names_only", []):
                self.assertIn(f"`{name}`", table)

    def test_hosts_switched_off_on_purpose_are_not_listed(self):
        addresses, names = connections.allowed("pt")
        every = self.every_host() | names | {host for _, host in addresses}
        for host, why in NEVER_LISTED.items():
            with self.subTest(host):
                self.assertNotIn(host, every, why)


if __name__ == "__main__":
    unittest.main()
