"""The daily watch reads the GitHub security advisories of each pinned extension's repository and fails on one
that covers the pinned version (#415). No network: GitHub's replies are recorded in tests/fixtures/advisories
(2026-11-18; gorhill/uBlock's GHSA-cmqw-9r2w-6wv2 is the known positive for the old pin 1.75.0)."""

from __future__ import annotations

import copy
import datetime
import io
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import watch_dependencies as watch  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "advisories"
UBO = json.loads((FIXTURES / "gorhill-uBlock.json").read_text())
KEEPASSXC = json.loads((FIXTURES / "keepassxreboot-keepassxc-browser.json").read_text())
LOCK = json.loads((ROOT / "browser" / "distribution" / "extensions.lock.json").read_text())
UBO_SOURCE = {"key": "ublock-origin", "repo": "gorhill/uBlock", "monorepo": False}


def entry(key: str, version: str) -> dict:
    return {"key": key, "version": version}


class AdvisoryNet:
    """Stands in for watch.Net: api.github.com answers from the recorded replies."""

    def __init__(self, replies=None, error=None):
        self.replies = {"gorhill/uBlock": UBO, "keepassxreboot/keepassxc-browser": KEEPASSXC, **(replies or {})}
        self.error = error
        self.urls = []

    def github_json(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        repo = url.split("/repos/")[1].split("/security-advisories")[0]
        return self.replies.get(repo, [])


def tree(version_overrides: dict[str, str], tmp: Path) -> Path:
    """A copy of the lock with other pinned versions, for run through advisory_rows."""
    lock = copy.deepcopy(LOCK)
    for item in lock["extensions"]:
        item["version"] = version_overrides.get(item["key"], item["version"])
    (tmp / "browser" / "distribution").mkdir(parents=True)
    (tmp / "docs" / "security").mkdir(parents=True)
    (tmp / "browser" / "distribution" / "extensions.lock.json").write_text(json.dumps(lock))
    (tmp / "docs" / "security" / "extension-advisory-sources.json").write_text(watch.ADVISORY_SOURCES.read_text())
    return tmp


class RangeTest(unittest.TestCase):
    def test_the_forms_github_uses(self):
        self.assertTrue(watch.range_covers("1.75.2 and lower", "1.75.0"))
        self.assertTrue(watch.range_covers("1.75.2 and lower", "1.75.2"))
        self.assertFalse(watch.range_covers("1.75.2 and lower", "1.75.4"))
        self.assertTrue(watch.range_covers("<= 1.9.6", "1.9.6"))
        self.assertFalse(watch.range_covers("<=1.10.3", "1.10.4.1"))  # four parts
        self.assertTrue(watch.range_covers(">= 2026.9.0, < 2026.10.2", "2026.10.1"))
        self.assertFalse(watch.range_covers(">= 2026.9.0, < 2026.10.2", "2026.10.2"))
        self.assertTrue(watch.range_covers("< 1.10", "1.9.9"))
        self.assertFalse(watch.range_covers("< 1.10", "1.10.0"))  # 1.10 == 1.10.0
        self.assertTrue(watch.range_covers("= 1.2.3", "1.2.3"))

    def test_a_range_it_cannot_read_is_refused_not_ignored(self):
        for text in (
            None,
            "",
            "   ",
            "all versions",
            "< 1.2-beta",
            "1.2 || 2.0",
            ">= 1.0 < 2.0",
            "before 1.4",
            "~> 1.2",
            "< 1.2,",
            "< 1.0, before the summer",
            "< 1.0, <= 2.x",
            "< 1.0, garbage",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                watch.range_covers(text, "1.0.0")
        with self.assertRaises(ValueError):
            watch.range_covers("< 2", "1.0-rc1")  # a pinned version is read as strictly as a bound


class AdvisoryRowsTest(unittest.TestCase):
    def rows(self, version, advisories=None):
        advisories = UBO if advisories is None else advisories
        return watch.advisory_row(entry("ublock-origin", version), UBO_SOURCE, advisories)

    def test_the_recorded_ubo_advisory_covers_the_old_pin_and_not_the_new(self):
        old = self.rows("1.75.0")
        self.assertEqual([r.state for r in old], ["fail"])
        self.assertIn("GHSA-cmqw-9r2w-6wv2", old[0].text)
        self.assertIn("https://github.com/gorhill/uBlock/security/advisories/GHSA-cmqw-9r2w-6wv2", old[0].text)
        self.assertIn("1.75.4", old[0].text)
        self.assertEqual(self.rows("1.75.2")[0].state, "fail")
        self.assertEqual(self.rows("1.75.4"), [])
        self.assertEqual(self.rows("1.76.4"), [])

    def test_an_unreadable_range_fails_with_the_advisory_named(self):
        broken = copy.deepcopy(UBO)
        broken[0]["vulnerabilities"][0]["vulnerable_version_range"] = "before the summer"
        rows = self.rows("1.76.4", broken)
        self.assertEqual([r.state for r in rows], ["fail"])
        self.assertIn("GHSA-cmqw-9r2w-6wv2", rows[0].text)
        self.assertIn("cannot be read", rows[0].text)

    def test_a_draft_or_withdrawn_advisory_is_not_a_finding(self):
        for change in ({"state": "draft"}, {"withdrawn_at": "2026-11-17T00:00:00Z"}):
            other = copy.deepcopy(UBO)
            other[0].update(change)
            self.assertEqual(self.rows("1.75.0", other), [])

    def test_a_one_product_repository_matches_whatever_the_package_is_called(self):
        for name in ("uBlock Origin (Firefox)", "ublock-origin", "gorhill/uBlock", "uBO", ""):
            other = copy.deepcopy(UBO)
            other[0]["vulnerabilities"][0]["package"]["name"] = name
            other[0]["vulnerabilities"][0]["package"]["ecosystem"] = ""
            with self.subTest(name=name):
                self.assertEqual([r.state for r in self.rows("1.75.0", other)], ["fail"])

    def test_a_monorepo_is_filtered_by_name_and_an_unknown_name_fails(self):
        mono = {"key": "bitwarden", "repo": "bitwarden/clients", "monorepo": True, "packages": ["@bitwarden/browser"]}
        advisory = copy.deepcopy(UBO)
        advisory[0]["vulnerabilities"][0]["vulnerable_version_range"] = "< 2027.1.0"
        advisory[0]["vulnerabilities"][0]["package"]["name"] = "@Bitwarden/Browser"
        self.assertEqual([r.state for r in watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, advisory)], ["fail"])
        self.assertEqual(watch.advisory_row(entry("bitwarden", "2027.1.0"), mono, advisory), [])  # not covered
        advisory[0]["vulnerabilities"][0]["package"]["name"] = "@bitwarden/cli"
        rows = watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, advisory)
        self.assertEqual([r.state for r in rows], ["fail"])
        self.assertIn("@bitwarden/cli", rows[0].text)

    def test_another_product_of_the_monorepo_is_skipped_and_an_unknown_name_still_fails(self):
        mono = {
            "key": "bitwarden",
            "repo": "bitwarden/clients",
            "monorepo": True,
            "packages": ["@bitwarden/browser"],
            "other_packages": ["@Bitwarden/CLI"],
        }
        advisory = copy.deepcopy(UBO)
        advisory[0]["vulnerabilities"][0]["vulnerable_version_range"] = "< 2027.1.0"
        advisory[0]["vulnerabilities"][0]["package"]["name"] = "@bitwarden/cli"
        self.assertEqual(watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, advisory), [])
        advisory[0]["vulnerabilities"][0]["package"]["name"] = "@bitwarden/desktop"  # in neither list
        self.assertEqual([r.state for r in watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, advisory)], ["fail"])
        both = copy.deepcopy(advisory)  # the extension's own package in the same advisory still counts
        both[0]["vulnerabilities"] = [
            {**advisory[0]["vulnerabilities"][0], "package": {"name": "@bitwarden/cli"}},
            {**advisory[0]["vulnerabilities"][0], "package": {"name": "@bitwarden/browser"}},
        ]
        self.assertEqual([r.state for r in watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, both)], ["fail"])
        shipped = watch.load_advisory_sources()["bitwarden"]
        self.assertIn("@bitwarden/cli", shipped["other_packages"])

    def test_an_advisory_without_vulnerabilities_cannot_be_matched(self):
        for empty in (None, [], "x"):
            other = copy.deepcopy(UBO)
            other[0]["vulnerabilities"] = empty
            with self.subTest(empty=empty):
                rows = self.rows("1.76.4", other)
                self.assertEqual([r.state for r in rows], ["fail"])
                self.assertIn("GHSA-cmqw-9r2w-6wv2", rows[0].text)

    def exception(self, **change):
        item = {
            "id": "GHSA-cmqw-9r2w-6wv2",
            "ecosystem": watch.EXTENSION_ECOSYSTEM,
            "package": "ublock-origin",
            "version": "1.75.0",
            "reason": "test",
            "until": "2026-12-31",
        }
        return {**item, **change}

    def test_an_exception_covers_one_advisory_one_extension_one_version_until_its_date(self):
        today = datetime.date(2026, 11, 18)

        def states(version, item, now=today):
            used = set()
            rows = watch.advisory_row(entry("ublock-origin", version), UBO_SOURCE, UBO, [item], now, used)
            return [r.state for r in rows], used

        self.assertEqual(states("1.75.0", self.exception())[0], ["accepted"])
        self.assertEqual(states("1.75.0", self.exception(until="2026-11-18"))[0], ["accepted"])  # the last day
        expired = watch.advisory_row(
            entry("ublock-origin", "1.75.0"), UBO_SOURCE, UBO, [self.exception(until="2026-11-17")], today
        )
        self.assertEqual([r.state for r in expired], ["fail"])
        self.assertIn("expired", expired[0].text)
        self.assertEqual(states("1.75.2", self.exception())[0], ["fail"])  # another version
        self.assertEqual(states("1.75.0", self.exception(package="bitwarden"))[0], ["fail"])  # another extension
        self.assertEqual(states("1.75.0", self.exception(id="GHSA-xxxx-xxxx-xxxx"))[0], ["fail"])  # another advisory

    def test_keepassxc_ranges_use_four_part_versions(self):
        source = {
            "key": "keepassxc-browser",
            "repo": "keepassxreboot/keepassxc-browser",
            "monorepo": False,
        }
        self.assertEqual(watch.advisory_row(entry("keepassxc-browser", "1.10.4.1"), source, KEEPASSXC), [])
        states = [r.state for r in watch.advisory_row(entry("keepassxc-browser", "1.10.3"), source, KEEPASSXC)]
        self.assertEqual(states, ["fail"])  # <=1.9.6 does not cover 1.10.3, <=1.10.3 does


