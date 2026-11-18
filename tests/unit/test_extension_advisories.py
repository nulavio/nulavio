"""The daily watch reads the GitHub security advisories of each pinned extension's repository and fails on one
that covers the pinned version (#415). No network: GitHub's replies are recorded in tests/fixtures/advisories
(2026-11-18; gorhill/uBlock's GHSA-cmqw-9r2w-6wv2 is the known positive for the old pin 1.75.0)."""

from __future__ import annotations

import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import watch_dependencies as watch  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "advisories"
UBO = json.loads((FIXTURES / "gorhill-uBlock.json").read_text())
KEEPASSXC = json.loads((FIXTURES / "keepassxreboot-keepassxc-browser.json").read_text())
LOCK = json.loads((ROOT / "browser" / "distribution" / "extensions.lock.json").read_text())
UBO_SOURCE = {"key": "ublock-origin", "repo": "gorhill/uBlock", "packages": ["uBlock Origin"]}


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

    def test_another_package_of_the_repository_is_reported_not_matched(self):
        other = copy.deepcopy(UBO)
        other[0]["vulnerabilities"][0]["package"]["name"] = "uBO Scope"
        rows = self.rows("1.75.0", other)
        self.assertEqual([r.state for r in rows], ["warn"])
        self.assertIn("uBO Scope", rows[0].text)

    def test_keepassxc_ranges_use_four_part_versions(self):
        source = {
            "key": "keepassxc-browser",
            "repo": "keepassxreboot/keepassxc-browser",
            "packages": ["KeePassXC-Browser", "keepassxreboot/keepassxc-browser"],
        }
        self.assertEqual(watch.advisory_row(entry("keepassxc-browser", "1.10.4.1"), source, KEEPASSXC), [])
        states = [r.state for r in watch.advisory_row(entry("keepassxc-browser", "1.10.3"), source, KEEPASSXC)]
        self.assertEqual(states, ["fail"])  # <=1.9.6 does not cover 1.10.3, <=1.10.3 does


class WatchTest(unittest.TestCase):
    def run_rows(self, net, versions=None):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return watch.advisory_rows(net, tree(versions or {}, Path(tmp)))

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
            {"key": "a", "repo": "o/r"},  # no packages
            {"key": "a", "repo": None},  # no reason
            {"key": "a", "repo": "not a repo", "packages": ["x"]},
        ]
        for item in bad:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(item=item):
                path = Path(tmp) / "t.json"
                path.write_text(json.dumps({"sources": [item]}))
                with self.assertRaises(ValueError):
                    watch.load_advisory_sources(path)


class FetchTest(unittest.TestCase):
    def http(self, code):
        return urllib.error.HTTPError("https://api.github.com/x", code, "x", {}, io.BytesIO(b""))

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

    def test_the_workflow_token_is_not_sent_elsewhere(self):
        net = watch.Net(token="t")
        with mock.patch("urllib.request.urlopen", return_value=self.reply({})) as opened:
            net.json("https://addons.mozilla.org/api/v5/x/")
        self.assertIsNone(opened.call_args.args[0].get_header("Authorization"))


if __name__ == "__main__":
    unittest.main()
