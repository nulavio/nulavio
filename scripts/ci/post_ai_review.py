#!/usr/bin/env python3
"""Post the advisory AI review as one pull request comment (job "publish" of .github/workflows/ai-review.yml).

The model's output is untrusted: the model read the pull request, which can
carry prompt injection. This script is the only thing that writes to GitHub,
and it does so deterministically:

- it validates the result against .github/ai-review/schema.json again (types,
  enums, lengths, counts); an invalid finding is dropped, an invalid document
  becomes an "AI review produced no valid result" notice;
- it drops findings whose file is neither in the pull request nor in the base
  tree (an invented path is a sign the model was misled);
- it strips control, bidirectional and invisible characters, redacts
  secret-like strings, neutralises @mentions and HTML comments, and shows
  every model-written field as plain text inside a code fence longer than any
  backtick run in it (no links, images, HTML or mentions);
- it caps the comment below GitHub's size limit;
- it creates or updates one issue comment marked ``<!-- nulavio-ai-review -->``.
  It never calls the reviews API, so it can never approve or request changes.

GitHub is reached through the ``gh`` CLI, which handles authentication
(``GH_TOKEN`` in Actions, the keyring locally), so no token passes through this
script. Without ``--post`` it only prints the comment.

    RESULT='{...}' python3 -I scripts/ci/post_ai_review.py --post          # in Actions
    claude -p ... --output-format json | python3 -I scripts/ci/post_ai_review.py --stdin --repo O/R --pr 7 --head-sha SHA

Exit status: 0 the comment was posted (or printed); 1 the result was invalid
(a notice was posted); 2 a usage or GitHub API error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / ".github" / "ai-review" / "schema.json"
MARKER = "<!-- nulavio-ai-review -->"
MAX_COMMENT = 60_000  # GitHub's limit is 65,536 characters
MAX_RAW_RESULT = 1_000_000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PR_RE = re.compile(r"^[1-9][0-9]{0,9}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9 ._(),:/-]{1,120}$")
RUN_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+$")
PATH_RE = re.compile(r"^[A-Za-z0-9._@+-]+(?:/[A-Za-z0-9._@+-]+)*$")
SEVERITIES = ("critical", "high", "medium", "low")
SCHEMA_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "minLength",
    "maxLength",
    "maxItems",
    "minimum",
    "maximum",
    "description",
}
ARRAYS = ("findings", "injection_attempts", "not_checked")
# Control, bidirectional, zero-width and tag characters (the last are used to hide instructions).
INVISIBLE_RE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
)
DISCLAIMER = "**Not an approval.** It can miss problems and can be misled by the content it reviews. A human reviewer decides."


class InvalidResult(Exception):
    """The model's output cannot be used."""


class ApiError(Exception):
    """A GitHub API call failed."""


# --- schema validation (the subset of JSON Schema that schema.json uses) ---------------------------------------------


def check_schema_keywords(schema: Any, where: str = "$") -> None:
    """Refuse keywords this validator does not implement, so the schema cannot silently outgrow it."""
    if not isinstance(schema, dict):
        raise ValueError(f"{where}: schema nodes must be objects")
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(f"{where}: unsupported schema keywords {sorted(unknown)}")
    for name, sub in (schema.get("properties") or {}).items():
        check_schema_keywords(sub, f"{where}.{name}")
    if "items" in schema:
        check_schema_keywords(schema["items"], f"{where}[]")