class WatchTest(unittest.TestCase):
    def run_rows(self, net, versions=None, exceptions=()):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return watch.advisory_rows(net, tree(versions or {}, Path(tmp)), list(exceptions), datetime.date(2026, 11, 18))

    def test_the_pinned_lock_has_no_finding_and_names_what_has_no_source(self):
        net = AdvisoryNet()
        rows = watch.advisory_rows(net, ROOT)
        self.assertEqual([r.state for r in rows if r.state != "ok"], [])
        self.assertEqual(sorted(r.detail["key"] for r in rows if r.detail.get("source", 1) is None), ["1password", "proton-pass"])
        self.assertEqual(len(net.urls), 3)
        self.assertTrue(all(u.startswith("https://api.github.com/repos/") for u in net.urls))
        self.assertIn("1password, proton-pass: no public source", watch.report([], rows))

    def test_the_old_ubo_pin_fails_the_run_with_the_advisory(self):
        rows = self.run_rows(AdvisoryNet(), {"ublock-origin": "1.75.0"})
        self.assertEqual(watch.exit_status(rows), 1)
        fail = next(r for r in rows if r.state == "fail")
        self.assertIn("GHSA-cmqw-9r2w-6wv2", watch.report([], rows))
        self.assertEqual(fail.detail["id"], "GHSA-cmqw-9r2w-6wv2")

    def test_an_api_error_is_reported_not_passed(self):
        for error in (OSError("down"), ValueError("bad json")):
            rows = self.run_rows(AdvisoryNet(error=error))
            self.assertEqual({r.state for r in rows if r.check == "advisory"} - {"ok"}, {"error"})
            self.assertEqual(watch.exit_status(rows), 2)
        rows = self.run_rows(AdvisoryNet(replies={"gorhill/uBlock": {"message": "rate limited"}}))
        self.assertIn("error", {r.state for r in rows})  # not a list

    def test_an_unused_extension_exception_is_reported_and_the_osv_check_leaves_it_alone(self):
        item = AdvisoryRowsTest.exception(self, version="1.76.4")
        rows = self.run_rows(AdvisoryNet(), exceptions=[item])
        self.assertEqual(
            [r.text for r in rows if r.check == "exception"],
            ["exception GHSA-cmqw-9r2w-6wv2 for ublock-origin 1.76.4 matches nothing now: remove it"],
        )
        self.assertEqual(watch.vulnerability_rows([], {}, [item], datetime.date(2026, 11, 18)), [])

    def test_an_exception_is_not_called_unused_when_its_extension_could_not_be_read(self):
        item = AdvisoryRowsTest.exception(self, version="1.76.4")
        rows = self.run_rows(AdvisoryNet(error=OSError("down")), exceptions=[item])
        self.assertEqual(watch.exit_status(rows), 2)
        self.assertEqual([r.text for r in rows if r.check == "exception"], [])
        # another extension's exception, whose own fetch worked, is still reported
        net = AdvisoryNet()
        net.github_json = lambda url: (_ for _ in ()).throw(OSError("down")) if "keepassxc" in url else UBO
        other = {**item, "package": "keepassxc-browser"}
        rows = self.run_rows(net, exceptions=[item, other])
        self.assertEqual(
            [r.text for r in rows if r.check == "exception"],
            ["exception GHSA-cmqw-9r2w-6wv2 for ublock-origin 1.76.4 matches nothing now: remove it"],
        )

    def test_a_malformed_reply_is_an_error_not_a_skip(self):
        for reply in ([None], [{}], [{"ghsa_id": "GHSA-x", "html_url": "u"}], ["x"], [{**UBO[0], "state": None}]):
            with self.subTest(reply=reply):
                rows = self.run_rows(AdvisoryNet(replies={"gorhill/uBlock": reply}))
                self.assertIn("error", {r.state for r in rows})
                self.assertEqual(watch.exit_status(rows), 2)
        draft = [{**UBO[0], "state": "draft"}]
        rows = self.run_rows(AdvisoryNet(replies={"gorhill/uBlock": draft}), {"ublock-origin": "1.75.0"})
        self.assertEqual(watch.exit_status(rows), 0)  # a valid draft stays excluded

    def test_a_malformed_vulnerability_is_an_error_row_and_the_other_checks_go_on(self):
        for bad in (["x"], [1], [{"package": "uBO", "vulnerable_version_range": "<= 2"}], [None]):
            other = copy.deepcopy(UBO)
            other[0]["vulnerabilities"] = bad
            with self.subTest(bad=bad):
                rows = self.run_rows(AdvisoryNet(replies={"gorhill/uBlock": other}))
                self.assertIn("error", {r.state for r in rows if r.check == "advisory"})
                self.assertIn("ok", {r.state for r in rows if r.check == "advisory"})  # the other extensions
                self.assertEqual(watch.exit_status(rows), 2)

    def test_the_token_is_read_from_the_first_line_of_stdin(self):
        self.assertEqual(watch.read_token(io.StringIO("ghs_abc\nmore")), "ghs_abc")
        self.assertIsNone(watch.read_token(io.StringIO("\n")))
        self.assertIsNone(watch.read_token(io.StringIO("")))
        text = (ROOT / "scripts" / "release" / "watch_dependencies.py").read_text()
        self.assertNotIn("os.environ", text)  # the token is not read from the environment

    def test_a_full_page_is_not_assumed_to_be_everything(self):
        rows = self.run_rows(AdvisoryNet(replies={"gorhill/uBlock": [UBO[0]] * 100}))
        self.assertIn("error", {r.state for r in rows})

    def test_the_table_and_the_lock_must_agree(self):
        table = json.loads(watch.ADVISORY_SOURCES.read_text())
        self.assertEqual(sorted(s["key"] for s in table["sources"]), sorted(e["key"] for e in LOCK["extensions"]))
        net = AdvisoryNet()
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = tree({}, Path(tmp))
            lock = json.loads((root / "browser/distribution/extensions.lock.json").read_text())
            lock["extensions"].append({**lock["extensions"][0], "key": "new-extension"})
            (root / "browser/distribution/extensions.lock.json").write_text(json.dumps(lock))
            rows = watch.advisory_rows(net, root)
        self.assertTrue(any(r.state == "fail" and "new-extension" in r.text for r in rows))

    def test_the_table_is_validated(self):
        import tempfile

        bad = [
            {"key": "a", "repo": "o/r"},  # no monorepo flag
            {"key": "a", "repo": "o/r", "monorepo": True},  # a monorepo with no packages
            {"key": "a", "repo": "o/r", "monorepo": False, "packages": ["x"]},  # packages without a monorepo
            {"key": "a", "repo": None},  # no reason
            {"key": "a", "repo": "not a repo", "monorepo": False},
            {"key": "a", "repo": "o/r", "monorepo": False, "other_packages": ["x"]},  # only a monorepo has them
            {"key": "a", "repo": "o/r", "monorepo": True, "packages": ["x"], "other_packages": "y"},  # not a list
            {"key": "a", "repo": "o/r", "monorepo": True, "packages": ["x"], "other_packages": [""]},
            {"key": "a", "repo": "o/r", "monorepo": True, "packages": ["X"], "other_packages": ["x"]},  # in both
        ]
        for item in bad:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(item=item):
                path = Path(tmp) / "t.json"
                path.write_text(json.dumps({"sources": [item]}))
                with self.assertRaises(ValueError):
                    watch.load_advisory_sources(path)


