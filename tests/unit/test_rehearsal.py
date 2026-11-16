"""The nightly rehearsal of main (#378): rehearsal.yml, scripts/ci/rehearsal_needed.py and rehearsal_issue.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import needs_integration as gate  # noqa: E402
import rehearsal_issue as tracker  # noqa: E402
import rehearsal_needed as night  # noqa: E402

REPO = "nulavio/nulavio"
SHA = "a" * 40
RUN = "https://github.com/nulavio/nulavio/actions/runs/123456"
WORKFLOWS = ROOT / ".github" / "workflows"


def run_entry(sha: str, event: str = "schedule") -> dict:
    return {"head_sha": sha, "event": event, "head_branch": "main", "head_repository": {"full_name": REPO}}


def issue(number: int, *, author: str = tracker.BOT, body: str = tracker.MARKER, state: str = "open", **more) -> dict:
    return {"number": number, "state": state, "user": {"login": author}, "body": body, **more}


class NeededTest(unittest.TestCase):
    def test_a_night_with_nothing_new_builds_nothing(self):
        self.assertFalse(night.needed("schedule", SHA, SHA, []))

    def test_a_night_with_only_markdown_builds_nothing(self):
        self.assertFalse(night.needed("schedule", SHA, "b" * 40, ["README.md", "docs/security/changelog.md"]))

    def test_a_night_with_a_change_builds(self):
        for changed in (
            ["browser/patches/series"],
            ["README.md", "tests/integration/test_vault.py"],
            [".github/workflows/rehearsal.yml"],
        ):
            self.assertTrue(night.needed("schedule", SHA, "b" * 40, changed), changed)

    def test_what_cannot_be_read_builds(self):
        self.assertTrue(night.needed("schedule", None, SHA, None))  # no green rehearsal yet, or the API is down
        self.assertTrue(night.needed("schedule", SHA, None, []))  # git did not say where HEAD is
        self.assertTrue(night.needed("schedule", SHA, "b" * 40, None))

    def test_by_hand_it_always_builds(self):
        self.assertTrue(night.needed("workflow_dispatch", SHA, SHA, []))
        self.assertTrue(night.needed("", SHA, SHA, []))

    def test_the_last_green_rehearsal_is_asked_of_its_own_workflow(self):
        asked = []

        def gh(args):
            asked.append(args)
            return json.dumps(
                {"workflow_runs": [run_entry("c" * 40, "push"), run_entry(SHA, "workflow_dispatch"), run_entry("b" * 40)]}
            )

        # A green run started by hand is not the baseline: it closes no issue, so the night after it must build.
        self.assertEqual(gate.last_green(REPO, gh, workflow=night.WORKFLOW, events=night.EVENTS), "b" * 40)
        self.assertIn("/actions/workflows/rehearsal.yml/runs?branch=main&status=success", asked[0][1])
        self.assertEqual(gate.last_green(REPO, gh), "c" * 40)  # ci.yml's own question is as it was
        self.assertIn("/actions/workflows/ci.yml/", asked[1][1])
        self.assertIsNone(gate.last_green(REPO, gh, workflow="../../other"))

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_the_script_in_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}  # fmt: skip

            def git(*args: str) -> str:
                return subprocess.run(["git", *args], cwd=tmp, env=env, capture_output=True, text=True, check=True).stdout.strip()

            git("init", "-q", "-b", "main")
            Path(tmp, "code.py").write_text("1\n")
            git("add", ".")
            git("commit", "-q", "-m", "one")
            first = git("rev-parse", "HEAD")

            def decide(event: str, green: str | None) -> dict:
                out = io.StringIO()
                with (
                    mock.patch.dict(os.environ, {"EVENT": event, "GITHUB_REPOSITORY": REPO}),
                    mock.patch.object(gate, "last_green", lambda *_a, **_k: green),
                    contextlib.chdir(tmp),
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(night.main(), 0)
                return dict(line.split("=", 1) for line in out.getvalue().splitlines())

            self.assertEqual(decide("schedule", first), {"build": "false", "base": first})  # nothing new
            Path(tmp, "NOTES.md").write_text("x\n")
            git("add", ".")
            git("commit", "-q", "-m", "two")
            self.assertEqual(decide("schedule", first)["build"], "false")  # Markdown only
            Path(tmp, "code.py").write_text("2\n")
            git("commit", "-q", "-am", "three")
            self.assertEqual(decide("schedule", first)["build"], "true")
            self.assertEqual(decide("schedule", None), {"build": "true", "base": ""})
            self.assertEqual(decide("schedule", "f" * 40), {"build": "true", "base": ""})  # not a commit of this clone
            self.assertEqual(decide("workflow_dispatch", git("rev-parse", "HEAD")), {"build": "true", "base": ""})


class IssuePlanTest(unittest.TestCase):
    def test_what_is_done_for_each_result(self):
        self.assertEqual(tracker.plan("failure", None), "open")
        self.assertEqual(tracker.plan("failure", issue(7)), "comment")
        self.assertEqual(tracker.plan("success", issue(7)), "close")
        self.assertEqual(tracker.plan("success", None), "nothing")

    def test_only_the_bots_own_open_issue_with_the_marker_is_tracked(self):
        others = [
            issue(1, author="someone"),  # the marker pasted by a person
            issue(2, body="The nightly rehearsal of main fails"),  # the bot's, without the marker
            issue(3, state="closed"),
            issue(4, pull_request={}),
            issue(5, body=None),
            {"number": 6},
        ]
        self.assertIsNone(tracker.tracked(others))
        self.assertEqual(tracker.tracked([*others, issue(9), issue(8)])["number"], 8)  # the oldest of two

    def test_the_text_names_the_commit_and_the_run_and_nothing_else_from_outside(self):
        text = tracker.body(SHA, RUN)
        self.assertTrue(text.startswith(tracker.MARKER))
        self.assertIn(f"`{SHA[:12]}`", text)
        self.assertIn(RUN, text)
        for heading in ("## Problem", "## What to do"):
            self.assertIn(heading, text)
        self.assertIn("rehearsal-logs", text)
        self.assertNotRegex(text, r"@[A-Za-z]")  # mentions nobody
        self.assertIn("Green again", tracker.comment("success", SHA, RUN))
        self.assertIn("Still failing", tracker.comment("failure", SHA, RUN))


class FakeApi:
    def __init__(self, issues: list[dict] | None = None, fail_on: str | None = None):
        self.issues = issues or []
        self.fail_on = fail_on
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, token: str, method: str, path: str, payload: dict | None = None):
        self.calls.append((method, path, payload))
        if self.fail_on and self.fail_on in f"{method} {path}":
            raise tracker.IssueError(f"{method} {path}: refused")
        if method == "GET":
            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            return self.issues[(page - 1) * 100 : page * 100]
        if method == "POST" and path.endswith("/issues"):
            return {"number": 41}
        return {}

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path, _ in self.calls if method != "GET"]


class IssueMainTest(unittest.TestCase):
    def run_main(self, result: str, api: FakeApi, *extra: str, with_token: bool = True) -> tuple[int, dict | None, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t" if with_token else ""}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                code = tracker.main(["--result", result, "--sha", SHA, "--run-url", RUN, "--repo", REPO, *extra], api=api)
            except SystemExit as stop:
                code = stop.code
        return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()

    def test_a_first_failure_opens_one_issue_with_the_labels(self):
        api = FakeApi([issue(3, author="someone")])
        code, said, _ = self.run_main("failure", api)
        self.assertEqual((code, said), (0, {"action": "open", "issue": 41, "dry_run": False}))
        self.assertEqual(api.writes(), [("POST", f"/repos/{REPO}/issues")])
        payload = api.calls[-1][2]
        self.assertEqual(payload["labels"], ["bug", "P1"])
        self.assertEqual(payload["title"], tracker.TITLE)
        self.assertIn(tracker.MARKER, payload["body"])

    def test_a_second_failure_comments_and_opens_nothing(self):
        api = FakeApi([issue(12)])
        code, said, _ = self.run_main("failure", api)
        self.assertEqual((code, said["action"], said["issue"]), (0, "comment", 12))
        self.assertEqual(api.writes(), [("POST", f"/repos/{REPO}/issues/12/comments")])

    def test_a_green_night_closes_the_issue_and_a_green_night_without_one_writes_nothing(self):
        api = FakeApi([issue(12)])
        code, said, _ = self.run_main("success", api)
        self.assertEqual((code, said["action"]), (0, "close"))
        self.assertEqual(api.writes(), [("POST", f"/repos/{REPO}/issues/12/comments"), ("PATCH", f"/repos/{REPO}/issues/12")])
        self.assertEqual(api.calls[-1][2], {"state": "closed", "state_reason": "completed"})
        quiet = FakeApi([issue(3, author="someone")])
        self.assertEqual(self.run_main("success", quiet)[1]["action"], "nothing")
        self.assertEqual(quiet.writes(), [])

    def test_the_issue_is_found_on_a_later_page(self):
        api = FakeApi([issue(n, author="someone") for n in range(1, 151)] + [issue(200)])
        code, said, _ = self.run_main("failure", api)
        self.assertEqual((code, said["action"], said["issue"]), (0, "comment", 200))
        self.assertEqual([path for method, path, _ in api.calls if method == "GET"][-1][-6:], "page=2")
        self.assertNotIn("creator=", api.calls[0][1])  # the filter is tracked()'s, never a query that may match nothing

    def test_too_many_open_issues_is_an_error_not_a_new_issue(self):
        api = FakeApi([issue(n, author="someone") for n in range(1, tracker.PAGES * 100 + 1)])
        code, said, err = self.run_main("failure", api)
        self.assertEqual((code, said), (4, None))
        self.assertEqual(api.writes(), [])
        self.assertIn("::error", err)

    def test_a_dry_run_says_what_it_would_do_and_writes_nothing(self):
        api = FakeApi([issue(12)])
        code, said, _ = self.run_main("success", api, "--dry-run", with_token=False)
        self.assertEqual((code, said), (0, {"action": "close", "issue": 12, "dry_run": True}))
        self.assertEqual(api.writes(), [])

    def test_an_issue_that_could_not_be_written_fails_the_job(self):
        for fail_on in ("GET", "POST /repos/nulavio/nulavio/issues"):
            code, said, err = self.run_main("failure", FakeApi(fail_on=fail_on))
            self.assertEqual((code, said), (4, None), fail_on)
            self.assertIn("::error title=Nightly rehearsal::", err)

    def test_arguments_of_another_shape_are_refused_before_any_request(self):
        for args in (
            ["--result", "failure", "--sha", "abc", "--run-url", RUN, "--repo", REPO],
            ["--result", "failure", "--sha", SHA, "--run-url", "https://example.org/actions/runs/1", "--repo", REPO],
            ["--result", "failure", "--sha", SHA, "--run-url", RUN + "\n## injected", "--repo", REPO],
            ["--result", "failure", "--sha", SHA, "--run-url", RUN, "--repo", "nulavio"],
            ["--result", "cancelled", "--sha", SHA, "--run-url", RUN, "--repo", REPO],
        ):
            api = FakeApi()
            with (
                mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as stop,
            ):
                tracker.main(args, api=api)
            self.assertEqual(stop.exception.code, 2, args)
            self.assertEqual(api.calls, [])

    def test_without_a_token_nothing_is_asked(self):
        api = FakeApi()
        code, _, _ = self.run_main("failure", api, with_token=False)
        self.assertEqual(code, 2)
        self.assertEqual(api.calls, [])


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (WORKFLOWS / "rehearsal.yml").read_text(encoding="utf-8")
        body = cls.text.split("\njobs:\n", 1)[1]
        cls.jobs = {m.group(1): m.group(2) for m in re.finditer(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", body, re.M | re.S)}

    def test_it_runs_at_night_and_by_hand_from_main_only(self):
        self.assertRegex(self.text, r'(?m)^  schedule:\n    - cron: "\d+ \d+ \* \* \*"')
        self.assertIn("workflow_dispatch:", self.text)
        self.assertEqual(sorted(self.jobs), ["build", "changes", "report"])
        for name, job in self.jobs.items():
            self.assertIn("github.ref == 'refs/heads/main'", job, name)
        self.assertIn("group: rehearsal", self.text)  # never queued with a release
        self.assertNotRegex(self.text, r"(?m)^  group: release$")

    def test_it_rehearses_as_the_release_build_does(self):
        build = self.jobs["build"]
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        for same in (
            "runs-on: blacksmith-16vcpu-ubuntu-2404",
            "environment: build",
            "NULAVIO_BUILD_PROFILE: runner",
            "NULAVIO_INTEGRATION_IMAGE: fedora-release-itest",
            "scripts/ci/apt_install.sh libsodium23 gocryptfs fuse3",
            "fetch-depth: 0",
        ):
            self.assertIn(same, build, same)
            self.assertIn(same, release, same)
        self.assertIn('scripts/release/rehearse_release.sh "$firefox" "$RUNNER_TEMP/rehearsal"', build)
        self.assertIn('rm -f "$HOME/.config/nulavio-build/google-safebrowsing.key"', build)
        self.assertNotIn("NULAVIO_MOZCONFIG_EXTRA", self.text)  # the release configuration, never a variant

    def test_it_is_never_a_release(self):
        for word in (
            "id-token",
            "attestations",
            "attest-build-provenance",
            "R2_",
            "AWS_",
            "publish_release",
            "sign_repo",
            "gh release",
        ):
            self.assertNotIn(word, self.text, word)
        self.assertNotIn("packages/", self.text)  # no package leaves the runner: the report and the logs only
        self.assertEqual(re.findall(r"(?m)^ {6}([\w-]+): write", self.text), ["issues"])
        self.assertIn("issues: write", self.jobs["report"])
        self.assertNotIn("secrets.", self.jobs["report"] + self.jobs["changes"])

    def test_the_build_waits_for_something_new_and_the_issue_for_a_verdict(self):
        self.assertIn("needs.changes.outputs.build == 'true'", self.jobs["build"])
        self.assertIn("python3 -I scripts/ci/rehearsal_needed.py", self.jobs["changes"])
        self.assertIn("actions: read", self.jobs["changes"])
        report = self.jobs["report"]
        self.assertIn("always()", report)
        self.assertIn("needs.build.result == 'success' || needs.build.result == 'failure'", report)
        self.assertIn("RESULT: ${{ needs.build.result }}", report)  # through env:, never inside the script
        self.assertIn('[ "$EVENT" = schedule ] || dry=(--dry-run)', report)  # by hand it writes to no issue
        self.assertIn('--result "$RESULT" --sha "$GITHUB_SHA" --run-url "$RUN_URL"', report)
        self.assertNotRegex(report, r"rehearsal_issue\.py[^\n]*\n?[^\n]*\|")  # a pipe would hide its exit status


if __name__ == "__main__":
    unittest.main()
