#!/usr/bin/env python3
"""Open, update and close the GitHub issue that tracks each newer Firefox release.

Reads the report of `scripts/release/watch_upstream.py --json` and keeps one
issue per Firefox version, found by a hidden marker in its body
(`<!-- nulavio-upstream firefox=159.0 fp=... phase=... urgency=... -->`):

- a new version gets an issue that @mentions the maintainer (GitHub sends e-mail and push);
- when something changes, the body is rewritten (that alone notifies nobody);
- an escalation (published, urgency raised, exploitation in the wild, target
  missed, deadline passed, signature failure) adds a comment that @mentions the maintainer;
- when engine.json reaches the version the issue is closed; reopened if it falls behind again.

    python3 -I scripts/release/upstream_issue.py --status FILE --repo OWNER/NAME [--mention LOGIN] [--dry-run]

Talks only to api.github.com, with GITHUB_TOKEN (issues: write). Only issues
opened by the workflow's bot count. Text from outside (advisory titles, errors)
is made inert: no mentions, HTML, issue links or tables. An alert that could not
be written (the issues could not be listed while there are newer releases, or an
issue could not be opened, reopened or commented on) is an error and exits 4, so
the job fails and GitHub's failure e-mail reaches the maintainer. Labels, body
rewrites and closing only warn. Exit status: 0 done, skipped or warned; 3 the
status file is not a watcher report; 4 an alert was not delivered.
Output: {"actions": [...], "warnings": [...], "errors": [...]} as JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch_upstream  # noqa: E402
from watch_upstream import plain  # noqa: E402

API = "https://api.github.com"
BOT = "github-actions[bot]"
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
MARKER_RE = re.compile(r"<!-- nulavio-upstream ((?:[a-z_]+=[^\s<>]* ?)+) -->")
LABELS = {
    "upstream-firefox": ("1d76db", "A newer Firefox release Nulavio has to ship (scripts/release/upstream_issue.py)"),
    "target-24h": ("b60205", "Urgent Firefox release: 24-hour target (72-hour deadline)"),
    "target-72h": ("fbca04", "Standard Firefox release: 72-hour deadline"),
    "exploited-in-the-wild": ("000000", "Mozilla reports exploitation in the wild"),
}
PHASES = ("unconfirmed", "staged", "shipped")
URGENCIES = ("standard", "urgent")
PAGES = 3
ALERTS = ("create", "reopen", "comment")  # each @mentions the maintainer (a reopen comes with its comment)
EXIT_NOT_ALERTED = 4


class StatusError(ValueError):
    """The status file is not a watcher report (schema 2)."""


class ApiError(Exception):
    """GitHub's API refused or could not be reached."""


# --- reading the watcher's report --------------------------------------------


def load_status(path: Path) -> dict:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StatusError(f"cannot read {path}: {exc}") from exc
    if not isinstance(report, dict) or report.get("schema") != 2 or not isinstance(report.get("targets"), list):
        raise StatusError("not a watch_upstream.py schema-2 report")
    if report.get("state") == "unavailable":
        return report
    pinned = (report.get("pinned") or {}).get("firefox")
    if not isinstance(pinned, str) or not watch_upstream.RELEASE_RE.match(pinned):
        raise StatusError("the report has no pinned Firefox version")
    for target in report["targets"]:
        if (
            not isinstance(target, dict)
            or not watch_upstream.RELEASE_RE.match(str(target.get("version")))
            or target.get("phase") not in PHASES
            or target.get("urgency") not in URGENCIES
            or not isinstance(target.get("target_hours"), int)
            or not isinstance(target.get("deadline_hours"), int)
            or not isinstance(target.get("reasons"), list)
        ):
            raise StatusError(f"unexpected target in the report: {str(target)[:200]}")
    return report


