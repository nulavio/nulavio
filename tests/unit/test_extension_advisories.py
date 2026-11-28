"""The daily watch reads the GitHub security advisories of each pinned extension's repository and fails on one
that covers the pinned version (#415). No network: GitHub's replies are recorded in tests/fixtures/advisories
(2026-11-18; gorhill/uBlock's GHSA-cmqw-9r2w-6wv2 is the known positive for the old pin 1.75.0)."""

from __future__ import annotations

import copy
import dataclasses
import datetime
import http
import http.client
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
        rows = watch.advisory_row(entry("bitwarden", "2026.10.2"), mono, advisory)
        self.assertEqual([r.state for r in rows], ["ok"])  # a trace, not a finding: the id and the reason
        self.assertIn(advisory[0]["ghsa_id"], rows[0].text)
        self.assertIn("other_packages", rows[0].text)
        self.assertIn(advisory[0]["ghsa_id"], watch.report([], rows))  # and it reaches the summary
        self.assertIn(advisory[0]["ghsa_id"], watch.markdown([], rows))
        self.assertEqual(watch.exit_status(rows), 0)
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
        with mock.patch.object(watch, "urlopen", side_effect=black_hole):
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
        with mock.patch.object(watch, "urlopen", return_value=reply) as opened:
            net.json("https://api.osv.dev/v1/x")
        self.assertEqual(opened.call_args.kwargs["timeout"], 5)
        now[0] = 100
        with mock.patch.object(watch, "urlopen") as opened, self.assertRaises(OSError):
            net.json("https://api.osv.dev/v1/x")
        with mock.patch.object(watch, "urlopen") as opened, self.assertRaises(OSError):
            net.head("https://registry.example/v2/x", {})
        opened.assert_not_called()

    def test_the_budgets_fit_inside_the_workflow_steps_timeout(self):
        import re

        text = (ROOT / ".github" / "workflows" / "upstream.yml").read_text()
        steps = re.split(r"(?m)^(?=      - )", text)  # the steps of the jobs, at their own indentation
        mine = [s for s in steps if "watch_dependencies.py" in s and re.match(r"      - name:", s)]
        self.assertEqual(len(mine), 1, "the watch step was not found in upstream.yml")
        step = re.search(r"(?m)^        timeout-minutes: (\d+)", mine[0])  # the step's own, not the job's
        self.assertIsNotNone(step, "the watch step has no timeout-minutes of its own")
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
        with mock.patch.object(watch, "urlopen", return_value=self.reply([])) as opened:
            net.github_json(watch.GITHUB + "repos/o/r/security-advisories")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer t")  # in the unredirected headers
        self.assertNotIn("Authorization", request.headers)
        # a redirect to another host builds a request that does not carry it
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, "Found", request.headers, "https://elsewhere.example/x"
        )
        self.assertIsNone(redirected.get_header("Authorization"))
        with mock.patch.object(watch, "urlopen", return_value=self.reply({})) as opened:
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


class CutShort:
    """A reply whose body ends early: read() raises IncompleteRead, as http.client does for a short body."""

    status, headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read1(self, amt=-1):
        raise http.client.IncompleteRead(b'{"results": [', 100)


def http_response(raw: bytes) -> http.client.HTTPResponse:
    """A real http.client response over these bytes, as a server that closed the connection after them sent it."""

    class Socket:
        def makefile(self, mode):
            return io.BytesIO(raw)

    response = http.client.HTTPResponse(Socket(), method="GET")
    response.begin()
    return response