def validate(value: Any, schema: dict, path: tuple = ()) -> list[tuple[tuple, str]]:
    """Return (path, problem) pairs; an empty list means the value is valid."""
    kind = schema.get("type")
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }
    if kind not in checks:
        raise ValueError(f"unsupported schema type {kind!r}")
    if not checks[kind]:
        return [(path, f"must be {kind}")]
    errors: list[tuple[tuple, str]] = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append((path, "is not an allowed value"))
    if kind == "string":
        if len(value) < schema.get("minLength", 0):
            errors.append((path, "is too short"))
        if len(value) > schema.get("maxLength", len(value)):
            errors.append((path, f"is longer than {schema['maxLength']} characters"))
    elif kind == "integer":
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append((path, "is out of range"))
    elif kind == "array":
        if len(value) > schema.get("maxItems", len(value)):
            errors.append((path, f"has more than {schema['maxItems']} items"))
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], (*path, index)))
    else:
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(((*path, name), "is missing"))
        for name, item in value.items():
            if name in properties:
                errors.extend(validate(item, properties[name], (*path, name)))
            elif schema.get("additionalProperties") is False:
                errors.append(((*path, name), "is not allowed"))
    return errors


def show_path(path: tuple) -> str:
    """A JSON path for messages; keys written by the model are not echoed unless they are plain words."""

    def part(item: object) -> str:
        if isinstance(item, int):
            return f"[{item}]"
        return f".{item}" if re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(item)) else ".<unexpected key>"

    return "$" + "".join(part(item) for item in path)


# --- the review ------------------------------------------------------------------------------------------------------


@dataclass
class Review:
    summary: str
    findings: list[dict]
    injection_attempts: list[dict]
    not_checked: list[str]
    notes: list[str] = field(default_factory=list)


def parse_result(raw: str, schema: dict) -> Review:
    """Parse and re-validate the model's structured output (or Claude Code's ``--output-format json`` envelope)."""
    raw = raw.strip()
    if not raw:
        raise InvalidResult("the review job passed no result (a job output that looks like a secret is dropped by GitHub)")
    if len(raw) > MAX_RAW_RESULT:
        raise InvalidResult("the result is unexpectedly large")
    try:
        data = json.loads(raw)
    except ValueError:
        raise InvalidResult("the result is not JSON") from None
    if isinstance(data, dict) and data.get("type") == "result":
        subtype = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("subtype")))[:40] or "unknown"
        data = data.get("structured_output")
        if data is None:
            raise InvalidResult(f"Claude Code ended without a structured result ({subtype})")
    notes: list[str] = []
    if isinstance(data, dict):
        for name in ARRAYS:
            limit = schema["properties"][name]["maxItems"]
            if isinstance(data.get(name), list) and len(data[name]) > limit:
                data[name] = data[name][:limit]
                notes.append(f"{name}: only the first {limit} items are kept")
    drop: dict[str, set[int]] = {name: set() for name in ARRAYS}
    fatal = []
    for path, problem in validate(data, schema):
        if len(path) >= 2 and path[0] in ARRAYS and isinstance(path[1], int):
            if path[1] not in drop[path[0]]:
                notes.append(f"{path[0]} item {path[1] + 1} dropped: {show_path(path)} {problem}")
            drop[path[0]].add(path[1])
        else:
            fatal.append(f"{show_path(path)} {problem}")
    if fatal:
        raise InvalidResult("the result does not match the schema: " + "; ".join(fatal[:5]))
    kept = {name: [item for index, item in enumerate(data[name]) if index not in drop[name]] for name in ARRAYS}
    return Review(data["summary"], kept["findings"], kept["injection_attempts"], kept["not_checked"], notes)


def normalise_path(value: str) -> str | None:
    path = value.strip()
    path = path.removeprefix("./")
    if len(path) > 300 or not PATH_RE.match(path) or any(part in (".", "..") for part in path.split("/")):
        return None
    return path


def filter_findings(review: Review, known: set[str] | None) -> Review:
    """Keep findings that name a real repository-relative file; ``known=None`` means the files could not be listed."""
    kept, dropped = [], 0
    for finding in review.findings:
        path = normalise_path(finding["file"])
        if path is None or (known is not None and path not in known):
            dropped += 1
            continue
        kept.append({**finding, "file": path})
    review.findings = kept
    if dropped:
        review.notes.append(f"{dropped} finding(s) dropped: the file is neither in this pull request nor in the base branch")
    if known is None:
        review.notes.append("file names were not checked against the repository")
    return review