class BudgetTest(unittest.TestCase):
    def test_a_black_holed_network_ends_inside_the_budget_with_every_check_reported(self):
        now = [0.0]
        timeouts = []

        def black_hole(request, timeout):  # every connection hangs until its timeout
            timeouts.append(timeout)
            now[0] += timeout
            raise TimeoutError("timed out")

        net = watch.Net(sleep=lambda d: now.__setitem__(0, now[0] + d), clock=lambda: now[0])
        with mock.patch("urllib.request.urlopen", side_effect=black_hole):
            deps, rows = watch.run(net, datetime.datetime(2026, 11, 19, tzinfo=datetime.UTC))
        self.assertLessEqual(now[0], watch.WATCH_BUDGET)
        self.assertTrue(all(0 < t <= net.timeout for t in timeouts))
        self.assertEqual({r.check for r in rows if r.state == "error"}, {"osv", "extension", "advisory", "image"})
        self.assertEqual(watch.exit_status(rows), 2)
        self.assertTrue(watch.report(deps, rows))  # the summary can be written

    def test_nothing_is_requested_after_the_budget_and_a_request_never_outlasts_it(self):
        now = [0.0]
        net = watch.Net(clock=lambda: now[0], budget=100)
        reply = mock.MagicMock()
        reply.__enter__.return_value = io.BytesIO(b"{}")
        now[0] = 95
        with mock.patch("urllib.request.urlopen", return_value=reply) as opened:
            net.json("https://api.osv.dev/v1/x")
        self.assertEqual(opened.call_args.kwargs["timeout"], 5)
        now[0] = 100
        with mock.patch("urllib.request.urlopen") as opened, self.assertRaises(OSError):
            net.json("https://api.osv.dev/v1/x")
        with mock.patch("urllib.request.urlopen") as opened, self.assertRaises(OSError):
            net.head("https://registry.example/v2/x", {})
        opened.assert_not_called()

    def test_the_budgets_fit_inside_the_workflow_steps_timeout(self):
        import re

        text = (ROOT / ".github" / "workflows" / "upstream.yml").read_text()
        step = re.search(r"timeout-minutes: (\d+)\n(?:(?!- name:).*\n)*?.*watch_dependencies\.py", text)
        self.assertIsNotNone(step, "the watch step and its timeout were not found in upstream.yml")
        step_seconds = int(step.group(1)) * 60
        self.assertLess(watch.GITHUB_BUDGET, watch.WATCH_BUDGET)
        self.assertLessEqual(watch.WATCH_BUDGET + 60, step_seconds)  # room for Python's start and the summary


