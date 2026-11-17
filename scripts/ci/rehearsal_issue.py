#!/usr/bin/env python3
"""Keep one issue that says the nightly rehearsal of main fails (#378, rehearsal.yml).

    python3 -I scripts/ci/rehearsal_issue.py --result success|failure --sha SHA --run-url URL --repo OWNER/NAME [--dry-run]

Some tests run only on a build of main (the Vault with FUSE, the release container, a build of a
new version): pull requests do not run them, so a merge can break them unseen and the next release
run stops an hour in. The nightly rehearsal runs them; this tells people when it fails.

- failure, no open issue: one is opened (labels bug and P1), with the run and what to do;
- failure, an issue open: a comment with the new run;
- success, an issue open: a comment, and the issue is closed;
- success, no issue: nothing.

The issue is found by a hidden marker in its body, and only an issue the workflow's bot opened
counts, so nobody else's issue is commented on or closed. It talks only to api.github.com, with
GITHUB_TOKEN (issues: write). The commit and the run's address come from the workflow, are checked
for their shape, and nothing from outside is put into the text.
Exit status: 0 done; 2 a bad argument; 4 the issue could not be written (the job fails, and
GitHub's own failure notice is then the alert). Output: {"action": ..., "issue": ...} as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
BOT = "github-actions[bot]"
MARKER = "<!-- nulavio-nightly-rehearsal -->"
TITLE = "The nightly rehearsal of main fails: tests that only a build of main runs"
LABELS = ["bug", "P1"]
PAGES = 20  # of 100 open issues and pull requests
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_RE = re.compile(r"^https://github\.com/[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}/actions/runs/[0-9]{1,20}$")


class IssueError(RuntimeError):
    pass


# -- pure (tests/unit/test_rehearsal_issue.py) ------------------------------------------------------


def body(sha: str, run_url: str) -> str:
    return "\n".join(
        [
            MARKER,
            "## Problem",
            "",
            f"The nightly rehearsal of `main` failed at `{sha[:12]}`: {run_url}",
            "",
            "The rehearsal builds `main` as a release is built and runs what pull requests do not: the whole",
            "integration suite on that build, in the release's own container, with the Vault on FUSE, then the",
            "packages and their checks (`scripts/release/rehearse_release.sh`). A release run started now would",
            "stop at the same place, about an hour in.",
            "",
            "## What to do",
            "",
            "- Open the run: its summary has the rehearsal's table of steps, and the `rehearsal-logs` artifact",
            "  has the log of the step that failed.",
            "- The merges since the last green night are the suspects. A test that fails only sometimes is",
            "  fixed too: it fails a release run the same way.",
            "- This issue is closed by the next green night. Nothing needs to be done to it by hand.",
            "",
            "Opened by `rehearsal.yml` (`scripts/ci/rehearsal_issue.py`). Refs #378.",
        ]
    )


def comment(result: str, sha: str, run_url: str) -> str:
    if result == "success":
        return f"Green again at `{sha[:12]}`: {run_url}. Closing."
    return f"Still failing at `{sha[:12]}`: {run_url}"


def tracked(issues: list[dict], author: str = BOT) -> dict | None:
    """The open issue this script keeps: the bot's own, with the marker. The oldest, should there be two."""
    ours = [
        issue
        for issue in issues
        if "pull_request" not in issue
        and issue.get("state") == "open"
        and (issue.get("user") or {}).get("login") == author
        and MARKER in (issue.get("body") or "")
    ]
    return min(ours, key=lambda issue: issue["number"]) if ours else None


def plan(result: str, issue: dict | None) -> str:
    """What to do: "open", "comment", "close" or "nothing"."""
    if result == "failure":
        return "comment" if issue else "open"
    return "close" if issue else "nothing"


# -- api.github.com ---------------------------------------------------------------------------------


def call(token: str, method: str, path: str, payload: dict | None = None):
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        f"{API}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            **({"Authorization": f"Bearer {token}"} if token else {}),  # a dry run of a public repository needs none
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nulavio-rehearsal-issue",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https host
            return json.loads(response.read() or b"null")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise IssueError(f"{method} {path}: {error}") from None


def open_issues(api, token: str, repo: str) -> list[dict]:
    """Every open issue (pull requests come along and tracked() drops them): the filter is tracked()'s,
    not a query parameter that could quietly match nothing and have a new issue opened every night."""
    found: list[dict] = []
    for page in range(1, PAGES + 1):
        items = api(token, "GET", f"/repos/{repo}/issues?state=open&per_page=100&page={page}")
        if not isinstance(items, list):
            raise IssueError("the list of open issues is not a list")
        found += [item for item in items if isinstance(item, dict)]
        if len(items) < 100:
            return found
    raise IssueError(f"more than {PAGES * 100} open issues and pull requests: the tracked issue may be missed")


def main(argv: list[str] | None = None, *, api=call) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--result", required=True, choices=("success", "failure"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true", help="say what would be done, write nothing")
    args = parser.parse_args(argv)
    if not (REPO_RE.fullmatch(args.repo) and SHA_RE.fullmatch(args.sha) and RUN_RE.fullmatch(args.run_url)):
        parser.error("--repo OWNER/NAME, --sha a full commit, --run-url a run of this kind of repository")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and not args.dry_run:
        parser.error("GITHUB_TOKEN is not set")
    try:
        issue = tracked(open_issues(api, token, args.repo))
        action = plan(args.result, issue)
        number = issue["number"] if issue else None
        if not args.dry_run:
            if action == "open":
                made = api(
                    token,
                    "POST",
                    f"/repos/{args.repo}/issues",
                    {"title": TITLE, "body": body(args.sha, args.run_url), "labels": LABELS},
                )
                number = made["number"]
            elif action in ("comment", "close"):
                api(
                    token,
                    "POST",
                    f"/repos/{args.repo}/issues/{number}/comments",
                    {"body": comment(args.result, args.sha, args.run_url)},
                )
                if action == "close":
                    api(token, "PATCH", f"/repos/{args.repo}/issues/{number}", {"state": "closed", "state_reason": "completed"})
    except (IssueError, KeyError, TypeError) as error:
        print(f"::error title=Nightly rehearsal::the issue could not be written: {error}", file=sys.stderr)
        return 4
    print(json.dumps({"action": action, "issue": number, "dry_run": args.dry_run}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