# --- rendering ---------------------------------------------------------------------------------------------------------


@dataclass
class Context:
    repo: str
    pr: str
    head_sha: str
    base_sha: str = ""
    source: str = "local run"
    run_url: str = ""


class Sanitiser:
    def __init__(self) -> None:
        self.redacted = 0

    def __call__(self, text: str) -> str:
        text = INVISIBLE_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
        for pattern in SECRET_PATTERNS:
            text, count = pattern.subn("[redacted]", text)
            self.redacted += count
        text = re.sub(r"@(?=[A-Za-z0-9_-])", "@\u200b", text)
        return text.replace("<!--", "<\u200b!--").replace("-->", "--\u200b>")


def fence(text: str) -> str:
    """Plain text that GitHub shows literally: a code fence longer than any backtick run inside."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{text}\n{ticks}"


def render_finding(number: int, finding: dict, clean: Sanitiser) -> str:
    where = f"`{finding['file']}`" + (f" line {finding['line']}" if "line" in finding else "")
    text = f"{clean(finding['title'])}\n\nEvidence:\n{clean(finding['evidence'])}\n\nFix:\n{clean(finding['fix'])}"
    return f"#### {number}. {finding['severity']} · {finding['invariant']} · {where}\n\n{fence(text)}\n"


def header(ctx: Context) -> str:
    return f"{MARKER}\n## Advisory AI review\n\nAdvisory AI review of {ctx.head_sha} ({ctx.source}). {DISCLAIMER}\n"


def footer(notes: list[str], ctx: Context) -> str:
    items = [*notes]
    if ctx.run_url:
        items.append(f"workflow run: {ctx.run_url}")
    return "\n---\n<sub>" + " · ".join(items) + "</sub>\n" if items else ""


def render(review: Review, ctx: Context) -> tuple[str, int]:
    """Return the comment body and the number of secret-like strings redacted."""
    clean = Sanitiser()
    findings = sorted(review.findings, key=lambda f: SEVERITIES.index(f["severity"]))
    counts = ", ".join(f"{sum(f['severity'] == s for f in findings)} {s}" for s in SEVERITIES)
    summary = f"### Summary\n\n{fence(clean(review.summary))}\n"
    extra = ""
    if review.injection_attempts:
        quotes = "\n".join(f"{clean(item['file'])}: {clean(item['quote'])}" for item in review.injection_attempts)
        extra += (
            "\n### Text in the change that looks like prompt injection\n\n"
            "The reviewer was told to treat it as data. Check that it is a known test fixture, or remove it.\n\n"
            f"{fence(quotes)}\n"
        )
    if review.not_checked:
        extra += "\n### Not checked\n\n" + fence("\n".join(f"- {clean(item)}" for item in review.not_checked)) + "\n"
    blocks = [render_finding(index, finding, clean) for index, finding in enumerate(findings, 1)]
    notes = list(review.notes)
    shown = len(blocks)
    while True:
        hidden = len(blocks) - shown
        tail_notes = [*notes, f"{hidden} lower-severity finding(s) not shown (comment size limit)"] if hidden else notes
        count_line = f"\n### Findings: {len(findings)} ({counts})\n\n" if findings else "\n### Findings: none reported\n\n"
        if not findings:
            count_line += "An empty result is not a pass: an AI review can miss problems.\n"
        body = header(ctx) + "\n" + summary + count_line + "\n".join(blocks[:shown]) + extra
        body += footer(tail_notes + ([f"{clean.redacted} secret-like string(s) redacted"] if clean.redacted else []), ctx)
        if len(body) <= MAX_COMMENT or shown == 0:
            break
        shown -= 1
    if len(body) > MAX_COMMENT:  # cannot happen within the schema's limits; keep the cap anyway
        body = body[: MAX_COMMENT - 20] + "\n[truncated]\n"
    return body, clean.redacted


def render_notice(ctx: Context, reason: str) -> str:
    return header(ctx) + f"\n{reason}\n" + footer([], ctx)


# --- GitHub ------------------------------------------------------------------------------------------------------------


class GhApi:
    """GitHub REST calls through the gh CLI, with argument lists and the request body on stdin."""

    def __init__(self, gh: str = "gh") -> None:
        self.gh = gh

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        args = [self.gh, "api", "--method", method, "-H", "Accept: application/vnd.github+json"]
        args += ["-H", "X-GitHub-Api-Version: 2022-11-28", path]
        if body is not None:
            args += ["--input", "-"]
        try:
            proc = subprocess.run(
                args,
                input=json.dumps(body) if body is not None else None,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ApiError(f"{method} {path}: {error}") from None
        if proc.returncode != 0:
            raise ApiError(f"{method} {path}: " + " ".join(proc.stderr.split())[:300])  # one line: no workflow commands
        return json.loads(proc.stdout) if proc.stdout.strip() else None


def known_files(api: Any, ctx: Context) -> set[str] | None:
    """Files of the pull request plus the base tree; None when the base tree is too large to list."""
    files: set[str] = set()
    for page in range(1, 31):
        batch = api.request("GET", f"repos/{ctx.repo}/pulls/{ctx.pr}/files?per_page=100&page={page}") or []
        for item in batch:
            for key in ("filename", "previous_filename"):
                if isinstance(item, dict) and isinstance(item.get(key), str):
                    files.add(item[key])
        if len(batch) < 100:
            break
    if ctx.base_sha:
        tree = api.request("GET", f"repos/{ctx.repo}/git/trees/{ctx.base_sha}?recursive=1") or {}
        if tree.get("truncated"):
            return None
        files.update(entry["path"] for entry in tree.get("tree", []) if isinstance(entry.get("path"), str))
    return files


def upsert_comment(api: Any, ctx: Context, body: str, author: str) -> str:
    """Update this script's earlier comment on the pull request, or create one."""
    for page in range(1, 51):
        batch = api.request("GET", f"repos/{ctx.repo}/issues/{ctx.pr}/comments?per_page=100&page={page}") or []
        for comment in batch:
            if (comment.get("user") or {}).get("login") == author and str(comment.get("body", "")).startswith(MARKER):
                api.request("PATCH", f"repos/{ctx.repo}/issues/comments/{int(comment['id'])}", {"body": body})
                return "updated"
        if len(batch) < 100:
            break
    api.request("POST", f"repos/{ctx.repo}/issues/{ctx.pr}/comments", {"body": body})
    return "created"