class FetchTest(unittest.TestCase):
    def http(self, code, **headers):
        return urllib.error.HTTPError("https://api.github.com/x", code, "x", headers, io.BytesIO(b""))

    def reply(self, body):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
        return response

    def test_a_transient_failure_is_retried_then_reported(self):
        sleeps = []
        net = watch.Net(token="t", sleep=sleeps.append)
        with mock.patch.object(net, "_open", side_effect=[self.http(502), OSError("reset"), self.reply([1])]) as opened:
            self.assertEqual(net.github_json(watch.GITHUB + "repos/o/r/security-advisories"), [1])
        self.assertEqual(sleeps, [2, 8])
        self.assertEqual(opened.call_args.kwargs["headers"]["Authorization"], "Bearer t")
        sleeps.clear()
        with mock.patch.object(net, "_open", side_effect=self.http(503)), self.assertRaises(urllib.error.HTTPError):
            net.github_json(watch.GITHUB + "repos/o/r/security-advisories")
        self.assertEqual(sleeps, [2, 8, 30])

    def test_a_client_error_is_not_retried_and_the_token_stays_on_github(self):
        sleeps = []
        net = watch.Net(token="t", sleep=sleeps.append)
        with mock.patch.object(net, "_open", side_effect=self.http(404)), self.assertRaises(urllib.error.HTTPError):
            net.github_json(watch.GITHUB + "repos/o/r/security-advisories")
        self.assertEqual(sleeps, [])
        with self.assertRaises(ValueError):
            net.github_json("https://example.org/repos/o/r/security-advisories")

    def test_the_token_is_sent_to_github_unredirected_and_never_by_json(self):
        net = watch.Net(token="t")
        with mock.patch("urllib.request.urlopen", return_value=self.reply([])) as opened:
            net.github_json(watch.GITHUB + "repos/o/r/security-advisories")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer t")  # in the unredirected headers
        self.assertNotIn("Authorization", request.headers)
        # a redirect to another host builds a request that does not carry it
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, "Found", request.headers, "https://elsewhere.example/x"
        )
        self.assertIsNone(redirected.get_header("Authorization"))
        with mock.patch("urllib.request.urlopen", return_value=self.reply({})) as opened:
            net.json("https://addons.mozilla.org/api/v5/x/")
        self.assertIsNone(opened.call_args.args[0].get_header("Authorization"))

    def test_retrying_stops_when_the_budget_is_spent_counting_the_requests(self):
        now = [0.0]
        sleeps, timeouts = [], []

        def slow_failure(*args, **kwargs):  # each request takes as long as its timeout, then fails
            timeouts.append(kwargs["timeout"])
            now[0] += kwargs["timeout"]
            raise self.http(503)

        net = watch.Net(sleep=lambda d: (sleeps.append(d), now.__setitem__(0, now[0] + d)), clock=lambda: now[0])
        with mock.patch.object(net, "_open", side_effect=slow_failure), self.assertRaises(urllib.error.HTTPError):
            net.github_json(watch.GITHUB + "repos/o/r/security-advisories")
        self.assertLessEqual(now[0], watch.GITHUB_BUDGET + 1)  # requests started at 0, 32, 70 stop there: no 130
        self.assertEqual(timeouts, [30, 30, 30, 30][: len(timeouts)])
        self.assertLessEqual(len(timeouts), 4)
        # nothing left for the next repository: one short attempt, no sleep
        sleeps.clear()
        with mock.patch.object(net, "_open", side_effect=slow_failure) as opened, self.assertRaises(urllib.error.HTTPError):
            net.github_json(watch.GITHUB + "repos/o/s/security-advisories")
        self.assertEqual((sleeps, opened.call_count), ([], 1))
        self.assertEqual(timeouts[-1], watch.GITHUB_BUDGET - 100)  # what is left, not the full 30 s

    def test_a_rate_limited_403_is_retried_and_an_authorization_403_is_not(self):
        sleeps = []
        net = watch.Net(sleep=sleeps.append, wall=lambda: 1000.0)
        url = watch.GITHUB + "repos/o/r/security-advisories"
        limited = self.http(403, **{"retry-after": "7"})
        with mock.patch.object(net, "_open", side_effect=[limited, self.reply([1])]):
            self.assertEqual(net.github_json(url), [1])
        self.assertEqual(sleeps, [7])
        sleeps.clear()
        reset = self.http(403, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1015"})
        with mock.patch.object(net, "_open", side_effect=[reset, self.reply([2])]):
            self.assertEqual(net.github_json(url), [2])
        self.assertEqual(sleeps, [15])
        sleeps.clear()
        authorization = self.http(403, **{"x-ratelimit-remaining": "42"})
        with mock.patch.object(net, "_open", side_effect=authorization) as opened, self.assertRaises(urllib.error.HTTPError):
            net.github_json(url)
        self.assertEqual((sleeps, opened.call_count), ([], 1))
        long_wait = self.http(403, **{"retry-after": "3600"})  # does not fit the budget: reported, not waited for
        with mock.patch.object(net, "_open", side_effect=long_wait) as opened, self.assertRaises(urllib.error.HTTPError):
            net.github_json(url)
        self.assertEqual((sleeps, opened.call_count), ([], 1))


if __name__ == "__main__":
    unittest.main()
