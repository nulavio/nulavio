"""Engine security fast path: advisories, the watcher, the issue, the bump, the autobuild (no network)."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import autobuild  # noqa: E402
import bump_engine  # noqa: E402
import fetch_firefox_source  # noqa: E402
import mfsa  # noqa: E402
import upstream_issue  # noqa: E402
import watch_upstream  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "upstream"
D158 = "b5beff55fa73a29a674a867da5922f5d7699f51e351e6bbe4405fcc4ba55a824"  # Mozilla's signed digests (2026-10-27)
D159 = "3d98df785894057fce60603e845828e758a5411ad79aaaaff2b8230597f500d9"
SUBKEY = "827E658608679618CD349F93678E455D76767AA3"
UTC = dt.UTC
_PATCHES: list = []


def setUpModule():
    """Unit tests never reach the network: any attempt fails loudly."""

    def refuse(*args, **kwargs):
        raise AssertionError("unit tests must not use the network")

    for target in ("urllib.request.urlopen", "urllib.request.OpenerDirector.open", "socket.socket.connect"):
        patcher = mock.patch(target, side_effect=refuse)
        patcher.start()
        _PATCHES.append(patcher)


def tearDownModule():
    while _PATCHES:
        _PATCHES.pop().stop()


def at(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def advisory(name: str) -> mfsa.Advisory:
    return mfsa.parse(fixture(f"mfsa/{name}"), name)


def offline_tree(tmp: Path, *, drop=(), latest=None, staged=(), verified=None, hide=(), extra=None, no_clock=False) -> Path:
    """A copy of the recorded responses, adjusted per test (watch_upstream.Offline layout)."""
    root = tmp / "offline"
    shutil.copytree(FIXTURES, root, ignore=shutil.ignore_patterns("synthetic", "SOURCE.md"))
    details = root / "product-details"
    for name in watch_upstream.SOURCES:
        history = json.loads((details / name).read_text())
        (details / name).write_text(json.dumps({k: v for k, v in history.items() if k not in drop}))
    if latest:
        versions = json.loads((details / "firefox_versions.json").read_text())
        versions["LATEST_FIREFOX_VERSION"] = latest
        (details / "firefox_versions.json").write_text(json.dumps(versions))
    for version in staged:
        (root / "archive" / version).mkdir(parents=True, exist_ok=True)
        (root / "archive" / version / "SHA256SUMS.asc").write_text("signature")
    for version, answer in (verified or {}).items():
        (root / "archive" / version).mkdir(parents=True, exist_ok=True)
        data = {"error": answer} if isinstance(answer, str) else {"source_sha256": answer[0], "signing_subkey": answer[1]}
        (root / "archive" / version / "verified.json").write_text(json.dumps(data))
    listing_path = root / "github" / "announce" / "2026.json"
    listing = [item for item in json.loads(listing_path.read_text()) if item["name"] not in hide]
    for name, text in (extra or {}).items():
        (root / "mfsa" / name).write_text(text)
        listing.append({"name": name, "type": "file"})
    listing_path.write_text(json.dumps(listing))
    if no_clock:
        shutil.rmtree(root / "github" / "commits")
    return root


def report_for(tmp: Path, now: str, *, pinned="158.0.1", digest=D158, verify=True, **tree) -> dict:
    verified = {"158.0.1": (D158, SUBKEY), "159.0": (D159, SUBKEY), **tree.pop("verified", {})}
    src = watch_upstream.Offline(offline_tree(tmp, verified=verified, **tree))
    return watch_upstream.check(pinned=pinned, pinned_sha256=digest, src=src, now=at(now), verify=verify)


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nulavio-fastpath-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# --- Mozilla's advisories (mfsa.py) ----------------------------------------------------


class AdvisoryReaderTest(unittest.TestCase):
    def test_parser_reads_each_fixture(self):
        for path in sorted((FIXTURES / "mfsa").glob("*.yml")):
            with self.subTest(advisory=path.name):
                text = path.read_text(encoding="utf-8")
                parsed = mfsa.parse(text, path.name)
                self.assertEqual(len(parsed.cves), len(re.findall(r"(?m)^  CVE-", text)))
                self.assertTrue(parsed.fixed_in and parsed.title and all(cve.title for cve in parsed.cves))
                self.assertIn(parsed.impact, mfsa.IMPACTS)

    def test_parser_handles_quoting_folding_and_comments(self):
        parsed = mfsa.parse(fixture("synthetic/quoted-title.yml"), "mfsa2026-901.yml")
        self.assertEqual(parsed.title, "Security Vulnerabilities fixed in Firefox 159.0.1 (the 'quoted' one)")
        self.assertEqual(parsed.description, "A folded description on two lines.\n")
        self.assertEqual([cve.title for cve in parsed.cves], ['Spoofing in the "Downloads" panel', "Plain title"])
        self.assertIn("Only a note", parsed.cves[0].text)

    def test_announced_dates_in_every_form(self):
        self.assertEqual(
            mfsa.parse(fixture("synthetic/announced-ordinal.yml"), "mfsa2025-903.yml").announced, dt.date(2025, 12, 18)
        )
        self.assertEqual(mfsa.parse_announced("Sep 3, 2024", "x"), dt.date(2024, 9, 3))
        self.assertEqual(mfsa.parse_announced("October 06, 2026", "x"), dt.date(2026, 10, 6))
        with self.assertRaises(mfsa.MfsaFormatError):
            mfsa.parse_announced("2026-10-27", "x")

    def test_malformed_advisory_fails_closed_to_urgent(self):
        with self.assertRaises(mfsa.MfsaFormatError):
            mfsa.parse(fixture("synthetic/malformed-missing-impact.yml"), "mfsa2026-902.yml")
        for bad in ("announced: [x]\n", "impact: high\n\tfixed_in: x\n", "title: 'open\n", "- a list\n"):
            with self.subTest(text=bad), self.assertRaises(mfsa.MfsaFormatError):
                mfsa.parse(bad, "mfsa2026-903.yml")
        verdict = mfsa.classify([], released_by=at("2026-10-01T00:00:00"), now=at("2026-10-27T00:00:00"), error="unreadable")
        self.assertEqual((verdict.urgency, verdict.advisory_status), ("urgent", "unreadable"))
        verdict = mfsa.classify([], released_by=None, now=at("2026-10-27T00:00:00"), unavailable=True)
        self.assertEqual((verdict.urgency, verdict.advisory_status), ("urgent", "unavailable"))

    def test_mfsa_files_sort_numerically(self):
        names = ["mfsa2026-100.yml", "mfsa2026-99.yml", "mfsa2025-120.yml", "mfsa2026-9.yml"]
        self.assertEqual(
            sorted(names, key=mfsa.sort_key), ["mfsa2025-120.yml", "mfsa2026-9.yml", "mfsa2026-99.yml", "mfsa2026-100.yml"]
        )

    def test_major_matches_firefox_without_dot_zero(self):
        self.assertTrue(mfsa.applies_to(advisory("mfsa2026-106.yml"), "158.0"))
        self.assertTrue(mfsa.applies_to(advisory("mfsa2026-118.yml"), "159.0"))
        self.assertFalse(mfsa.applies_to(advisory("mfsa2026-118.yml"), "159.0.1"))
        self.assertTrue(mfsa.applies_to(advisory("mfsa2026-111.yml"), "158.0.1"))
        self.assertTrue(mfsa.applies_to(advisory("mfsa2024-51.yml"), "131.0.2"))  # several products in fixed_in

    def test_android_ios_esr_and_thunderbird_advisories_are_not_desktop_releases(self):
        self.assertFalse(mfsa.applies_to(advisory("mfsa2026-116.yml"), "158.0.2"))  # "Firefox 158.0.2" for Android
        self.assertFalse(mfsa.applies_to(advisory("mfsa2026-117.yml"), "156.1"))
        self.assertFalse(mfsa.applies_to(advisory("mfsa2026-112.yml"), "153.5.1"))
        self.assertFalse(mfsa.applies_to(advisory("mfsa2026-121.yml"), "159.0"))

    def test_itw_table(self):
        cases = {
            "We have had reports of this vulnerability being exploited in the wild.": "yes",
            "The original vulnerability was being exploited in the wild.": "yes",
            "We are aware of targeted attacks in the wild abusing this flaw.": "yes",
            "We have had reports of attacks in the wild abusing this flaw.": "yes",
            "We are aware of this issue being exploited in other products in the wild.": "yes",
            "Windows sandbox escape detected with the in-the-wild exploit": "yes",
            "We are aware that exploit code for this is public however we are not aware of any attacks in the wild"
            " abusing this flaw.": "no",
            "To the best of our understanding, this issue was not abused in the wild.": "no",
            "Researchers looked at in the wild samples.": "unclear",
            "A use-after-free in the Layout component.": "no",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(mfsa.itw(text), expected)

    def test_real_advisories_classify(self):
        now = at("2026-10-27T00:00:00")
        rows = {
            "mfsa2026-67.yml": ("urgent", "no", True, False),  # critical; public exploit; attacks in the wild denied
            "mfsa2024-51.yml": ("urgent", "yes", False, True),
            "mfsa2022-09.yml": ("urgent", "yes", False, True),
            "mfsa2023-40.yml": ("urgent", "yes", False, False),
            "mfsa2026-106.yml": ("urgent", "no", False, False),
            "mfsa2026-104.yml": ("standard", "no", False, False),
        }
        for name, (urgency, itw, public, emergency_escape) in rows.items():
            with self.subTest(advisory=name):
                verdict = mfsa.classify([advisory(name)], released_by=None, now=now)
                self.assertEqual((verdict.urgency, verdict.itw, verdict.public_exploit), (urgency, itw, public))
                if itw == "yes":
                    self.assertTrue(verdict.emergency)
                if emergency_escape:
                    self.assertTrue(verdict.sandbox_escape)

    def test_sandbox_escape_and_public_exploit_are_urgent_reasons(self):
        verdict = mfsa.classify([advisory("mfsa2026-106.yml")], released_by=None, now=at("2026-10-14T00:00:00"))
        self.assertIn("sandbox escape", verdict.reasons)
        verdict = mfsa.classify([advisory("mfsa2026-67.yml")], released_by=None, now=at("2026-07-15T00:00:00"))
        self.assertIn("exploit code is public", verdict.reasons)

    def test_moderate_only_is_standard(self):
        verdict = mfsa.classify(
            [advisory("mfsa2026-104.yml")], released_by=at("2026-10-06T13:00:00"), now=at("2026-10-07T00:00:00")
        )
        self.assertEqual(
            (verdict.urgency, verdict.max_impact, verdict.reasons), ("standard", "moderate", ("impact moderate only",))
        )

    def test_no_advisory_is_urgent_until_6_hours_after_release(self):
        released = at("2026-10-27T13:00:00")
        self.assertEqual(mfsa.classify([], released_by=None, now=released).urgency, "urgent")  # staged only
        self.assertEqual(mfsa.classify([], released_by=released, now=at("2026-10-27T18:59:00")).urgency, "urgent")
        later = mfsa.classify([], released_by=released, now=at("2026-10-27T19:00:00"))
        self.assertEqual((later.urgency, later.advisory_status), ("standard", "none"))

    def test_platform_note_never_lowers_urgency(self):
        verdict = mfsa.classify([advisory("mfsa2025-19.yml")], released_by=None, now=at("2025-03-28T00:00:00"))
        self.assertEqual(verdict.platform_notes, ("only affects Firefox on Windows",))
        self.assertEqual((verdict.urgency, verdict.itw), ("urgent", "yes"))


# --- the watcher (watch_upstream.py) ------------------------------------------------------


class WatcherTest(TempDirTest):
    def test_esr_lines_are_not_newer_releases(self):
        self.assertEqual(
            watch_upstream.status("153.0.4", {"153.1.0": "2026-08-18"}, at("2026-08-20T00:00:00"))["state"], "up-to-date"
        )
        self.assertEqual(
            watch_upstream.release_history({"153.1.0": "x", "153.5.1": "2026-10-20", "158.0.1": "2026-10-20"}),
            {"158.0.1": "2026-10-20"},
        )

    def test_next_candidates_cover_skipped_dot_numbers(self):
        self.assertEqual(watch_upstream.next_candidates("158.0.1", None), ["158.0.2", "158.0.3", "158.0.4", "159.0", "159.0.1"])
        self.assertEqual(
            watch_upstream.next_candidates("158.0.1", "159.0"), ["159.0.1", "159.0.2", "159.0.3", "160.0", "160.0.1"]
        )
        self.assertEqual(
            watch_upstream.next_candidates("159.0", "153.6.0esr"), ["159.0.1", "159.0.2", "159.0.3", "160.0", "160.0.1"]
        )

    def test_clock_uses_product_details_commit_time_else_midnight(self):
        commits = json.loads(fixture("github/commits/stability-2026-10-20.json"))
        self.assertEqual(
            watch_upstream.release_clock("2026-10-20", commits), (at("2026-10-20T13:07:39"), "product-details-commit")
        )
        self.assertEqual(watch_upstream.release_clock("2026-10-20", []), (at("2026-10-20T00:00:00"), "date"))
        other_day = [{"commit": {"committer": {"date": "2026-10-21T01:00:00Z"}}}, {"commit": {}}]
        self.assertEqual(watch_upstream.release_clock("2026-10-20", other_day)[1], "date")

    def test_published_release_has_a_24_hour_target_and_the_72_hour_deadline(self):
        report = report_for(self.tmp, "2026-10-27T15:00:00")
        self.assertEqual((report["state"], report["exit_code"], report["newer"]), ("pending", 0, ["159.0"]))
        (target,) = report["targets"]
        self.assertEqual((target["phase"], target["verified"], target["source_sha256"]), ("shipped", True, D159))
        self.assertEqual((target["released_at"], target["clock_source"]), ("2026-10-27T12:57:05Z", "product-details-commit"))
        self.assertEqual((target["urgency"], target["reasons"]), ("urgent", ["impact high", "sandbox escape"]))
        self.assertEqual((target["target"], target["target_hours"]), ("2026-10-28T12:57:05Z", 24))
        self.assertEqual((target["deadline"], target["deadline_hours"]), ("2026-10-30T12:57:05Z", 72))
        self.assertEqual([a["id"] for a in target["advisories"]], ["mfsa2026-118"])
        self.assertEqual((report["target"], report["deadline"]), (target["target"], target["deadline"]))
        self.assertTrue(report["pinned"]["verified"])
        self.assertIn("Target 2026-10-28 12:57:05 UTC (24 h", report["summary"])
        self.assertIn("deadline 2026-10-30 12:57:05 UTC (72 h", report["summary"])

    def test_target_missed_is_not_overdue_and_overdue_comes_at_72_hours(self):
        missed = report_for(self.tmp / "a", "2026-10-28T13:00:00")
        self.assertEqual((missed["state"], missed["exit_code"], missed["targets"][0]["target_missed"]), ("pending", 0, True))
        overdue = report_for(self.tmp / "b", "2026-10-30T13:00:00")
        self.assertEqual((overdue["state"], overdue["exit_code"], overdue["targets"][0]["overdue"]), ("overdue", 1, True))
        self.assertIn("OVERDUE", overdue["summary"])

    def test_without_the_commit_time_the_clock_starts_at_midnight(self):
        report = report_for(self.tmp, "2026-10-27T15:00:00", no_clock=True)
        target = report["targets"][0]
        self.assertEqual((target["clock_source"], target["target"]), ("date", "2026-10-28T00:00:00Z"))

    def test_staged_release_is_reported_before_publication(self):
        report = report_for(
            self.tmp,
            "2026-10-27T05:00:00",
            drop=("159.0",),
            latest="158.0.1",
            staged=("159.0",),
            hide=("mfsa2026-118.yml", "mfsa2026-121.yml"),
        )
        self.assertEqual((report["state"], report["exit_code"], report["newer"]), ("staged", 0, []))
        (target,) = report["targets"]
        self.assertEqual((target["phase"], target["staged"], target["verified"]), ("staged", True, True))
        self.assertEqual((target["urgency"], target["advisory_status"], target["target"]), ("urgent", "none-yet", None))
        self.assertIn("staged on archive.mozilla.org (signature verified)", report["summary"])

    def test_staged_requires_valid_signature(self):
        report = report_for(
            self.tmp / "a", "2026-10-27T15:00:00", staged=("159.0.1",), verified={"159.0.1": "signed by unexpected primary key X"}
        )
        bad = report["targets"][-1]
        self.assertEqual((bad["version"], bad["phase"], bad["verified"]), ("159.0.1", "unconfirmed", False))
        self.assertEqual((report["exit_code"], report["verification_failed"]), (3, True))
        self.assertIn("Nothing may be built", report["summary"])
        unchecked = report_for(self.tmp / "b", "2026-10-27T15:00:00", staged=("159.0.1",))  # no answer: network
        self.assertEqual((unchecked["targets"][-1]["phase"], unchecked["exit_code"]), ("unconfirmed", 0))
        self.assertTrue(any("could not run" in error for error in unchecked["errors"]))

    def test_pinned_digest_must_match_mozillas_signature(self):
        report = report_for(self.tmp, "2026-10-27T15:00:00", digest="0" * 64)
        self.assertEqual((report["exit_code"], report["pinned"]["verified"]), (3, False))
        self.assertIn("did NOT match", report["summary"])

    def test_unreadable_advisory_fails_closed(self):
        broken = fixture("synthetic/malformed-missing-impact.yml").replace("Firefox 158.0.1", "Firefox 159")
        report = report_for(self.tmp, "2026-10-27T15:00:00", extra={"mfsa2026-123.yml": broken})
        target = report["targets"][0]
        self.assertEqual((target["urgency"], target["advisory_status"], target["itw"]), ("urgent", "unreadable", "unknown"))

    def test_moderate_release_keeps_the_72_hour_target(self):
        report = report_for(
            self.tmp, "2026-10-07T00:00:00", pinned="157.0", digest=None, drop=("158.0", "158.0.1", "159.0"), latest="157.0.1"
        )
        target = report["targets"][0]
        self.assertEqual((target["version"], target["urgency"], target["target_hours"]), ("157.0.1", "standard", 72))
        self.assertEqual(target["target"], target["deadline"])

    def test_exit_codes_from_the_command_line(self):
        engine = self.tmp / "engine.json"
        engine.write_text(json.dumps({"firefox": "158.0.1", "source_sha256": D158}))
        verified = {"158.0.1": (D158, SUBKEY), "159.0": (D159, SUBKEY)}
        cases = {
            ("ok", "2026-10-27T15:00:00"): ({}, 0),
            ("overdue", "2026-10-30T13:00:00"): ({}, 1),
            ("bad-signature", "2026-10-27T15:00:00"): (
                {"staged": ("159.0.1",), "verified": {**verified, "159.0.1": "FAILED"}},
                3,
            ),
        }
        for (label, now), (tree, code) in cases.items():
            with self.subTest(case=label):
                root = offline_tree(self.tmp / label, verified=tree.pop("verified", verified), **tree)
                summary = self.tmp / f"{label}.md"
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = watch_upstream.main(
                        [
                            "--json",
                            "--verify",
                            "--offline",
                            str(root),
                            "--now",
                            now,
                            "--engine",
                            str(engine),
                            "--summary",
                            str(summary),
                        ]
                    )
                self.assertEqual(rc, code)
                self.assertEqual(json.loads(out.getvalue())["exit_code"], code)
                self.assertIn("### Upstream Firefox", summary.read_text())
        root = offline_tree(self.tmp / "down", verified=verified)
        (root / "product-details" / "firefox_versions.json").unlink()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            rc = watch_upstream.main(["--json", "--offline", str(root), "--engine", str(engine)])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.getvalue())["state"], "unavailable")

    def test_job_summary_is_inert(self):
        report = report_for(self.tmp, "2026-10-27T15:00:00")
        report["errors"] = ["@someone <!-- x --> <img src=x> | #12 `code`"]
        text = watch_upstream.markdown(report)
        self.assertNotIn("@someone", text)
        self.assertNotIn("<!--", text)
        self.assertNotIn("<img", text)
        self.assertIn("\\|", text)
        self.assertIn("#\u200b12", text)

    def test_network_talks_to_fixed_hosts_and_sends_the_token_only_to_the_github_api(self):
        class Response(io.BytesIO):
            status = 200

        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                return Response(b"[]")

        opener = Opener()
        network = watch_upstream.Network(token="secret-token", opener=opener)
        network.request("https://api.github.com/repos/mozilla/foundation-security-advisories/contents/announce/2026")
        network.request("https://product-details.mozilla.org/1.0/firefox_versions.json")
        self.assertEqual(opener.requests[0].unredirected_hdrs.get("Authorization"), "Bearer secret-token")
        self.assertNotIn("Authorization", {**opener.requests[1].headers, **opener.requests[1].unredirected_hdrs})
        for url in ("https://example.org/x", "http://api.github.com/x", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                network.request(url)
        with self.assertRaises(ValueError):
            network.staged("159.0; rm -rf /")

    def test_advisory_listing_that_is_missing_or_not_a_list_fails_closed(self):
        class Response(io.BytesIO):
            status = 200

        class Opener:
            def __init__(self, answer):
                self.answer = answer

            def open(self, request, timeout):
                if self.answer == 404:
                    raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO())
                return Response(self.answer)

        class Listing(watch_upstream.Offline):
            """The recorded data, except the advisory listing, which comes from Network with this answer."""

            def __init__(self, root, answer):
                super().__init__(root)
                self.network = watch_upstream.Network(opener=Opener(answer), sleep=lambda seconds: None)

            def advisory_names(self, year):
                return self.network.advisory_names(year)

        root = offline_tree(self.tmp, verified={"158.0.1": (D158, SUBKEY), "159.0": (D159, SUBKEY)})
        answers = {
            "listing": ((FIXTURES / "github" / "announce" / "2026.json").read_bytes(), "found"),
            "404": (404, "unavailable"),
            "object": (b'{"message": "Moved Permanently"}', "unavailable"),
            "string": (b'"announce/2026"', "unavailable"),
        }
        for label, (answer, status) in answers.items():
            with self.subTest(answer=label):
                report = watch_upstream.check(
                    pinned="158.0.1", pinned_sha256=D158, src=Listing(root, answer), now=at("2026-10-28T00:00:00"), verify=True
                )
                target = report["targets"][0]
                self.assertEqual((target["version"], target["urgency"], target["advisory_status"]), ("159.0", "urgent", status))
                self.assertEqual(target["target_hours"], 24)
                self.assertEqual(any(e.startswith("advisories unavailable") for e in report["errors"]), status != "found")
                self.assertEqual(report["exit_code"], 0)

    def test_only_a_new_years_advisory_listing_may_be_missing(self):
        class Src:
            def __init__(self, years):
                self.years = years

            def advisory_names(self, year):
                if year not in self.years:
                    raise watch_upstream.ListingMissing(f"announce/{year}: HTTP 404")
                return self.years[year]

            def advisory_text(self, year, name):
                return fixture(f"mfsa/{name}")

        names = [item["name"] for item in json.loads(fixture("github/announce/2026.json"))]
        new_year = at("2027-01-01T12:00:00")
        found, _ = watch_upstream.find_advisories(Src({2026: names}), ["159.0"], {"159.0": "2026-10-27"}, new_year)
        self.assertEqual([a.id for a in found["159.0"]], ["mfsa2026-118"])  # announce/2027 does not exist yet
        found, _ = watch_upstream.find_advisories(Src({2026: names, 2027: []}), ["159.0"], {"159.0": "2026-10-27"}, new_year)
        self.assertEqual([a.id for a in found["159.0"]], ["mfsa2026-118"])
        cases = [
            ({2027: []}, {"159.0": "2026-10-27"}),  # a past year must list advisories...
            ({2026: ["README.md"], 2027: []}, {"159.0": "2026-10-27"}),
            ({2026: names}, {"160.0": "2027-01-01"}),  # ...and so must the year of a release
            ({2026: names, 2027: ["firefox"]}, {"160.0": "2027-01-01"}),
        ]
        for years, days in cases:
            with self.subTest(years=years, days=days), self.assertRaisesRegex(OSError, "must have advisories"):
                watch_upstream.find_advisories(Src(years), list(days), days, new_year)

    def test_network_retries_then_gives_up(self):
        slept = []

        class Flaky:
            def open(self, request, timeout):
                raise urllib.error.URLError("down")

        network = watch_upstream.Network(opener=Flaky(), sleep=slept.append, budget=1000)
        with self.assertRaises(urllib.error.URLError):
            network.request("https://archive.mozilla.org/pub/firefox/releases/159.0/SHA256SUMS.asc", method="HEAD")
        self.assertEqual(slept, [2, 8, 30])

    def test_signature_checks_are_cached_per_phase_and_never_when_they_fail(self):
        checked = []

        class Counting(watch_upstream.Offline):
            def verify(self, version):
                checked.append(version)
                return super().verify(version)

        cache: dict = {}
        staged = Counting(
            offline_tree(
                self.tmp / "s",
                drop=("159.0",),
                latest="158.0.1",
                staged=("159.0",),
                verified={"158.0.1": (D158, SUBKEY), "159.0": (D159, SUBKEY)},
            )
        )
        for hour in ("05", "06"):
            watch_upstream.check(
                pinned="158.0.1", pinned_sha256=D158, src=staged, now=at(f"2026-10-27T{hour}:00:00"), verify=True, cache=cache
            )
        self.assertEqual(checked, ["158.0.1", "159.0"])
        shipped = Counting(offline_tree(self.tmp / "p", verified={"158.0.1": (D158, SUBKEY), "159.0": (D159, SUBKEY)}))
        report = watch_upstream.check(
            pinned="158.0.1", pinned_sha256=D158, src=shipped, now=at("2026-10-27T15:00:00"), verify=True, cache=cache
        )
        self.assertEqual(checked[2:], ["158.0.1", "159.0"])  # 6 hours passed for the pin; published: checked again
        self.assertTrue(report["targets"][0]["verified"])
        bad = Counting(offline_tree(self.tmp / "b", verified={"158.0.1": (D158, SUBKEY), "159.0": "bad signature"}))
        cache["verified"]["159.0:shipped"]["checked_at"] = "2026-10-27T15:00:00+00:00"
        report = watch_upstream.check(
            pinned="158.0.1", pinned_sha256=D158, src=bad, now=at("2026-10-27T15:30:00"), verify=True, cache=cache
        )
        self.assertTrue(report["targets"][0]["verified"])  # a fresh success is reused...
        del cache["verified"]["159.0:shipped"]
        report = watch_upstream.check(
            pinned="158.0.1", pinned_sha256=D158, src=bad, now=at("2026-10-27T15:30:00"), verify=True, cache=cache
        )
        self.assertEqual((report["targets"][0]["verified"], report["exit_code"]), (False, 3))  # ...a failure never is
        self.assertNotIn("159.0:shipped", cache["verified"])

    def test_advisory_cache_is_reused_within_6_hours(self):
        root = offline_tree(self.tmp)
        calls = []

        class Counting(watch_upstream.Offline):
            def advisory_text(self, year, name):
                calls.append(name)
                return super().advisory_text(year, name)

        cache: dict = {}
        src = Counting(root)
        for hour in ("15", "16"):
            watch_upstream.check(
                pinned="158.0.1", pinned_sha256=None, src=src, now=at(f"2026-10-27T{hour}:00:00"), verify=False, cache=cache
            )
        self.assertEqual(len(calls), len(set(calls)))
        state = self.tmp / "state" / "cache.json"
        watch_upstream.save_cache(state, cache, at("2026-10-27T16:00:00"))
        self.assertEqual(set(watch_upstream.load_cache(state)["mfsa"]), set(cache["mfsa"]))


# --- the tracking issue (upstream_issue.py) ------------------------------------------------


class FakeGitHub:
    def __init__(self, issues=None, fail=False, labels_fail=False, fail_on=()):
        self.store = {issue["number"]: dict(issue) for issue in issues or []}
        self.fail, self.labels_fail, self.fail_on = fail, labels_fail, fail_on
        self.calls: list = []

    def refuse(self, op):
        if op in self.fail_on:
            raise upstream_issue.ApiError(f"{op}: HTTP 403")

    def issues(self):
        if self.fail:
            raise upstream_issue.ApiError("GET issues: HTTP 503")
        return [dict(issue) for issue in self.store.values()]

    def ensure_labels(self, names):
        if self.labels_fail:
            raise upstream_issue.ApiError("POST labels: HTTP 403")
        self.calls.append(("labels", tuple(names)))

    def create(self, title, body, labels):
        self.refuse("create")
        number = max(self.store, default=0) + 1
        self.store[number] = {"number": number, "state": "open", "title": title, "body": body, "labels": labels}
        self.store[number]["user"] = {"login": upstream_issue.BOT}
        self.calls.append(("create", number, tuple(labels)))
        return number

    def update(self, number, **changes):
        self.refuse("update")
        self.store[number].update(changes)
        self.calls.append(("update", number, tuple(sorted(changes))))

    def comment(self, number, text):
        self.refuse("comment")
        self.calls.append(("comment", number, text))


class IssueTest(TempDirTest):
    runs = itertools.count()

    def sync(self, api, report, mention="caiolombello"):
        actions = upstream_issue.plan(report, api.issues(), mention=mention)
        return upstream_issue.apply(api, actions, [], [])

    def published(self, **kwargs):
        return report_for(self.tmp / f"r{next(self.runs)}", "2026-10-27T15:00:00", **kwargs)

    def test_new_release_opens_one_issue_that_mentions_the_maintainer(self):
        api = FakeGitHub()
        done = self.sync(api, self.published())
        self.assertEqual([a["op"] for a in done], ["create"])
        issue = api.store[1]
        self.assertEqual(issue["labels"], ["upstream-firefox", "target-24h"])
        self.assertIn("cc @caiolombello", issue["body"])
        self.assertIn("2026-10-28 12:57:05 UTC (24 h)", issue["body"])
        self.assertIn("2026-10-30 12:57:05 UTC (72 h)", issue["body"])
        self.assertIn(D159, issue["body"])
        self.assertIn("target 2026-10-28", issue["title"])
        self.assertEqual(upstream_issue.parse_marker(issue["body"])["firefox"], "159.0")

    def test_issue_dedup_by_marker_and_fingerprint(self):
        api = FakeGitHub()
        report = self.published()
        self.sync(api, report)
        self.assertEqual(upstream_issue.plan(report, api.issues(), mention="caiolombello"), [])

    def test_comment_only_on_escalation(self):
        api = FakeGitHub()
        staged = report_for(
            self.tmp / "s",
            "2026-10-27T05:00:00",
            drop=("159.0",),
            latest="158.0.1",
            staged=("159.0",),
            hide=("mfsa2026-118.yml", "mfsa2026-121.yml"),
        )
        self.sync(api, staged)
        self.assertIn("staged", api.store[1]["title"])
        done = self.sync(api, self.published())
        self.assertEqual([a["op"] for a in done], ["update", "comment"])
        comment = api.calls[-1][2]
        self.assertTrue(comment.startswith("@caiolombello Firefox 159.0: Mozilla published it"))
        quieter = self.published()
        quieter["targets"][0]["advisories"].append({"id": "mfsa2026-999", "impact": "low", "title": "x", "url": "u"})
        done = self.sync(api, quieter)
        self.assertEqual([a["op"] for a in done], ["update"])  # body changes notify nobody
        overdue = report_for(self.tmp / "o", "2026-10-30T13:00:00")
        done = self.sync(api, overdue)
        self.assertEqual([a["op"] for a in done], ["update", "comment"])
        self.assertIn("OVERDUE", api.calls[-1][2])

    def test_issue_closed_when_pinned_reaches_the_release_and_reopened_if_behind(self):
        api = FakeGitHub()
        self.sync(api, self.published())
        caught_up = report_for(self.tmp / "c", "2026-10-28T15:00:00", pinned="159.0", digest=D159)
        self.assertEqual(caught_up["targets"], [])
        done = self.sync(api, caught_up)
        self.assertEqual([a["op"] for a in done], ["close"])
        self.assertEqual(api.store[1]["state"], "closed")
        done = self.sync(api, self.published())
        self.assertEqual([a["op"] for a in done], ["reopen", "comment"])
        self.assertEqual(api.store[1]["state"], "open")

    def test_issue_body_neutralizes_mentions_html_and_links(self):
        report = self.published()
        report["targets"][0]["advisories"][0]["title"] = "Pwn @mallory <!-- x --> <img src=x onerror=y> | #12 `run`"
        report["errors"] = ["@mallory said <b>hi</b>"]
        body = upstream_issue.body(report["targets"][0], report, "caiolombello")
        self.assertNotIn("@mallory", body)
        self.assertEqual(body.count("<!--"), 1)  # only the marker
        self.assertNotIn("<img", body)
        self.assertNotIn("<b>", body)
        self.assertIn("#\u200b12", body)
        self.assertEqual(upstream_issue.parse_marker(body)["firefox"], "159.0")

    def test_only_the_bots_issues_count(self):
        report = self.published()
        forged = {
            "number": 7,
            "state": "open",
            "body": upstream_issue.marker("159.0", upstream_issue.fields(report["targets"][0])),
        }
        api = FakeGitHub(
            [
                {**forged, "user": {"login": "mallory"}},
                {**forged, "number": 8, "pull_request": {}, "user": {"login": upstream_issue.BOT}},
            ]
        )
        self.assertEqual([a["op"] for a in self.sync(api, report)], ["create"])

    def test_labels_unavailable_issue_still_opens(self):
        api = FakeGitHub(labels_fail=True)
        warnings: list = []
        upstream_issue.apply(api, upstream_issue.plan(self.published(), [], mention=None), warnings, [])
        self.assertEqual(api.store[1]["labels"], [])
        self.assertIn("labels unavailable", warnings[0])

    def run_main(self, report, api, *extra):
        status = self.tmp / f"status-{next(self.runs)}.json"
        status.write_text(json.dumps(report))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = upstream_issue.main(["--status", str(status), "--repo", "caiolombello/nulavio", *extra], api=api)
        return rc, out.getvalue()

    def test_an_alert_that_cannot_be_written_fails_with_exit_4(self):
        published = self.published()
        cases = {
            "issues cannot be listed": (FakeGitHub(fail=True), published),
            "issue cannot be opened": (FakeGitHub(fail_on=("create",)), published),
            "escalation cannot be written": (FakeGitHub(fail_on=("update",)), published),
            "escalation comment cannot be written": (FakeGitHub(fail_on=("comment",)), published),
        }
        for label, (api, report) in cases.items():
            with self.subTest(case=label):
                if "escalation" in label:  # an issue opened while 159.0 was staged; now Mozilla published it
                    staged = report_for(
                        self.tmp / f"s{next(self.runs)}",
                        "2026-10-27T05:00:00",
                        drop=("159.0",),
                        latest="158.0.1",
                        staged=("159.0",),
                        hide=("mfsa2026-118.yml", "mfsa2026-121.yml"),
                    )
                    upstream_issue.apply(api, upstream_issue.plan(staged, [], mention="caiolombello"), [], [])
                rc, out = self.run_main(report, api, "--mention", "caiolombello")
                self.assertEqual(rc, 4)
                self.assertIn("::error::upstream_issue: alert not delivered for Firefox 159.0", out)
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
            rc, out = self.run_main(published, None)
        self.assertEqual(rc, 4)
        self.assertIn("GITHUB_TOKEN is not set", out)

    def test_issue_changes_that_alert_nobody_only_warn(self):
        rc, out = self.run_main(self.published(), FakeGitHub(labels_fail=True))
        self.assertEqual(rc, 0)
        self.assertIn("::warning::upstream_issue: labels unavailable", out)
        opened = FakeGitHub(fail_on=("update",))
        upstream_issue.apply(opened, upstream_issue.plan(self.published(), [], mention=None), [], [])
        quieter = self.published()
        quieter["targets"][0]["advisories"].append({"id": "mfsa2026-999", "impact": "low", "title": "x", "url": "u"})
        caught_up = report_for(self.tmp / "c", "2026-10-28T15:00:00", pinned="159.0", digest=D159)
        unavailable = {"schema": 2, "state": "unavailable", "exit_code": 2, "targets": [], "errors": ["down"]}
        for label, api, report in (
            ("body rewrite", opened, quieter),
            ("close", FakeGitHub(opened.issues(), fail_on=("comment", "update")), caught_up),
            ("nothing newer, issues cannot be listed", FakeGitHub(fail=True), caught_up),
            ("no report, issues cannot be listed", FakeGitHub(fail=True), unavailable),
        ):
            with self.subTest(case=label):
                rc, out = self.run_main(report, api)
                self.assertEqual(rc, 0)
                self.assertIn("::warning::upstream_issue: GitHub API unavailable", out)
                self.assertNotIn("::error::", out)

    def test_invalid_status_exits_3(self):
        status = self.tmp / "status.json"
        for text in (
            "not json",
            json.dumps({"schema": 1}),
            json.dumps({"schema": 2, "targets": [{"version": "x"}], "pinned": {"firefox": "158.0.1"}}),
        ):
            status.write_text(text)
            with self.subTest(text=text), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    upstream_issue.main(["--status", str(status), "--repo", "caiolombello/nulavio"], api=FakeGitHub()), 3
                )

    def test_advisories_out_of_reach_do_not_notify(self):
        old = upstream_issue.fields(self.published()["targets"][0]) | {"urgency": "standard", "status": "found"}
        new = old | {"urgency": "urgent", "status": "unavailable"}
        self.assertEqual(upstream_issue.escalations(old, new), [])
        self.assertEqual(upstream_issue.escalations(old, new | {"status": "found"}), ["urgency raised to URGENT (24 h target)"])

    def test_unavailable_report_changes_no_issue(self):
        report = {"schema": 2, "state": "unavailable", "exit_code": 2, "targets": [], "errors": ["down"]}
        self.assertEqual(upstream_issue.plan(report, [], mention="caiolombello"), [])

    def test_github_client_is_pinned_to_the_api_host(self):
        with self.assertRaises(ValueError):
            upstream_issue.GitHub("caiolombello/nulavio/../x", "t")
        requests = []

        class Response(io.BytesIO):
            status = 201

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                return Response(b'{"number": 5}')

        api = upstream_issue.GitHub("caiolombello/nulavio", "t0ken", opener=Opener())
        self.assertEqual(api.create("t", "b", []), 5)
        self.assertEqual(requests[0].full_url, "https://api.github.com/repos/caiolombello/nulavio/issues")
        self.assertEqual(requests[0].unredirected_hdrs["Authorization"], "Bearer t0ken")


# --- the verified bump (bump_engine.py) and the fetch pin check ----------------------------


class BumpTest(TempDirTest):
    def setUp(self):
        super().setUp()
        # The repository's file shape with a fixed pin, so these tests survive every real engine bump.
        self.engine = self.tmp / "engine.json"
        shape = json.loads((ROOT / "browser" / "build" / "engine.json").read_text())
        shape.update(firefox="158.0.1", source_sha256=D158)
        self.engine.write_text(json.dumps(shape, indent=2) + "\n")
        self.original = self.engine.read_text()

    def bump(self, version, *, published=True, verify=(D159, SUBKEY), staged=False):
        def answer(value):
            def call(_version):
                if isinstance(value, Exception):
                    raise value
                return value

            return call

        return bump_engine.bump(
            version, engine=self.engine, allow_staged=staged, published=answer(published), verify=answer(verify)
        )

    def code(self, *args, **kwargs) -> int:
        with self.assertRaises(bump_engine.BumpError) as caught:
            self.bump(*args, **kwargs)
        return caught.exception.code

    def test_engine_json_pins_a_verified_digest(self):
        engine = json.loads((ROOT / "browser" / "build" / "engine.json").read_text())
        self.assertRegex(engine["firefox"], watch_upstream.RELEASE_RE)
        self.assertRegex(engine["source_sha256"], r"^[0-9a-f]{64}$")

    def test_bump_writes_the_verified_digest_and_keeps_the_file_shape(self):
        result = self.bump("159.0")
        self.assertEqual((result["previous"], result["version"], result["source_sha256"]), ("158.0.1", "159.0", D159))
        data = json.loads(self.engine.read_text())
        self.assertEqual(list(data), ["comment", "firefox", "source_sha256"])
        self.assertEqual((data["firefox"], data["source_sha256"]), ("159.0", D159))
        self.assertTrue(self.engine.read_text().endswith("}\n"))

    def test_bump_refuses_downgrade_esr_unshipped_and_unverified(self):
        cases = [
            ("158.0", {}, 3),
            ("158.0.1", {}, 3),
            ("153.6.0", {}, 2),
            ("140.4.0esr", {}, 2),
            ("159.0", {"published": False}, 4),
            ("159.0", {"published": OSError("down")}, 4),
            ("159.0", {"verify": watch_upstream.VerificationFailed("bad signature")}, 5),
            ("159.0", {"verify": OSError("404")}, 7),
            ("159.0", {"verify": ("not-hex", SUBKEY)}, 5),
        ]
        for version, kwargs, code in cases:
            with self.subTest(version=version, kwargs=kwargs):
                self.assertEqual(self.code(version, **kwargs), code)
                self.assertEqual(self.engine.read_text(), self.original)
        self.assertEqual(self.bump("159.0", published=False, staged=True)["version"], "159.0")

    def test_check_detects_a_missing_or_different_digest(self):
        self.assertEqual(bump_engine.check(engine=self.engine, verify=lambda v: (D158, SUBKEY))["version"], "158.0.1")
        with self.assertRaises(bump_engine.BumpError) as caught:
            bump_engine.check(engine=self.engine, verify=lambda v: (D159, SUBKEY))
        self.assertEqual(caught.exception.code, 6)
        self.engine.write_text(json.dumps({"firefox": "158.0.1"}))
        with self.assertRaises(bump_engine.BumpError) as caught:
            bump_engine.check(engine=self.engine, verify=lambda v: (D158, SUBKEY))
        self.assertEqual(caught.exception.code, 6)

    def test_fetch_refuses_a_pin_that_differs_from_the_signed_digest(self):
        fetch_firefox_source.check_pin("158.0.1", D158, self.engine)
        fetch_firefox_source.check_pin("159.0", D159, self.engine)  # not the pinned version: nothing to compare
        with self.assertRaisesRegex(SystemExit, "engine.json pin differs from Mozilla's signed SHA256SUMS: refusing"):
            fetch_firefox_source.check_pin("158.0.1", D159, self.engine)

    def test_fetch_checks_the_pin_before_downloading(self):
        pinned = json.loads((ROOT / "browser" / "build" / "engine.json").read_text())["firefox"]  # the real pin
        with (
            mock.patch.object(fetch_firefox_source, "signed_source_digest", return_value=("f" * 64, SUBKEY)),
            mock.patch.object(fetch_firefox_source, "download", side_effect=AssertionError("downloaded")),
            mock.patch.object(sys, "argv", ["fetch", pinned, "--dest", str(self.tmp)]),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(SystemExit, "refusing"),
        ):
            fetch_firefox_source.main()
        self.assertFalse((self.tmp / "downloads" / f"firefox-{pinned}.source.tar.xz").exists())

    def test_fetch_reuses_a_source_tree_only_if_it_came_from_the_signed_tarball(self):
        version = "999.0"  # not engine.json's pin: no pin to compare
        tarballs = {}
        for label in ("A", "B", "C"):
            path = self.tmp / "mozilla" / f"{label}.tar.xz"
            path.parent.mkdir(exist_ok=True)
            data = f"source {label}\n".encode()
            with tarfile.open(path, "w:xz") as archive:
                info = tarfile.TarInfo(f"firefox-{version}/which")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            tarballs[label] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
        dest = self.tmp / "build"
        tree = dest / f"firefox-{version}"

        def fetch(label: str) -> str:
            """Mozilla's signed SHA256SUMS lists tarball `label`, and the archive serves it."""
            path, digest = tarballs[label]

            def download(url, target):
                shutil.copyfile(path, target)
                return digest

            with (
                mock.patch.object(fetch_firefox_source, "signed_source_digest", return_value=(digest, SUBKEY)),
                mock.patch.object(fetch_firefox_source, "download", side_effect=download),
                mock.patch.object(sys, "argv", ["fetch", version, "--dest", str(dest)]),
                contextlib.redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(fetch_firefox_source.main(), 0)
            return out.getvalue()

        def marker() -> str:
            return (tree / fetch_firefox_source.MARKER).read_text().strip()

        def set_aside() -> list[str]:
            return sorted((path / "which").read_text() for path in dest.glob(f"firefox-{version}.stale-*/firefox-{version}"))

        fetch("A")
        self.assertEqual(((tree / "which").read_text(), marker()), ("source A\n", tarballs["A"][1]))
        (tree / "obj-nulavio").mkdir()  # a build in the tree
        self.assertIn("already present", fetch("A"))
        self.assertTrue((tree / "obj-nulavio").is_dir())
        # Mozilla signs another tarball for the same version (--retry after the old tarball was deleted).
        (dest / "downloads" / f"firefox-{version}.source.tar.xz").unlink()
        fetch("B")
        self.assertEqual(((tree / "which").read_text(), marker()), ("source B\n", tarballs["B"][1]))
        self.assertFalse((tree / "obj-nulavio").exists())  # nothing built from A is reused...
        self.assertEqual(set_aside(), ["source A\n"])  # ...nor deleted
        fetch("C")  # the cached tarball (B) is stale: downloaded again, tree extracted again
        self.assertEqual(((tree / "which").read_text(), marker()), ("source C\n", tarballs["C"][1]))
        (tree / fetch_firefox_source.MARKER).unlink()  # a tree from before the marker
        (tree / "which").write_text("changed by hand\n")
        fetch("C")
        self.assertEqual(((tree / "which").read_text(), marker()), ("source C\n", tarballs["C"][1]))
        self.assertEqual(set_aside(), ["changed by hand\n", "source A\n", "source B\n"])
        self.assertFalse(list(dest.glob(".extract-*")))


# --- the local autobuild (autobuild.py) -----------------------------------------------------


GOOD = autobuild.Facts(True, 100.0, "ok", "/k", "/w")
NOW = at("2026-10-27T15:00:00")


class AutobuildDecideTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.shipped = report_for(self.tmp / "a", "2026-10-27T15:00:00")
        self.staged = report_for(
            self.tmp / "b",
            "2026-10-27T05:00:00",
            drop=("159.0",),
            latest="158.0.1",
            staged=("159.0",),
            hide=("mfsa2026-118.yml", "mfsa2026-121.yml"),
        )

    def decide(self, report, state=None, facts=GOOD, **options):
        return autobuild.decide(state or {"builds": {}}, report, facts, autobuild.Options(**options), NOW)

    def test_decide_table(self):
        built = {"builds": {"159.0": {"phase": "built", "source_sha256": D159}}}
        ready = {"builds": {"159.0": {"phase": "ready-to-sign", "source_sha256": D159}}}
        other = {"builds": {"159.0": {"phase": "built", "source_sha256": "e" * 64}}}
        failed = {"builds": {"159.0": {"phase": "failed", "source_sha256": D159, "failed_step": "build"}}}
        rows = [
            ("staged, nothing built", self.staged, {}, GOOD, {}, ("build", 0)),
            ("published, nothing built", self.shipped, {}, GOOD, {}, ("build", 0)),
            ("staged and built: wait", self.staged, built, GOOD, {}, ("wait", 0)),
            ("published, same digest built", self.shipped, built, GOOD, {}, ("ready", 10)),
            ("already ready", self.shipped, ready, GOOD, {}, ("idle", 0)),
            ("published, other digest built", self.shipped, other, GOOD, {}, ("build", 0)),
            ("failed before", self.shipped, failed, GOOD, {}, ("failed-before", 1)),
            ("failed before, --retry", self.shipped, failed, GOOD, {"retry": True}, ("build", 0)),
            ("--no-build", self.shipped, {}, GOOD, {"no_build": True}, ("would-build", 0)),
            ("battery", self.shipped, {}, dataclasses.replace(GOOD, ac_power=False), {}, ("blocked", 4)),
            (
                "battery allowed",
                self.shipped,
                {},
                dataclasses.replace(GOOD, ac_power=False),
                {"build_on_battery": True},
                ("build", 0),
            ),
            ("power unknown", self.shipped, {}, dataclasses.replace(GOOD, ac_power=None), {}, ("blocked", 4)),
            ("low disk", self.shipped, {}, dataclasses.replace(GOOD, free_gib=12.0), {}, ("blocked", 4)),
            ("no key", self.shipped, {}, dataclasses.replace(GOOD, sb_key="missing"), {}, ("blocked", 4)),
            ("key not private", self.shipped, {}, dataclasses.replace(GOOD, sb_key="not-private"), {}, ("blocked", 4)),
            ("a manual build is running", self.shipped, {}, dataclasses.replace(GOOD, busy=(4242,)), {}, ("blocked", 4)),
        ]
        for label, report, state, facts, options, expected in rows:
            with self.subTest(case=label):
                decision = self.decide(report, {"builds": {}, **state}, facts, **options)
                self.assertEqual((decision.action, decision.exit_code), expected)
                if decision.action == "build":
                    self.assertEqual((decision.version, decision.digest), ("159.0", D159))

    def test_never_builds_without_a_verified_signature(self):
        failed = report_for(self.tmp / "c", "2026-10-27T15:00:00", staged=("159.0.1",), verified={"159.0.1": "bad signature"})
        decision = self.decide(failed)
        self.assertEqual((decision.action, decision.exit_code), ("stop", 3))
        self.assertTrue(any(n.urgency == "critical" and "FAILED" in n.title for n in decision.notices))
        unchecked = json.loads(json.dumps(self.shipped))
        for target in unchecked["targets"]:
            target.update(verified=None)
            target.pop("source_sha256")
        self.assertEqual(self.decide(unchecked).action, "wait")
        self.assertEqual(self.decide(report_for(self.tmp / "d", "2026-10-27T15:00:00", digest="0" * 64)).exit_code, 3)

    def test_unavailable_data_notifies_only_after_6_hours(self):
        report = {"schema": 2, "state": "unavailable", "exit_code": 2, "targets": [], "errors": ["down"]}
        fresh = self.decide(report, {"builds": {}, "unavailable_since": "2026-10-27T12:00:00Z"})
        self.assertEqual((fresh.action, fresh.exit_code, fresh.notices), ("unavailable", 2, ()))
        old = self.decide(report, {"builds": {}, "unavailable_since": "2026-10-27T08:00:00Z"})
        self.assertEqual([n.key for n in old.notices], ["unavailable:2026-10-27T08:00:00Z"])

    def test_notices_show_target_and_deadline(self):
        decision = self.decide(self.shipped)
        (shipped,) = [n for n in decision.notices if n.key.startswith("shipped:")]
        self.assertEqual(shipped.urgency, "critical")
        self.assertIn("target 2026-10-28 12:57:05 UTC (24 h)", shipped.body)
        self.assertIn("deadline 2026-10-30 12:57:05 UTC (72 h)", shipped.body)
        blocked = self.decide(self.shipped, facts=dataclasses.replace(GOOD, free_gib=12.0))
        self.assertEqual(blocked.notices[-1].key, "blocked:159.0:disk")  # stable as free space moves

    def test_up_to_date_is_idle(self):
        report = report_for(self.tmp / "e", "2026-10-28T15:00:00", pinned="159.0", digest=D159)
        self.assertEqual((self.decide(report).action, self.decide(report).exit_code), ("idle", 0))


class FakeMachine:
    """Stands in for git, bump_engine.py, systemd-inhibit and rehearse_release.sh."""

    def __init__(self, *, bump_rc=0, bump_digest=D159, rehearse_rc=0, manifest_digest=D159, rehearse_error=None):
        self.calls: list = []
        self.bump_rc, self.bump_digest, self.manifest_digest = bump_rc, bump_digest, manifest_digest
        self.rehearse_rc, self.rehearse_error = rehearse_rc, rehearse_error

    def __call__(self, command, **kwargs):
        self.calls.append((list(map(str, command)), kwargs))
        done = subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[0] == "git":
            if "remove" in command:
                shutil.rmtree(command[-1], ignore_errors=True)
            if "add" in command:
                Path(command[command.index("--detach") + 1]).mkdir(parents=True)
            if "rev-parse" in command:
                done.stdout = "0123abcd\n"
            return done
        if any(str(part).endswith("bump_engine.py") for part in command):
            done.returncode, done.stdout = self.bump_rc, json.dumps({"source_sha256": self.bump_digest})
            return done
        if any(str(part).endswith("rehearse_release.sh") for part in command):
            if self.rehearse_error:
                raise self.rehearse_error
            out = Path(command[-1])
            out.mkdir(parents=True)
            step = "| build | 52 min 00 s | failed (logs/build.log) |" if self.rehearse_rc else "| build | 52 min 00 s | ok |"
            (out / "rehearsal.md").write_text(f"| Step | Time | Result |\n|---|---|---|\n{step}\n")
            if not self.rehearse_rc:
                manifest = {"firefox": command[-2], "source_sha256": self.manifest_digest, "rehearsal": "ok"}
                (out / "manifest.json").write_text(json.dumps(manifest))
            done.returncode = self.rehearse_rc
            return done
        return done  # systemd-ac-power: on AC


class AutobuildRunTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.shipped = report_for(self.tmp / "a", "2026-10-27T15:00:00")
        self.staged = report_for(
            self.tmp / "b",
            "2026-10-27T05:00:00",
            drop=("159.0",),
            latest="158.0.1",
            staged=("159.0",),
            hide=("mfsa2026-118.yml", "mfsa2026-121.yml"),
        )
        self.key = self.tmp / "google-safebrowsing.key"
        self.key.write_text("k")
        self.key.chmod(0o600)
        self.sent: list = []

    def runner(self, report, machine, **options):
        return autobuild.Autobuild(
            repo=self.tmp / "repo",
            work=self.tmp / "work",
            state_path=self.tmp / "state" / "autobuild.json",
            options=autobuild.Options(min_free_gib=0, **options),
            notify=True,
            run=machine,
            which=lambda name: f"/usr/bin/{name}",
            notifier=self.sent.append,
            watch=lambda now: report,
            env={"HOME": str(self.tmp), "NULAVIO_SAFEBROWSING_KEYFILE": str(self.key), "NULAVIO_ALLOW_NO_SAFEBROWSING_KEY": "1"},
            clock=lambda: NOW,
            running=list,
        )

    def test_published_release_builds_in_a_separate_worktree_and_is_ready_to_sign(self):
        machine = FakeMachine()
        result, code = self.runner(self.shipped, machine).once()
        self.assertEqual((code, result["action"], result["phase"]), (10, "build", "ready-to-sign"))
        commands = [call[0] for call in machine.calls]
        tree = str(self.tmp / "work" / "worktrees" / "firefox-159.0")
        self.assertIn(["git", "-C", str(self.tmp / "repo"), "worktree", "add", "--detach", tree, "main"], commands)
        bump = next(c for c in commands if any(part.endswith("bump_engine.py") for part in c))
        self.assertEqual(bump[1:], ["-I", f"{tree}/scripts/release/bump_engine.py", "159.0", "--allow-staged", "--json"])
        rehearse, kwargs = next(call for call in machine.calls if call[0][0] == "systemd-inhibit")
        self.assertEqual(
            rehearse[-3:],
            [f"{tree}/scripts/release/rehearse_release.sh", "159.0", str(self.tmp / "work" / "rehearsal" / "159.0")],
        )
        self.assertNotIn("NULAVIO_ALLOW_NO_SAFEBROWSING_KEY", kwargs["env"])  # release builds need the key
        self.assertEqual(kwargs["cwd"], tree)
        self.assertFalse(any(word in command for command in commands for word in ("commit", "push", "fetch", "pull")))
        titles = [notice.title for notice in self.sent]
        self.assertIn("READY TO SIGN: Nulavio with Firefox 159.0", titles)
        state = json.loads((self.tmp / "state" / "autobuild.json").read_text())
        self.assertEqual(
            (state["builds"]["159.0"]["phase"], state["builds"]["159.0"]["base_commit"]), ("ready-to-sign", "0123abcd")
        )
        again, code = self.runner(self.shipped, FakeMachine()).once()
        self.assertEqual((again["action"], code), ("idle", 0))
        self.assertEqual(titles, [notice.title for notice in self.sent])  # nothing said twice

    def test_staged_pre_build_then_ready_when_published(self):
        result, code = self.runner(self.staged, FakeMachine()).once()
        self.assertEqual((result["phase"], code), ("built", 0))
        result, code = self.runner(self.staged, FakeMachine()).once()
        self.assertEqual((result["action"], code), ("wait", 0))
        machine = FakeMachine()
        result, code = self.runner(self.shipped, machine).once()
        self.assertEqual((result["action"], result["phase"], code), ("ready", "ready-to-sign", 10))
        self.assertFalse(any("rehearse_release.sh" in " ".join(c[0]) for c in machine.calls))  # no rebuild

    def test_failures(self):
        cases = [
            ("bad signature in the worktree", {"bump_rc": 5}, 3, "failed"),
            ("Mozilla unreachable: retried next run", {"bump_rc": 7}, 2, "interrupted"),
            ("digest moved between checks", {"bump_digest": "e" * 64}, 3, "failed"),
            ("rehearsal failed", {"rehearse_rc": 1}, 1, "failed"),
            ("manifest does not match", {"manifest_digest": "e" * 64}, 1, "failed"),
            ("a tool vanished: a failure, not 'building' forever", {"rehearse_error": FileNotFoundError("gone")}, 1, "failed"),
        ]
        for label, machine_options, code, phase in cases:
            with self.subTest(case=label):
                shutil.rmtree(self.tmp / "state", ignore_errors=True)
                shutil.rmtree(self.tmp / "work", ignore_errors=True)
                result, rc = self.runner(self.shipped, FakeMachine(**machine_options)).once()
                self.assertEqual((rc, result["phase"]), (code, phase))
                state = json.loads((self.tmp / "state" / "autobuild.json").read_text())
                if phase == "interrupted":
                    self.assertNotIn("159.0", state["builds"])
                else:
                    self.assertEqual(state["builds"]["159.0"]["phase"], "failed")
        self.assertEqual(state["builds"]["159.0"]["failed_step"], "autobuild")
        self.assertEqual(autobuild.failed_step(Path("/nonexistent")), None)

    def test_rehearsal_failure_names_the_step_and_is_not_retried_alone(self):
        result, code = self.runner(self.shipped, FakeMachine(rehearse_rc=1)).once()
        self.assertIn("step build", result["reason"])
        machine = FakeMachine()
        result, code = self.runner(self.shipped, machine).once()
        self.assertEqual((result["action"], code, machine.calls[-1][0][0]), ("failed-before", 1, "systemd-ac-power"))
        result, code = self.runner(self.shipped, FakeMachine(), retry=True).once()
        self.assertEqual(code, 10)

    def test_dry_run_changes_nothing(self):
        machine = FakeMachine()
        runner = self.runner(self.shipped, machine)
        runner.dry_run = True
        result, code = runner.once()
        self.assertEqual((result["action"], code), ("build", 0))
        self.assertFalse((self.tmp / "state").exists())
        self.assertFalse((self.tmp / "work").exists())
        self.assertEqual(self.sent, [])
        self.assertIn("Firefox 159.0 released: URGENT (impact high; sandbox escape)", result["notices"])

    def test_a_running_manual_build_is_found(self):
        proc = self.tmp / "proc"
        for pid, arguments in (
            ("101", [b"bash", b"/src/scripts/build/build_nulavio.sh", b"159.0"]),
            ("102", [b"bash"]),
            ("self", [b"x"]),
        ):
            (proc / pid).mkdir(parents=True)
            (proc / pid / "cmdline").write_bytes(b"\0".join(arguments) + b"\0")
        (proc / "103").mkdir()  # gone before it was read
        self.assertEqual(autobuild.running_builds(proc), [101])

    def test_lock_is_exclusive(self):
        lock = self.tmp / "run" / "nulavio-autobuild.lock"
        first = autobuild.acquire(lock)
        self.assertIsNotNone(first)
        self.assertIsNone(autobuild.acquire(lock))
        first.close()
        third = autobuild.acquire(lock)
        self.assertIsNotNone(third)
        third.close()

    def test_safe_browsing_key_is_the_file_build_nulavio_reads(self):
        script = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text()
        self.assertIn(
            "NULAVIO_SAFEBROWSING_KEYFILE:-${XDG_CONFIG_HOME:-$HOME/.config}/nulavio-build/google-safebrowsing.key", script
        )
        self.assertEqual(autobuild.safebrowsing_key({"HOME": "/h"}), Path("/h/.config/nulavio-build/google-safebrowsing.key"))
        self.assertEqual(
            autobuild.safebrowsing_key({"HOME": "/h", "XDG_CONFIG_HOME": "/c"}), Path("/c/nulavio-build/google-safebrowsing.key")
        )
        self.assertEqual(autobuild.safebrowsing_key({"NULAVIO_SAFEBROWSING_KEYFILE": "/k"}), Path("/k"))
        self.assertEqual(autobuild.key_state(self.key), "ok")
        self.key.chmod(0o644)
        self.assertEqual(autobuild.key_state(self.key), "not-private")
        self.assertEqual(autobuild.key_state(self.tmp / "absent"), "missing")

    def test_autobuild_never_commits_pushes_or_fetches(self):
        source = (ROOT / "scripts" / "release" / "autobuild.py").read_text()
        for git_call in re.findall(r"self\.git\(([^)]*)\)", source):
            self.assertNotRegex(git_call, r'"(commit|push|fetch|pull|reset|checkout)"')
        self.assertNotRegex(source, r'"git",\s*"(commit|push)')

    def test_prune_removes_only_older_releases_of_its_own(self):
        machine = FakeMachine()
        runner = self.runner(self.shipped, machine)
        for name in (
            "worktrees/firefox-158.0.1",
            "worktrees/firefox-159.0",
            "rehearsal/158.0.1",
            "rehearsal/159.0",
            "rehearsal/notes",
        ):
            (self.tmp / "work" / name).mkdir(parents=True)
        removed = runner.prune("159.0")
        self.assertEqual(sorted(Path(p).name for p in removed), ["158.0.1", "firefox-158.0.1"])
        self.assertTrue((self.tmp / "work" / "rehearsal" / "159.0").exists())
        self.assertFalse((self.tmp / "work" / "rehearsal" / "158.0.1").exists())


# --- the rehearsal's manifest, the workflow and the timer ------------------------------------


class ReleaseFilesTest(TempDirTest):
    def test_rehearsal_writes_a_manifest_of_what_it_checked(self):
        script = (ROOT / "scripts" / "release" / "rehearse_release.sh").read_text()
        match = re.search(
            r"manifest\(\) \{\n    python3 -I - \"\$out\" \"\$version\" \"\$repo\" \"\$work/firefox-\$version\" <<'EOF'\n"
            r"(.*?)\nEOF\n\}\nstep manifest manifest\n",
            script,
            re.S,
        )
        self.assertIsNotNone(match, "rehearse_release.sh must end with the manifest step")
        writer = self.tmp / "manifest_writer.py"
        writer.write_text(match.group(1))
        repo = self.tmp / "repo"
        (repo / "browser" / "build").mkdir(parents=True)
        (repo / "browser" / "build" / "engine.json").write_text(json.dumps({"firefox": "159.0", "source_sha256": D159}))
        env = {"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": str(self.tmp), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
        for command in (
            ["init", "-q"],
            ["add", "-A"],
            ["-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "base"],
        ):
            subprocess.run(["git", "-C", str(repo), *command], check=True, env=env)
        out = self.tmp / "out"
        (out / "logs").mkdir(parents=True)
        (out / "packages" / "x86_64").mkdir(parents=True)
        (out / "logs" / "verify-source.log").write_text(
            f"OK  signature by 14F26682D0916CDD81E37B6D61B7B526D98F0353 (subkey {SUBKEY})\n"
            f"{D159}  source/firefox-159.0.source.tar.xz\n"
        )
        rpm = out / "packages" / "x86_64" / "nulavio-159.0-0.1.fc44.x86_64.rpm"
        rpm.write_bytes(b"rpm")
        (out / "packages" / "nulavio_159.0-0.1_amd64.deb").write_bytes(b"deb")
        (out / "packages" / "nulavio_159.0-0.1_amd64.deb.cdx.json").write_text("{}")
        tree = self.tmp / "build" / "firefox-159.0"  # the source tree the build compiled
        tree.mkdir(parents=True)
        (tree / ".nulavio-source-sha256").write_text(D159 + "\n")

        def write():
            command = [sys.executable, "-I", str(writer), str(out), "159.0", str(repo), str(tree)]
            return subprocess.run(command, capture_output=True, text=True, env=env)

        run = write()
        self.assertEqual(run.returncode, 0, run.stderr)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual((manifest["firefox"], manifest["source_sha256"], manifest["signing_subkey"]), ("159.0", D159, SUBKEY))
        self.assertEqual(manifest["rehearsal"], "ok")
        self.assertEqual(manifest["engine_json"], {"firefox": "159.0", "source_sha256": D159})
        self.assertRegex(manifest["nulavio_base_commit"], r"^[0-9a-f]{40}$")
        files = {entry["file"]: entry["sha256"] for entry in manifest["packages"]}
        self.assertEqual(files["packages/x86_64/nulavio-159.0-0.1.fc44.x86_64.rpm"], hashlib.sha256(b"rpm").hexdigest())
        self.assertEqual([entry["file"] for entry in manifest["sboms"]], ["packages/nulavio_159.0-0.1_amd64.deb.cdx.json"])
        # The tree was extracted from another tarball than the one Mozilla signs now, or nobody knows which.
        for text, error in ((D158 + "\n", "extracted from " + D158), (None, "no verified digest")):
            with self.subTest(marker=text):
                (out / "manifest.json").unlink(missing_ok=True)
                (tree / ".nulavio-source-sha256").unlink(missing_ok=True)
                if text:
                    (tree / ".nulavio-source-sha256").write_text(text)
                run = write()
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(error, run.stderr)
                self.assertFalse((out / "manifest.json").exists())
        (tree / ".nulavio-source-sha256").write_text(D159 + "\n")
        (out / "logs" / "verify-source.log").write_text("FAILED\n")
        self.assertNotEqual(write().returncode, 0)

    def test_upstream_workflow_is_least_privilege_and_takes_no_outside_data_into_shell(self):
        text = (ROOT / ".github" / "workflows" / "upstream.yml").read_text()
        self.assertEqual(re.findall(r'cron: "([^"]+)"', text), ["47 4 * * *", "47 14 * * *"])
        self.assertIn("\npermissions:\n  contents: read\n", text)
        self.assertEqual(re.findall(r"(?m)^\s+(\w[\w-]*): write(?:\s+#.*)?$", text), ["issues"])
        self.assertRegex(text, r"(?m)^    permissions:\n      contents: read\n      issues: write(?:\s+#.*)?$")
        self.assertIn("timeout-minutes: 5", text)
        self.assertRegex(text, r"concurrency:\n  group: upstream\n  cancel-in-progress: false")
        self.assertIn("persist-credentials: false", text)
        self.assertIn("watch_upstream.py --json --verify", text)
        self.assertIn("upstream_issue.py --status", text)
        # A failed issue step (exit 4: an alert not delivered) fails the job; the verdict and the other watch still run.
        self.assertEqual(len(re.findall(r"(?m)^        if: \$\{\{ !cancelled\(\) \}\}$", text)), 2)
        self.assertRegex(text, r"- name: Verdict\n        if: \$\{\{ !cancelled\(\) \}\}\n")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)run: ?(.*)$", line)
            if not match:
                continue
            block = [match.group(2)]
            if match.group(2) in ("|", ">"):
                indent = len(match.group(1))
                block = [following for following in lines[index + 1 :] if following.strip()]
                block = block[: next((i for i, b in enumerate(block) if len(b) - len(b.lstrip()) <= indent), len(block))]
            self.assertNotIn("${{", "\n".join(block), f"expression expanded into a shell command near line {index + 1}")

    def test_systemd_units_are_inert_and_run_isolated_python(self):
        service = (ROOT / "contrib" / "systemd" / "nulavio-upstream.service").read_text()
        timer = (ROOT / "contrib" / "systemd" / "nulavio-upstream.timer").read_text()
        for path in (ROOT / "contrib" / "systemd").iterdir():
            self.assertFalse(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), path.name)
        self.assertIn("ExecStart=/usr/bin/python3 -I ${NULAVIO_REPO}/scripts/release/autobuild.py --notify", service)
        self.assertIn("EnvironmentFile=%h/.config/nulavio-build/autobuild.env", service)
        self.assertIn("SuccessExitStatus=10", service)
        self.assertNotIn("sudo", service + timer)
        self.assertIn("OnCalendar=*-*-* *:07,37:00", timer)
        self.assertIn("Persistent=true", timer)
        policy = (ROOT / "docs" / "architecture" / "update-policy.md").read_text()
        for command in (
            "install -Dm644 contrib/systemd/nulavio-upstream.service contrib/systemd/nulavio-upstream.timer"
            " -t ~/.config/systemd/user/",
            "systemctl --user daemon-reload",
            "systemctl --user enable --now nulavio-upstream.timer",
        ):
            self.assertIn(command, policy)
            self.assertIn(command, service)


if __name__ == "__main__":
    unittest.main()