# --- command line ------------------------------------------------------------------------------------------------------


def build_context(args: argparse.Namespace, env: dict) -> Context:
    ctx = Context(
        repo=args.repo or env.get("GITHUB_REPOSITORY", ""),
        pr=args.pr or env.get("PR_NUMBER", ""),
        head_sha=args.head_sha or env.get("HEAD_SHA", ""),
        base_sha=args.base_sha or env.get("BASE_SHA", ""),
        source=args.source or env.get("AI_REVIEW_SOURCE", "") or "local run",
    )
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_SERVER_URL"):
        ctx.run_url = f"{env['GITHUB_SERVER_URL']}/{ctx.repo}/actions/runs/{env['GITHUB_RUN_ID']}"
    problems = [
        name
        for name, ok in (
            ("repository", REPO_RE.match(ctx.repo)),
            ("pull request number", PR_RE.match(ctx.pr)),
            ("head commit", SHA_RE.match(ctx.head_sha)),
            ("base commit", not ctx.base_sha or SHA_RE.match(ctx.base_sha)),
            ("source label", LABEL_RE.match(ctx.source)),
            ("run URL", not ctx.run_url or RUN_URL_RE.match(ctx.run_url)),
        )
        if not ok
    ]
    if problems:
        raise SystemExit(f"invalid {', '.join(problems)}")
    return ctx