class ReplyTest(unittest.TestCase):
    """What Net makes of a reply cut short, a redirect and a slow server (#829): unavailable data, never a crash."""

    def reply(self, body):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(body).encode())
        return response

    def test_a_reply_cut_short_is_an_error_row_and_the_summary_prints(self):
        def opened(url, data=None, **kwargs):  # OSV.dev answers; AMO, GitHub and the registries cut their replies short
            if url == watch.OSV + "querybatch":
                return self.reply({"results": [{} for _ in data["queries"]]})
            if url.startswith(watch.OSV):
                return self.reply({})
            return CutShort()

        sleeps = []
        net = watch.Net(sleep=sleeps.append)
        with mock.patch.object(net, "_open", side_effect=opened):
            deps, rows = watch.run(net, datetime.datetime(2026, 11, 27, tzinfo=datetime.UTC), exceptions=[])
        self.assertFalse([r for r in rows if r.check == "osv"])  # OSV's (empty) result is kept
        for check in ("extension", "advisory", "image"):
            states = {r.state for r in rows if r.check == check and r.detail.get("source", 1) is not None}
            self.assertEqual(states, {"error"}, check)
        self.assertIn("cut short", next(r.text for r in rows if r.check == "extension"))
        self.assertTrue(sleeps)  # GitHub's request was retried, as for a network failure
        self.assertEqual(watch.exit_status(rows), 2)
        self.assertTrue(watch.report(deps, rows).startswith(f"Checked {len(deps)} pinned packages against OSV.dev"))

    def test_github_retries_a_reply_cut_short(self):
        sleeps = []
        net = watch.Net(sleep=sleeps.append)
        with mock.patch.object(net, "_open", side_effect=[CutShort(), self.reply([1])]):
            self.assertEqual(net.github_json(watch.GITHUB + "repos/o/r/security-advisories"), [1])
        self.assertEqual(sleeps, [2])

    def test_a_real_response_closed_before_its_end_is_unavailable_data(self):
        cases = {
            "length": b'HTTP/1.1 200 OK\r\nContent-Length: 40\r\n\r\n{"a": 1}',  # read(n) alone ends quietly here
            "chunked": b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n20\r\n{"a": 1}',
        }
        for name, raw in cases.items():
            net = watch.Net()
            with self.subTest(name), mock.patch.object(net, "_open", return_value=http_response(raw)):
                with self.assertRaises(OSError) as caught:
                    net.json(watch.OSV + "query")
                self.assertIn("cut short", str(caught.exception))
        whole = b'HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n{"a": 1}'
        net = watch.Net()
        with mock.patch.object(net, "_open", return_value=http_response(whole)):
            self.assertEqual(net.json(watch.OSV + "query"), {"a": 1})

    def serve(self, routes, asked, clock=None, step=0.0, timeouts=None, wires=None):
        """https_open and http_open for urllib's own handlers: url -> (status, headers, body), every URL asked kept.

        Each reply is a real http.client response over a Wire, so urllib's handlers and http.client read it as a
        server's; `timeouts` and `wires` keep each request's timeout and each reply's socket, by URL.
        """

        def handler(_self, request):
            asked.append(request.full_url)
            if timeouts is not None:
                timeouts.append(request.timeout)
            status, headers, body = routes[request.full_url]
            if clock is not None:
                clock[0] += step  # a slow connection: the headers come `step` seconds after the request
            head = f"HTTP/1.1 {status} {http.HTTPStatus(status).phrase}\r\n"
            head += "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n"
            drip = body if isinstance(body, Drip) else Drip(body)
            wire = Wire(head.encode(), drip)
            if wires is not None:
                wires[request.full_url] = wire
            response = http.client.HTTPResponse(Socket(wire), method=request.get_method())
            response.begin()
            response.url, response.msg = request.full_url, response.reason  # as urllib's do_open sets them
            return response

        return (
            mock.patch.object(urllib.request.HTTPSHandler, "https_open", handler),
            mock.patch.object(urllib.request.HTTPHandler, "http_open", handler),
        )

    def fetch(self, routes, url, net=None, missing_ok=False, **kwargs):
        asked = []
        https, plain = self.serve(routes, asked, **kwargs)
        with https, plain:
            try:
                return (net or watch.Net()).json(url, missing_ok=missing_ok), asked
            except OSError as exc:
                return exc, asked

    def test_an_amo_request_follows_no_redirect_off_amo_or_to_http(self):
        block = watch.AMO + "blocklist/block/x/"
        not_blocked = b'{"is_all_versions": false, "blocked": [], "soft_blocked": []}'
        for target in ("https://elsewhere.example/blocklist/block/x/", "http://addons.mozilla.org/api/v5/blocklist/block/x/"):
            with self.subTest(target):
                routes = {block: (302, {"Location": target}, b""), target: (200, {}, not_blocked)}
                result, asked = self.fetch(routes, block)
                self.assertIsInstance(result, urllib.error.HTTPError)  # unavailable data, not "not blocked"
                self.assertIn("refusing a redirect", str(result))
                self.assertEqual(asked, [block])  # the other address is never asked
        moved = watch.AMO + "blocklist/block/y/"
        result, asked = self.fetch({block: (301, {"Location": moved}, b""), moved: (200, {}, not_blocked)}, block)
        self.assertEqual((result["blocked"], asked), ([], [block, moved]))  # a redirect inside AMO is followed

    def test_no_request_follows_a_redirect_to_http(self):
        url, plain = watch.OSV + "vulns/X", "http://api.osv.dev/v1/vulns/X"
        result, asked = self.fetch({url: (301, {"Location": plain}, b""), plain: (200, {}, b'{"id": "X"}')}, url)
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertEqual(asked, [url])
        other = "https://osv-mirror.example/v1/vulns/X"  # another https host is followed, as before, outside AMO
        result, asked = self.fetch({url: (302, {"Location": other}, b""), other: (200, {}, b'{"id": "X"}')}, url)
        self.assertEqual(result, {"id": "X"})

    def test_a_request_never_ends_after_its_budget_when_the_server_is_slow(self):
        url = watch.OSV + "vulns/X"
        body = b'{"id": "X", "summary": "' + b"x" * 300_000 + b'"}'
        now = [0.0]

        def started_at(when):  # a Net whose 100 s budget began at 0, asked at `when`
            now[0] = 0.0
            net = watch.Net(clock=lambda: now[0], budget=100)
            now[0] = when
            return net

        # the connection and headers take 10 s, with 5 s of the watch left: the request ends there
        result, _ = self.fetch({url: (200, {}, body)}, url, net=started_at(95), clock=now, step=10)
        self.assertIsInstance(result, TimeoutError)
        # the headers come at once and the body drips, 64 KiB every 2 s: it is cut off between two chunks
        net = started_at(95)
        result, _ = self.fetch({url: (200, {}, Drip(body, now, 2))}, url, net=net)
        self.assertIsInstance(result, TimeoutError)
        self.assertLessEqual(now[0], 100 + 2)  # one chunk past the end at most, not the whole body
        # AMO's own budget bounds an AMO request in the same way
        now[0] = 0.0
        net = watch.Net(clock=lambda: now[0])
        net.amo_started = -(watch.AMO_BUDGET - 3)
        amo = watch.AMO + "addons/addon/x/"
        result, _ = self.fetch({amo: (200, {}, Drip(body, now, 2))}, amo, net=net)
        self.assertIsInstance(result, TimeoutError)
        self.assertLessEqual(now[0], 3 + 2)
        # a reply on time is read whole
        result, _ = self.fetch({url: (200, {}, Drip(body, now, 2))}, url, net=started_at(0))
        self.assertEqual(result["id"], "X")

    def clocked(self, left: float):
        """A Net with `left` seconds of the watch's budget, on a clock the test moves, and that clock."""
        now = [0.0]
        return watch.Net(clock=lambda: now[0], budget=left), now

    def test_a_body_sent_a_little_at_a_time_is_cut_off_at_its_end(self):
        # OpenCodeReview on #916: read(64 KiB) waits on the socket until it has 64 KiB, here 64 reads of 1 KiB, 1 s each
        url = watch.OSV + "vulns/X"
        body = b'{"id": "X", "summary": "' + b"x" * 300_000 + b'"}'
        net, now = self.clocked(5)
        result, _ = self.fetch({url: (200, {}, Drip(body, now, 1, piece=1024))}, url, net=net)
        self.assertIsInstance(result, TimeoutError)
        self.assertLessEqual(now[0], 5 + 1)  # one socket read past the end at most

    def test_a_body_whose_end_comes_after_the_budget_is_not_a_reply(self):
        # OpenCodeReview on #916: the body fills one read before the end, and the read that finds its end comes after it
        url = watch.OSV + "vulns/X"
        head = b'{"id": "X", "summary": "'
        body = head + b"x" * (watch.READ_CHUNK - len(head) - 2) + b'"}'
        self.assertEqual(len(body), watch.READ_CHUNK)
        net, now = self.clocked(5)
        result, _ = self.fetch({url: (200, {}, Drip(body, now, 0, eof=10))}, url, net=net)
        self.assertIsInstance(result, TimeoutError)
        net, now = self.clocked(5)  # the same reply, over in time
        result, _ = self.fetch({url: (200, {}, Drip(body, now, 0, eof=1))}, url, net=net)
        self.assertEqual(result["id"], "X")

    def test_a_404_after_the_budget_is_not_read_as_not_there(self):
        # OpenCodeReview on #916: a late 404 for the pinned version read as "AMO no longer serves it" (exit 1)
        url = watch.AMO + "addons/addon/x/versions/1.0/"
        gone = {url: (404, {"Content-Length": "2"}, b"{}")}
        net, now = self.clocked(500)
        net.amo_started = -(watch.AMO_BUDGET - 3)  # 3 s of AMO's budget left, and the reply takes 10
        result, _ = self.fetch(gone, url, net=net, missing_ok=True, clock=now, step=10)
        self.assertIsInstance(result, TimeoutError)
        net, now = self.clocked(500)
        net.amo_started = -(watch.AMO_BUDGET - 30)  # in time, a 404 still means not there
        result, _ = self.fetch(gone, url, net=net, missing_ok=True, clock=now, step=10)
        self.assertIsNone(result)

    def test_a_redirect_after_the_budget_is_not_followed_and_its_body_not_read(self):
        # OpenCodeReview on #916: urllib read the redirect's whole body, then asked the next address with the first
        # request's timeout, before _open looked at the clock
        url, moved = watch.AMO + "addons/addon/x/", watch.AMO + "addons/addon/y/"
        routes = {url: (302, {"Location": moved}, b""), moved: (200, {}, b"{}")}
        net, now = self.clocked(5)
        result, asked = self.fetch(routes, url, net=net, clock=now, step=10)  # the redirect comes 10 s later
        self.assertIsInstance(result, TimeoutError)
        self.assertEqual(asked, [url])  # the other address is never asked
        # in time, the redirect is followed with what is left (25 - 10 s), and its body is never read
        long_body = Drip(b"x" * 300_000, now, 2)
        routes = {url: (302, {"Location": moved}, long_body), moved: (200, {}, b"{}")}
        net, now = self.clocked(25)
        long_body.clock = now
        timeouts = []
        result, asked = self.fetch(routes, url, net=net, clock=now, step=1, timeouts=timeouts)
        self.assertEqual((result, asked), ({}, [url, moved]))
        self.assertEqual(now[0], 2)  # the two requests' headers, nothing of the redirect's body
        self.assertEqual(timeouts, [25, 24])

    def test_a_refused_redirect_names_only_its_host_and_closes_its_reply(self):
        # OpenCodeReview on #916: the summary would carry a signed URL's token, and the reply's socket stayed open
        block = watch.AMO + "blocklist/block/x/"
        target = "https://someone:hunter2@cdn.example/x.json?Signature=SECRET&Expires=1"
        wires = {}
        result, asked = self.fetch({block: (302, {"Location": target}, b"moved")}, block, wires=wires)
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertIn("refusing a redirect to https://cdn.example (only https://addons.mozilla.org/)", str(result))
        for secret in ("hunter2", "someone", "SECRET", "x.json"):
            self.assertNotIn(secret, str(result))
        self.assertTrue(wires[block].closed)
        self.assertEqual(asked, [block])

    def test_an_amo_redirect_is_judged_by_its_origin_not_its_spelling(self):
        # OpenCodeReview on #916: AMO's own origin with its default port, or its host in capitals, was refused
        block = watch.AMO + "blocklist/block/x/"
        not_blocked = b'{"is_all_versions": false, "blocked": [], "soft_blocked": []}'
        for target in (
            "https://addons.mozilla.org:443/api/v5/blocklist/block/y/",
            "https://ADDONS.mozilla.org/api/v5/blocklist/block/y/",
        ):
            with self.subTest(target):
                result, asked = self.fetch({block: (301, {"Location": target}, b""), target: (200, {}, not_blocked)}, block)
                self.assertEqual((result["blocked"], asked), ([], [block, target]))
        for target in (
            "https://addons.mozilla.org:8443/api/v5/blocklist/block/y/",
            "https://addons.mozilla.org.example/api/v5/blocklist/block/y/",
            "https://addons.mozilla.org@elsewhere.example/api/v5/blocklist/block/y/",
            "https://addons.mozilla.org:x/api/v5/blocklist/block/y/",
        ):
            with self.subTest(target):
                result, asked = self.fetch({block: (301, {"Location": target}, b""), target: (200, {}, not_blocked)}, block)
                self.assertIsInstance(result, urllib.error.HTTPError)
                self.assertEqual(asked, [block])