def fields(target: dict) -> dict[str, str]:
    """What the issue shows, in the marker: a change rewrites the body; some changes notify."""
    verified = {True: "1", False: "0"}.get(target.get("verified"), "-")
    ids = ",".join(sorted(a["id"] for a in target.get("advisories") or [] if watch_upstream.mfsa.ID_RE.match(str(a.get("id")))))
    return {
        "phase": target["phase"],
        "urgency": target["urgency"],
        "itw": target.get("itw") if target.get("itw") in ("yes", "no", "unclear", "unknown") else "unknown",
        "missed": "1" if target.get("target_missed") else "0",
        "overdue": "1" if target.get("overdue") else "0",
        "verified": verified,
        "advisories": ids or "-",
        "status": str(target.get("advisory_status") or "-"),
        "target": target.get("target") or "-",
        "deadline": target.get("deadline") or "-",
    }


def fingerprint(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def marker(version: str, values: dict[str, str]) -> str:
    keys = ("phase", "urgency", "itw", "missed", "overdue", "verified")
    return (
        f"<!-- nulavio-upstream firefox={version} fp={fingerprint(values)} " + " ".join(f"{k}={values[k]}" for k in keys) + " -->"
    )


def parse_marker(body: str | None) -> dict[str, str] | None:
    match = MARKER_RE.search(body or "")
    if not match:
        return None
    values = dict(part.split("=", 1) for part in match.group(1).split())
    return values if watch_upstream.RELEASE_RE.match(values.get("firefox", "")) else None


def escalations(old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Changes worth a notification (a comment with the @mention); body edits alone notify nobody."""
    reasons = []
    if new["verified"] == "0" and old.get("verified") != "0":
        reasons.append("signature verification FAILED")
    if new["phase"] == "shipped" and old.get("phase") != "shipped":
        reasons.append("Mozilla published it: the clock is running")
    if new["urgency"] == "urgent" and old.get("urgency") != "urgent" and new["status"] != "unavailable":
        reasons.append("urgency raised to URGENT (24 h target)")  # not for a passing network failure
    if new["itw"] == "yes" and old.get("itw") != "yes":
        reasons.append("Mozilla reports exploitation in the wild")
    if new["missed"] == "1" and old.get("missed") != "1":
        reasons.append("the target passed")
    if new["overdue"] == "1" and old.get("overdue") != "1":
        reasons.append("OVERDUE: the 72-hour deadline passed")
    return reasons


# --- what the issue says -------------------------------------------------------


def _when(stamp: str | None) -> str:
    return watch_upstream._when(stamp) if stamp else "starts when Mozilla publishes"


def _hex(value) -> str:
    return f"`{value}`" if isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{16,64}", value) else plain(value or "?", 80)


def title(target: dict) -> str:
    version = target["version"]
    if target.get("verified") is False:
        text = f"Firefox {version}: signature verification FAILED, do not build"
    elif target["phase"] != "shipped":
        text = f"Firefox {version} staged ({target['urgency']}): the clock starts when Mozilla publishes"
    elif target.get("overdue"):
        text = f"Firefox {version} released: Nulavio update OVERDUE since {_when(target.get('deadline'))}"
    else:
        goal, deadline = _when(target.get("target")), _when(target.get("deadline"))
        text = f"Firefox {version} released ({target['urgency']}): target {goal}, deadline {deadline}"
    return text[:120]


def labels_for(target: dict) -> list[str]:
    names = ["upstream-firefox", "target-24h" if target["urgency"] == "urgent" else "target-72h"]
    if target.get("emergency") or target.get("itw") == "yes":
        names.append("exploited-in-the-wild")
    return names


def body(target: dict, report: dict, mention: str | None) -> str:
    version, pinned = target["version"], report["pinned"]["firefox"]
    values = fields(target)
    if target["phase"] == "shipped":
        clock = (
            "product-details commit"
            if target.get("clock_source") == "product-details-commit"
            else "start of the day, time unknown"
        )
        head = f"**Firefox {version}** was released {_when(target.get('released_at'))} ({clock}). Nulavio ships {pinned}."
    elif target.get("verified") is False:
        head = f"**Firefox {version}** is on archive.mozilla.org but its signature did NOT verify. Nothing may be built from it."
    else:
        head = f"**Firefox {version}** is staged on archive.mozilla.org, not published yet. Nulavio ships {pinned}."
    if target.get("verified") is True:
        signature = f"verified: primary {_hex(target.get('signing_primary'))}, subkey {_hex(target.get('signing_subkey'))}"
    elif target.get("verified") is False:
        signature = f"FAILED: {plain(target.get('verification_error') or '?', 200)}"
    else:
        signature = "not checked yet"
    if target.get("target"):
        goal = f"{_when(target['target'])} ({target['target_hours']} h){' MISSED' if target.get('target_missed') else ''}"
        deadline = f"{_when(target['deadline'])} ({target['deadline_hours']} h){' OVERDUE' if target.get('overdue') else ''}"
    else:
        goal = f"{target['target_hours']} h from Mozilla's publication"
        deadline = f"{target['deadline_hours']} h from Mozilla's publication"
    advisories = "<br>".join(
        f"[{a['id']}]({watch_upstream.mfsa.ADVISORY_URL.format(id=a['id'])}) ({plain(a.get('impact'), 20)}): "
        f"{plain(a.get('title'), 120)}"
        for a in target.get("advisories") or []
        if watch_upstream.mfsa.ID_RE.match(str(a.get("id")))
    ) or plain(target.get("advisory_status") or "none")
    digest = target.get("source_sha256")
    rows = [
        ("Urgency", f"{target['urgency'].upper()}: {plain('; '.join(target.get('reasons') or []))}"),
        ("Target", goal),
        ("Policy deadline", deadline),
        ("Exploited in the wild", plain(values["itw"])),
        ("Public exploit code", "yes" if target.get("public_exploit") else "no"),
        ("Platform notes", plain("; ".join(target.get("platform_notes") or []) or "none")),
        ("Signature", signature),
        ("Source tarball SHA-256", f"`{digest}`" if digest and watch_upstream.SHA256_RE.match(digest) else "not verified"),
        ("Advisories", advisories),
    ]
    lines = [marker(version, values), head, "", "| | |", "|---|---|"] + [f"| {name} | {value} |" for name, value in rows]
    if target.get("verified") is False:
        lines += [
            "",
            "Do not build. Check Mozilla's announcements for a key rotation (docs/architecture/update-policy.md, Key rotation).",
        ]
    else:
        lines += [
            "",
            "Next steps:",
            "",
            "1. Take the pre-built worktree from the local autobuild (scripts/release/autobuild.py), or run "
            f"`python3 -I scripts/release/bump_engine.py {version}` and `scripts/release/rehearse_release.sh {version}`.",
            "2. Review the diff and commit; sign and publish only what `manifest.json` lists.",
            "3. Add the entry to `docs/security/changelog.md`.",
        ]
    if report.get("errors"):
        lines += ["", "Problems in the last check:", ""] + [f"- {plain(error, 200)}" for error in report["errors"][:10]]
    lines += ["", f"Updated {_when(report.get('checked_at'))} by the `upstream` workflow (scripts/release/upstream_issue.py)."]
    if mention:
        lines += ["", f"cc @{mention}"]
    return "\n".join(lines)


def comment(target: dict, reasons: list[str], mention: str | None) -> str:
    who = f"@{mention} " if mention else ""
    goal = f"target {_when(target.get('target'))}, deadline {_when(target.get('deadline'))}"
    return f"{who}Firefox {target['version']}: {'; '.join(reasons)}. Urgency {target['urgency'].upper()}; {goal}."


# --- the plan (pure) ---------------------------------------------------------------


def tracked(issues: list[dict], author: str) -> dict[str, dict]:
    """Issues opened by the bot with a marker, newest per version (open ones first)."""
    found: dict[str, dict] = {}
    for issue in issues:
        if "pull_request" in issue or (issue.get("user") or {}).get("login") != author:
            continue
        values = parse_marker(issue.get("body"))
        if not values:
            continue
        version = values["firefox"]
        known = found.get(version)
        rank = (issue.get("state") == "open", issue.get("number", 0))
        if known is None or rank > (known["state"] == "open", known["number"]):
            found[version] = {"number": issue["number"], "state": issue.get("state"), "values": values}
    return found


def plan(report: dict, issues: list[dict], *, mention: str | None, author: str = BOT) -> list[dict]:
    """The issue operations that bring GitHub in line with the report."""
    if report.get("state") == "unavailable":
        return []
    pinned = report["pinned"]["firefox"]
    existing = tracked(issues, author)
    actions: list[dict] = []
    seen = set()
    for target in report["targets"]:
        version = target["version"]
        if target["phase"] == "unconfirmed" and target.get("verified") is not False:
            continue  # on the archive but not verified yet (network): nothing to say
        seen.add(version)
        new = fields(target)
        issue = existing.get(version)
        content = {"title": title(target), "body": body(target, report, mention), "labels": labels_for(target)}
        if issue is None:
            actions.append({"op": "create", "version": version, "reason": "new Firefox release", **content})
            continue
        number, old = issue["number"], issue["values"]
        if issue["state"] != "open":
            actions.append(
                {"op": "reopen", "version": version, "issue": number, "reason": "Nulavio is behind it again", **content}
            )
            reasons = ["Nulavio is behind it again", *escalations(old, new)]
            actions.append(
                {
                    "op": "comment",
                    "version": version,
                    "issue": number,
                    "reason": "; ".join(reasons),
                    "body": comment(target, reasons, mention),
                }
            )
            continue
        if old.get("fp") == fingerprint(new):
            continue
        actions.append({"op": "update", "version": version, "issue": number, "reason": "the release's status changed", **content})
        reasons = escalations(old, new)
        if reasons:
            actions.append(
                {
                    "op": "comment",
                    "version": version,
                    "issue": number,
                    "reason": "; ".join(reasons),
                    "body": comment(target, reasons, mention),
                }
            )
    for version, issue in sorted(existing.items()):
        if version in seen or issue["state"] != "open":
            continue
        if watch_upstream.version_key(version) <= watch_upstream.version_key(pinned):
            note = f"engine.json now pins Firefox {pinned}, which includes {version}. Closing."
            actions.append({"op": "close", "version": version, "issue": issue["number"], "reason": "shipped", "body": note})
    return actions


# --- GitHub -----------------------------------------------------------------------


class GitHub:
    """The few issue endpoints this needs, on api.github.com only."""

    def __init__(self, repo: str, token: str, opener=None):
        if not REPO_RE.match(repo):
            raise ValueError(f"not an OWNER/NAME repository: {repo!r}")
        self.repo, self.token = repo, token
        self.opener = opener or urllib.request.build_opener()

    def call(self, method: str, path: str, payload: dict | None = None, accept_codes=(200, 201)) -> tuple[int, object]:
        url = f"{API}/repos/{self.repo}/{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - fixed https host
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "nulavio-upstream-issue")
        request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(8 << 20)
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in accept_codes:
                return exc.code, None
            raise ApiError(f"{method} {path}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
            raise ApiError(f"{method} {path}: {exc}") from None

    def issues(self) -> list[dict]:
        found: list[dict] = []
        for page in range(1, PAGES + 1):
            _, items = self.call("GET", f"issues?state=all&per_page=100&page={page}")
            if not isinstance(items, list):
                raise ApiError("unexpected answer listing issues")
            found += [item for item in items if isinstance(item, dict)]
            if len(items) < 100:
                break
        return found

    def ensure_labels(self, names: list[str]) -> None:
        for name in names:
            color, description = LABELS[name]
            self.call("POST", "labels", {"name": name, "color": color, "description": description}, accept_codes=(200, 201, 422))

    def create(self, title: str, body: str, labels: list[str]) -> int:
        _, issue = self.call("POST", "issues", {"title": title, "body": body, "labels": labels})
        return issue["number"]

    def update(self, number: int, **changes) -> None:
        self.call("PATCH", f"issues/{int(number)}", changes)

    def comment(self, number: int, text: str) -> None:
        self.call("POST", f"issues/{int(number)}/comments", {"body": text})


def not_done(actions: list[dict], cause, warnings: list[str], errors: list[str]) -> None:
    """Report actions the API failure stopped: an error if an alert is among them, else a warning."""
    missed = sorted({a["version"] for a in actions if a["op"] in ALERTS}, key=watch_upstream.version_key)
    if missed:
        errors.append(f"alert not delivered for Firefox {', '.join(missed)}: {cause}")
    else:
        warnings.append(f"GitHub API unavailable, issue not updated: {cause}")


def apply(api, actions: list[dict], warnings: list[str], errors: list[str]) -> list[dict]:
    """Carry out the plan; stop at the first API failure (labels only warn)."""
    done: list[dict] = []
    labels_ok = True
    wanted = sorted({name for action in actions for name in action.get("labels", [])})
    if wanted:
        try:
            api.ensure_labels(wanted)
        except ApiError as exc:
            labels_ok = False
            warnings.append(f"labels unavailable, continuing without them: {exc}")
    try:
        for action in actions:
            labels = action.get("labels", []) if labels_ok else []
            op = action["op"]
            if op == "create":
                action = {**action, "issue": api.create(action["title"], action["body"], labels)}
            elif op in ("update", "reopen"):
                changes = {"title": action["title"], "body": action["body"]}
                if labels_ok:
                    changes["labels"] = labels
                if op == "reopen":
                    changes["state"] = "open"
                api.update(action["issue"], **changes)
            elif op == "comment":
                api.comment(action["issue"], action["body"])
            elif op == "close":
                api.comment(action["issue"], action["body"])
                api.update(action["issue"], state="closed", state_reason="completed")
            done.append({key: action[key] for key in ("op", "version", "issue", "reason") if key in action})
    except ApiError as exc:
        not_done(actions[len(done) :], exc, warnings, errors)
    return done


def _annotation(text: str) -> str:
    """One line, no workflow-command syntax from outside data."""
    return re.sub(r"\s+", " ", text).replace("::", ": :")


def main(argv: list[str] | None = None, *, api=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status", type=Path, required=True, help="watch_upstream.py --json output")
    parser.add_argument("--repo", required=True, help="OWNER/NAME (in Actions: $GITHUB_REPOSITORY)")
    parser.add_argument("--mention", help="GitHub login to @mention on new releases and escalations")
    parser.add_argument("--author", default=BOT, help=f"only issues opened by this login count (default {BOT})")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    args = parser.parse_args(argv)
    if args.mention and not LOGIN_RE.match(args.mention):
        parser.error("--mention must be a GitHub login")
    try:
        report = load_status(args.status)
    except StatusError as exc:
        print(f"::error::upstream_issue: {_annotation(str(exc))}")
        return 3
    warnings: list[str] = []
    errors: list[str] = []
    actions: list[dict] = []
    try:
        if api is None:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise ApiError("GITHUB_TOKEN is not set")
            api = GitHub(args.repo, token)
        actions = plan(report, api.issues(), mention=args.mention, author=args.author)
        if not args.dry_run:
            actions = apply(api, actions, warnings, errors)
    except (ApiError, ValueError) as exc:
        # The issues could not be listed: each newer release may be an alert nobody got.
        not_done(plan(report, [], mention=args.mention, author=args.author), exc, warnings, errors)
    for warning in warnings:
        print(f"::warning::upstream_issue: {_annotation(warning)}")
    for error in errors:
        print(f"::error::upstream_issue: {_annotation(error)}")
    shown = [{key: action[key] for key in ("op", "version", "issue", "reason") if key in action} for action in actions]
    print(json.dumps({"actions": shown, "warnings": warnings, "errors": errors}, indent=2))
    return EXIT_NOT_ALERTED if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