def comment_for(args: argparse.Namespace, env: dict, ctx: Context, stdin: Any, api: Any) -> tuple[str, int]:
    status = args.status or env.get("INPUT_STATUS", "") or "ready"
    outcome = args.review_result or env.get("REVIEW_RESULT", "") or "success"
    if status == "too-large":
        size = env.get("DIFF_BYTES", "")
        size_text = f" ({size} bytes)" if size.isdigit() else ""
        reason = f"The diff{size_text} is over the size limit for an AI review. It needs a human-only review."
        return render_notice(ctx, reason), 0
    if status != "ready" or outcome != "success":
        shown = outcome if LABEL_RE.match(outcome) else "unknown"
        return render_notice(ctx, f"The AI review did not complete (job result: {shown}). This is not a pass."), 0
    raw = stdin.read() if args.stdin else env.get("RESULT", "")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    check_schema_keywords(schema)
    try:
        review = parse_result(raw, schema)
    except InvalidResult as error:
        print(f"::error title=AI review::{error}")
        return render_notice(ctx, f"The AI review produced no valid result: {error}. This is not a pass."), 1
    known = None if args.no_file_check or api is None else known_files(api, ctx)
    body, redacted = render(filter_findings(review, known), ctx)
    if redacted:
        print(f"::error title=AI review::the model output held {redacted} secret-like string(s); they were redacted")
    for note in review.notes:
        print(f"note: {note}", file=sys.stderr)
    return body, 0


def comment_author(args: argparse.Namespace, env: dict, api: Any) -> str:
    """Whose earlier comment to update: the Actions bot in CI, otherwise the account gh is logged in as."""
    if args.comment_author:
        return args.comment_author
    if env.get("GITHUB_ACTIONS") == "true":
        return "github-actions[bot]"
    login = (api.request("GET", "user") or {}).get("login")
    if not isinstance(login, str) or not login:
        raise ApiError("GET user: no login in the response")
    return login


def main(argv: list[str] | None = None, env: dict | None = None, stdin: Any = None, api: Any = None) -> int:
    env = dict(os.environ) if env is None else env
    stdin = sys.stdin if stdin is None else stdin
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdin", action="store_true", help="read the result from stdin instead of $RESULT")
    parser.add_argument("--post", action="store_true", help="create or update the comment (default: print it)")
    parser.add_argument("--no-file-check", action="store_true", help="do not list the pull request's files")
    parser.add_argument("--repo", help="owner/name (default $GITHUB_REPOSITORY)")
    parser.add_argument("--pr", help="pull request number (default $PR_NUMBER)")
    parser.add_argument("--head-sha", help="reviewed commit (default $HEAD_SHA)")
    parser.add_argument("--base-sha", help="base commit whose tree is checked (default $BASE_SHA)")
    parser.add_argument("--status", help="ready or too-large (default $INPUT_STATUS)")
    parser.add_argument("--review-result", help="result of the review job (default $REVIEW_RESULT)")
    parser.add_argument("--source", help="model and tool shown in the header (default $AI_REVIEW_SOURCE)")
    parser.add_argument("--comment-author", help="login whose earlier comment is updated")
    args = parser.parse_args(argv)
    try:
        ctx = build_context(args, env)
        if api is None and (args.post or not args.no_file_check):
            api = GhApi()
        body, code = comment_for(args, env, ctx, stdin, api)
        if not args.post:
            sys.stdout.write(body)
            return code
        print(f"comment {upsert_comment(api, ctx, body, comment_author(args, env, api))} on {ctx.repo}#{ctx.pr}")
        return code
    except ApiError as error:
        print(f"::error title=AI review::GitHub API: {error}")
        return 2
    except SystemExit as error:
        print(f"::error title=AI review::{error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