CHUNK = 64 * 1024  # what a server sends at a time


@dataclasses.dataclass
class Drip:
    """A body as a server sends it: `piece` bytes a socket read, each read (the one that finds its end too) `step`
    seconds after the last on `clock`, and the read that finds the end `eof` seconds after it when that is given."""

    data: bytes
    clock: list | None = None
    step: float = 0.0
    piece: int = CHUNK
    eof: float | None = None


class Wire(io.RawIOBase):
    """A connection's bytes, read by http.client through a BufferedReader as from a socket: the status line and
    headers in one read, then the body as `drip` sends it."""

    def __init__(self, head: bytes, drip: Drip):
        self.head, self.drip, self.left = head, drip, drip.data

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.head:
            data, self.head = self.head[: len(buffer)], self.head[len(buffer) :]
        else:
            size = min(len(buffer), self.drip.piece)
            data, self.left = self.left[:size], self.left[size:]
            if self.drip.clock is not None:
                last = not data and self.drip.eof is not None
                self.drip.clock[0] += self.drip.eof if last else self.drip.step
        buffer[: len(data)] = data
        return len(data)


class Socket:
    def __init__(self, wire):
        self.wire = wire

    def makefile(self, mode):
        return io.BufferedReader(self.wire)


if __name__ == "__main__":
    unittest.main()
