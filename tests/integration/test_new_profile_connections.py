"""A new profile left alone asks only for what docs/security/new-profile-connections.md lists.

No setting says what the browser contacts by itself: the page was written from a record, and every engine or content
blocker update can add to it unseen (the region lookup and the question to Google's update service were both found by
chance). This starts a new profile with the engine's own network log on from the first moment of the process, waits
for the start-up work the record shows (the last of it was a second network check, a minute in) and compares every
address asked for and every name resolved with the list. It reaches the real services, like a person's first start,
and needs them: offline the engine does not ask Remote Settings at all, and the test then says it could not measure.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import connections
import harness

SETTLE = 75  # seconds: the record's last start-up request is at 61 s


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class NewProfileConnectionsTest(unittest.TestCase):
    def test_01_a_new_profile_left_alone_asks_only_for_what_the_page_lists(self):
        session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(session.cleanup)
        session.env["MOZ_LOG"] = connections.ENGINE_LOG
        session.env["MOZ_LOG_FILE"] = str(session.tmp / "engine")
        started = time.monotonic()
        session.start()
        time.sleep(max(0.0, SETTLE - (time.monotonic() - started)))
        session.stop()
        addresses, names = connections.read_log(session.tmp)
        language = os.environ.get("NULAVIO_TEST_LANG", "pt_BR.UTF-8")[:2]
        listed, names_only = connections.allowed(language)
        asked = {(urlsplit(a).scheme, urlsplit(a).hostname): a for a in reversed(addresses)}  # the first address of each
        # The measurement sees the engine's work: Remote Settings is asked at every first start, and the second
        # network check is the last thing the record shows.
        # What the test needs before it can say anything, told apart from a finding.
        needs = "could not measure (this is not an unlisted address): "
        remote_settings = ("https", "firefox.settings.services.mozilla.com")
        self.assertIn(remote_settings, asked, needs + "the engine asked nothing of Remote Settings; is the network reachable?")
        unlisted = sorted(connections.without_query(address) for key, address in asked.items() if key not in listed)
        self.assertEqual(unlisted, [], "asked for by a new profile and not in docs/security/new-profile-connections.json")
        hosts = {host for _, host in listed}
        self.assertEqual(sorted(set(names) - hosts - names_only), [], "resolved by a new profile and not in the list")


if __name__ == "__main__":
    unittest.main()
