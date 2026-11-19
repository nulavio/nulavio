#!/usr/bin/env python3
"""Is any pinned dependency known to be vulnerable, blocked or stale? (daily; the engine has watch_upstream.py)

* Against OSV.dev: the GitHub Actions (commit SHA plus "# vX.Y.Z"), ruff (requirements/dev.txt),
  the Gradle wrapper, and every artifact in android/gradle/verification-metadata.xml (direct,
  transitive and build-time; the ones in android/app/gradle.lockfile ship in the APK). GitHub raises
  no Dependabot alerts for SHA-pinned actions or Gradle, so this is their vulnerability signal.
* The pinned extensions against addons.mozilla.org: Mozilla's blocklist, a replaced file for the
  pinned version, and how long the lock has lagged behind AMO's current version.
* The pinned extensions against the security advisories their repositories publish on GitHub (the table in
  docs/security/extension-advisory-sources.json): an advisory whose range covers the pinned version fails at once.
* The base images' tag@digest pins against their registries (a newer build is reported, not failed).

A finding someone has looked at and accepted goes in docs/security/vulnerability-exceptions.json,
for one package version, with a reason and an expiry (docs/security/dependency-updates.md).

    python3 -I scripts/release/watch_dependencies.py [--summary FILE] [--json]
    python3 -I scripts/release/watch_dependencies.py --list     # the inventory only, no network

Exit status: 0 nothing to act on, 1 action needed (a known vulnerability without a valid exception,
a blocked or replaced extension, a published advisory that covers a pinned extension, a lock more
than 30 days behind AMO), 2 some data was unavailable and
nothing else needs action. The four checks run independently: one source being down does not hide
what the others found.
Sends only public package names and versions to api.osv.dev, addons.mozilla.org, api.github.com (a GET of a
repository's advisories, with the workflow's read-only token) and the registries.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OSV = "https://api.osv.dev/v1/"
AMO = "https://addons.mozilla.org/api/v5/"
GITHUB = "https://api.github.com/"
ADVISORY_SOURCES = ROOT / "docs" / "security" / "extension-advisory-sources.json"
MIN_REQUEST_SECONDS = 10
RETRY_DELAYS = (2, 8, 30)  # a transient GitHub failure is retried before it is reported (as watch_upstream.py does)
GITHUB_BUDGET = 120  # seconds of retrying across all repositories, so the step ends and writes its summary in time
WATCH_BUDGET = 360  # seconds for the whole watch (every request of every check); the step's timeout-minutes is 8 (480 s)
EXCEPTIONS = ROOT / "docs" / "security" / "vulnerability-exceptions.json"
APK_LOCKFILE = "android/app/gradle.lockfile"  # the APK's classpath (releaseRuntimeClasspath), nv1 included
EXTENSION_LAG_DAYS = 30
EXTENSION_ECOSYSTEM = "Browser extension"  # in vulnerability-exceptions.json: package = the lock's key, version = the pin
UNAVAILABLE = (OSError, ValueError, KeyError, TypeError)  # network errors, unexpected or malformed replies
BATCH = 500  # OSV.dev accepts up to 1000 queries per batch
INDEX_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json",
])  # fmt: skip


@dataclasses.dataclass(frozen=True)
class Dep:
    ecosystem: str  # OSV ecosystem name
    name: str
    version: str
    sources: tuple[str, ...]
    ships: bool = False  # in the APK; everything else runs at build or CI time

    def label(self) -> str:
        where = "ships in the APK" if self.ships else ", ".join(self.sources)
        return f"{self.ecosystem} {self.name} {self.version} ({where})"


@dataclasses.dataclass
class Row:
    check: str  # osv, extension, image, exception
    state: str  # ok, warn, accepted, fail, error (data unavailable)
    text: str
    detail: dict = dataclasses.field(default_factory=dict)


class Net:
    """The only code here that touches the network (the unit tests replace it)."""

    def __init__(
        self,
        timeout: int = 30,
        token: str | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
        wall=time.time,
        budget: float = WATCH_BUDGET,
    ):
        self.timeout = timeout
        self.token = token  # the workflow's read-only GITHUB_TOKEN: only for api.github.com, it raises the rate limit
        self.sleep = sleep
        self.clock = clock
        self.wall = wall  # the epoch clock, for the rate limit's reset time
        self.github_started: float | None = None
        self.deadline = clock() + budget  # no request starts after it, and none may outlast it: the summary always prints

    def _open(
        self,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
        method: str | None = None,
        timeout: float | None = None,
    ):
        if not url.startswith("https://"):
            raise ValueError(f"refusing a non-https URL: {url}")
        left = self.deadline - self.clock()
        if left <= 0:
            raise TimeoutError("the watch's time budget is spent")  # an OSError: the check reports it as unavailable data
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=body, method=method)  # noqa: S310 - https only, checked above
        request.add_header("User-Agent", "nulavio-dependency-watch")
        for key, value in (headers or {}).items():
            if key.lower() == "authorization":
                request.add_unredirected_header(key, value)  # never follows a redirect to another host
            else:
                request.add_header(key, value)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        return urllib.request.urlopen(request, timeout=min(timeout or self.timeout, left))  # noqa: S310 - https only, checked above

    def json(self, url: str, data: dict | None = None, missing_ok: bool = False) -> dict | None:
        try:
            with self._open(url, data) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise

    def github_json(self, url: str):
        """A GET against api.github.com, retried on a server error, rate limit or network failure."""
        if not url.startswith(GITHUB):
            raise ValueError(f"refusing a non-GitHub URL: {url}")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.github_started is None:
            self.github_started = self.clock()
        deadline = min(self.github_started + GITHUB_BUDGET, self.deadline)
        for attempt in range(len(RETRY_DELAYS) + 1):
            # the budget covers the requests too: a request may not outlast it (but gets a few seconds at least)
            timeout = max(MIN_REQUEST_SECONDS, min(self.timeout, deadline - self.clock()))
            try:
                with self._open(url, headers=headers, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                delay = self.backoff(exc, RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
                failure = exc
                if delay is None:
                    raise
            except OSError as exc:  # a reset, a timeout, DNS (HTTPError is handled above)
                failure = exc
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            if attempt == len(RETRY_DELAYS) or self.clock() + delay >= deadline:  # checked after the failure
                raise failure
            self.sleep(delay)

    def backoff(self, exc: urllib.error.HTTPError, default: float) -> float | None:
        """Seconds to wait before retrying this HTTP error, or None when it is not worth retrying.

        Server errors and 429 are; a 403 only when it is GitHub's rate limit (Retry-After, or no calls left until the
        reset time), whose own backoff is honoured when it fits the budget; any other 403 (authorization) is not.
        """
        headers = exc.headers or {}
        limited = exc.code == 429 or (
            exc.code == 403 and (headers.get("retry-after") or headers.get("x-ratelimit-remaining") == "0")
        )
        if exc.code not in (500, 502, 503, 504) and not limited:
            return None
        try:
            if headers.get("retry-after"):
                return max(float(headers["retry-after"]), 1)
            if headers.get("x-ratelimit-remaining") == "0":
                return max(float(headers["x-ratelimit-reset"]) - self.wall(), 1)
        except (KeyError, ValueError):
            pass
        return default

    def head(self, url: str, headers: dict) -> tuple[int, dict[str, str]]:
        try:
            with self._open(url, headers=headers, method="HEAD") as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}


# Inventory ---------------------------------------------------------------------------------------


def locked_modules(lockfile: Path) -> set[tuple[str, str]]:
    """(group:name, version) of every module a Gradle lockfile lists."""
    found = set()
    for line in lockfile.read_text(encoding="utf-8").splitlines():
        module, _, configurations = line.partition("=")
        if configurations and module.count(":") == 2:
            group, name, version = module.split(":")
            found.add((f"{group}:{name}", version))
    return found


def inventory(root: Path = ROOT) -> list[Dep]:
    seen: dict[tuple[str, str, str], set[str]] = {}

    def add(ecosystem: str, name: str, version: str, source: str) -> None:
        seen.setdefault((ecosystem, name, version), set()).add(source)

    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        for match in re.finditer(
            r"uses:\s*([\w.-]+/[\w.-]+(?:/[\w./-]+)?)@[0-9a-f]{40}\s+#\s*v?(\d[\w.-]*)", workflow.read_text()
        ):
            add("GitHub Actions", match.group(1), match.group(2), f".github/workflows/{workflow.name}")
    for requirements in sorted((root / "requirements").glob("*.txt")):  # dev.txt, and fuzz.txt (#149)
        for match in re.finditer(r"^([A-Za-z0-9_.\-]+)==(\S+)", requirements.read_text(), re.M):
            add("PyPI", match.group(1).lower(), match.group(2), f"requirements/{requirements.name}")
    wrapper = (root / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text()
    if match := re.search(r"distributions/gradle-([0-9.]+)-bin\.zip", wrapper):
        add("Bitnami", "gradle", match.group(1), "android/gradle/wrapper")  # OSV lists Gradle's own advisories there
    metadata = ET.parse(root / "android" / "gradle" / "verification-metadata.xml").getroot()  # noqa: S314 - our committed file
    ns = metadata.tag.split("}")[0] + "}"
    for component in metadata.iter(f"{ns}component"):
        name = f"{component.get('group')}:{component.get('name')}"
        add("Maven", name, component.get("version"), "Android build")
    shipped = locked_modules(root / APK_LOCKFILE)
    return [
        Dep(eco, name, version, tuple(sorted(sources)), ships=eco == "Maven" and (name, version) in shipped)
        for (eco, name, version), sources in sorted(seen.items())
    ]


# OSV ---------------------------------------------------------------------------------------------


def version_key(version: str) -> tuple:
    """Order release versions; a pre-release (1.2.0-rc1) sorts before its release (1.2.0)."""
    match = re.match(r"v?(\d+(?:\.\d+)*)(.*)", version.strip())
    if not match:
        return ((), 0)
    numbers = [int(p) for p in match.group(1).split(".")]
    while numbers and numbers[-1] == 0:
        numbers.pop()  # 2.3 == 2.3.0
    suffix = match.group(2)
    return (tuple(numbers), 0 if suffix and not suffix.startswith("+") else 1)  # "+build" is not a pre-release


def _ended(event: dict, key: tuple) -> bool:
    if "fixed" in event:
        return key >= version_key(event["fixed"])
    return "last_affected" in event and key > version_key(event["last_affected"])


def affected(vuln: dict, names: set[str], version: str) -> bool:
    """Evaluate OSV ranges locally (OSV.dev matches no versions for the GitHub Actions ecosystem)."""
    key = version_key(version)
    wanted = {n.lower() for n in names}
    for item in vuln.get("affected", []):
        if item.get("package", {}).get("name", "").lower() not in wanted:
            continue
        if any(version_key(v) == key for v in item.get("versions", [])):
            return True
        for span in item.get("ranges", []):
            if span.get("type") == "GIT":
                continue  # commit ranges: a tag's version cannot be placed in them
            inside = False
            for event in span.get("events", []):
                if "introduced" in event:
                    inside = inside or event["introduced"] == "0" or key >= version_key(event["introduced"])
                elif inside and _ended(event, key):
                    inside = False
            if inside:
                return True
    return False


def action_names(name: str) -> set[str]:
    """An action may be advised as owner/repo or by its full path (owner/repo/sub-action)."""
    return {name, "/".join(name.split("/")[:2])}


def osv_findings(deps: list[Dep], net: Net) -> list[tuple[Dep, str]]:
    found: list[tuple[Dep, str]] = []
    matched = [d for d in deps if d.ecosystem != "GitHub Actions"]
    for start in range(0, len(matched), BATCH):
        chunk = matched[start : start + BATCH]
        queries = [{"package": {"ecosystem": d.ecosystem, "name": d.name}, "version": d.version} for d in chunk]
        results = net.json(OSV + "querybatch", {"queries": queries})["results"]
        for dep, query, result in zip(chunk, queries, results, strict=True):
            vulns = list(result.get("vulns", []))
            token = result.get("next_page_token")
            while token:
                page = net.json(OSV + "query", {**query, "page_token": token})
                vulns += page.get("vulns", [])
                token = page.get("next_page_token")
            found += [(dep, v["id"]) for v in vulns]
    for dep in (d for d in deps if d.ecosystem == "GitHub Actions"):
        names, ids = action_names(dep.name), set()
        for name in sorted(names):
            for vuln in net.json(OSV + "query", {"package": {"ecosystem": dep.ecosystem, "name": name}}).get("vulns", []):
                if vuln["id"] not in ids and affected(vuln, names, dep.version):
                    ids.add(vuln["id"])
                    found.append((dep, vuln["id"]))
    return found


def severity(info: dict) -> str:
    return str(info.get("database_specific", {}).get("severity") or "unrated").upper()


# Exceptions --------------------------------------------------------------------------------------


EXCEPTION_KEYS = {"id", "ecosystem", "package", "version", "reason", "until"}


def load_exceptions(path: Path = EXCEPTIONS) -> list[dict]:
    """The accepted findings; a malformed entry stops the run here rather than being skipped."""
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))["exceptions"]
    for item in items:
        if set(item) != EXCEPTION_KEYS or not str(item["reason"]).strip():
            raise ValueError(f"{path.name}: each exception needs exactly {sorted(EXCEPTION_KEYS)}: {item}")
        _dt.date.fromisoformat(item["until"])  # ValueError when it is not a date
    return items


def matching_exception(ids: set[str], dep: Dep, exceptions: list[dict]) -> dict | None:
    """An exception covers one advisory for one exact package version, so a bump is looked at again."""
    for item in exceptions:
        if item["id"] in ids and (item["ecosystem"], item["package"], item["version"]) == (dep.ecosystem, dep.name, dep.version):
            return item
    return None


def vulnerability_rows(findings: list[tuple[Dep, str]], details: dict[str, dict], exceptions: list[dict], today: _dt.date):
    rows, used = [], set()
    for dep, vid in findings:
        info = details[vid]
        if info.get("withdrawn"):
            continue
        ids = {vid, *info.get("aliases", [])}
        text = f"{dep.label()}: {vid} [{severity(info)}] {info.get('summary', '').strip()}".rstrip()
        detail = {"id": vid, "aliases": sorted(ids - {vid}), "severity": severity(info), **dataclasses.asdict(dep)}
        item = matching_exception(ids, dep, exceptions)
        if item is None:
            rows.append(Row("osv", "fail", text, detail))
            continue
        used.add(id(item))
        until = _dt.date.fromisoformat(item["until"])
        if until < today:
            rows.append(Row("osv", "fail", f"{text} (exception expired {until}: look at it again)", detail))
        else:
            detail["exception"] = item
            rows.append(Row("osv", "accepted", f"{text} (accepted until {until})", detail))
    for item in exceptions:
        if id(item) not in used and item["ecosystem"] != EXTENSION_ECOSYSTEM:  # advisory_rows reports those
            what = f"{item['id']} for {item['ecosystem']} {item['package']} {item['version']}"
            rows.append(Row("exception", "warn", f"exception {what} matches nothing now: remove it"))
    return rows


# Extensions --------------------------------------------------------------------------------------


def parse_time(text: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def extension_verdict(entry: dict, current: dict, block: dict | None, now: _dt.datetime) -> tuple[str, str]:
    pinned = entry["version"]
    if block and (block.get("is_all_versions") or pinned in block.get("blocked", []) + block.get("soft_blocked", [])):
        return "fail", f"{entry['key']} {pinned} is on Mozilla's blocklist: refresh the lock now"
    if current["version"] == pinned:
        if current["sha256"] != entry["sha256"]:
            return "fail", f"{entry['key']} {pinned}: AMO now serves a different file than the pinned SHA-256"
        return "ok", f"{entry['key']} {pinned} is AMO's current version"
    days = (now - parse_time(current["created"])).days
    text = f"{entry['key']} pinned {pinned}, AMO has had {current['version']} for {days} days"
    if days > EXTENSION_LAG_DAYS:
        return "fail", f"{text}: run scripts/upstream/refresh_extensions_lock.py and review"
    return "warn", text


def extension_rows(net: Net, now: _dt.datetime, root: Path = ROOT) -> list[Row]:
    lock = json.loads((root / "browser" / "distribution" / "extensions.lock.json").read_text(encoding="utf-8"))
    rows = []
    for entry in lock["extensions"]:
        guid = urllib.parse.quote(entry["id"], safe="")
        try:
            data = net.json(f"{AMO}addons/addon/{guid}/")["current_version"]
            algorithm, _, digest = data["file"]["hash"].partition(":")
            if algorithm != "sha256":
                raise ValueError(f"AMO returned a {algorithm} hash")
            current = {"version": data["version"], "sha256": digest, "created": data["file"]["created"]}
            block = net.json(f"{AMO}blocklist/block/{guid}/", missing_ok=True)  # 404: not blocked
            state, text = extension_verdict(entry, current, block, now)
        except UNAVAILABLE as exc:  # the other extensions are still checked
            rows.append(
                Row("extension", "error", f"{entry['key']}: no data from addons.mozilla.org: {exc}", {"key": entry["key"]})
            )
            continue
        rows.append(Row("extension", state, text, {"key": entry["key"], "pinned": entry["version"], "amo": current["version"]}))
    return rows


# Extension advisories ----------------------------------------------------------------------------

STRICT_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
RANGE_CLAUSE = re.compile(r"(<=|>=|<|>|==|=)\s*(v?\d+(?:\.\d+)*)")
RANGE_OR_LOWER = re.compile(r"(v?\d+(?:\.\d+)*)\s+(?:and|or)\s+(?:lower|below|earlier|older)")


def strict_version(text: str) -> tuple[int, ...]:
    """Dotted numbers only (1.75.2, 1.10.4.1, 2026.10.2); anything else raises, so the caller fails closed."""
    match = STRICT_VERSION.fullmatch(text.strip())
    if not match:
        raise ValueError(f"not a dotted version: {text!r}")
    numbers = [int(p) for p in match.group(1).split(".")]
    while numbers and numbers[-1] == 0:
        numbers.pop()  # 1.10 == 1.10.0
    return tuple(numbers)


def range_covers(text: str | None, version: str) -> bool:
    """Does an advisory's `vulnerable_version_range` cover the version? ValueError when it cannot be read.

    GitHub stores the range as free text: "<= 1.9.6", ">= 1.2, < 1.4", "1.75.2 and lower". Clauses joined by
    commas must all hold. Any other form is refused instead of guessed at.
    """
    if not text or not text.strip():
        raise ValueError("empty vulnerable_version_range")
    key = strict_version(version)
    clauses = []
    for clause in text.split(","):  # every clause is read before any is judged, so a bad one is never skipped
        clause = clause.strip()
        if match := RANGE_CLAUSE.fullmatch(clause):
            clauses.append((match.group(1), strict_version(match.group(2))))
        elif match := RANGE_OR_LOWER.fullmatch(clause):
            clauses.append(("<=", strict_version(match.group(1))))
        else:
            raise ValueError(f"cannot read the range {text!r} (at {clause!r})")
    for op, bound in clauses:
        holds = {
            "<": key < bound,
            "<=": key <= bound,
            ">": key > bound,
            ">=": key >= bound,
            "==": key == bound,
            "=": key == bound,
        }
        if not holds[op]:
            return False
    return True


def load_advisory_sources(path: Path = ADVISORY_SOURCES) -> dict[str, dict]:
    """key -> {"repo", "packages", "other_packages"} or {"reason"}; a malformed table stops the run here."""
    items = json.loads(path.read_text(encoding="utf-8"))["sources"]
    table: dict[str, dict] = {}
    for item in items:
        if item.get("key") in table or not item.get("key"):
            raise ValueError(f"{path.name}: duplicate or missing key: {item}")
        if item.get("repo"):
            ok = re.fullmatch(r"[\w.-]+/[\w.-]+", item["repo"]) and isinstance(item.get("monorepo"), bool)
            allowed = {"key", "repo", "monorepo", *(["packages", "other_packages"] if item.get("monorepo") else [])}
            if not ok or not {"key", "repo", "monorepo"} <= set(item) <= allowed or item.get("monorepo") != ("packages" in item):
                raise ValueError(
                    f"{path.name}: a source needs key, repo, monorepo (true or false) and, for a monorepo, packages "
                    f"(and optionally other_packages): {item}"
                )
            if item["monorepo"]:
                names = {k: item.get(k, []) for k in ("packages", "other_packages")}
                if not names["packages"]:
                    raise ValueError(f"{path.name}: a monorepo needs the package names of its extension: {item}")
                if any(not isinstance(v, list) or not all(isinstance(n, str) and n.strip() for n in v) for v in names.values()):
                    raise ValueError(f"{path.name}: packages and other_packages are lists of names: {item}")
                if {n.lower() for n in names["packages"]} & {n.lower() for n in names["other_packages"]}:
                    raise ValueError(f"{path.name}: a package cannot be both this extension's and another product's: {item}")
        elif set(item) != {"key", "repo", "reason"} or item["repo"] is not None or not str(item["reason"]).strip():
            raise ValueError(f"{path.name}: an extension without a source needs repo null and a reason: {item}")
        table[item["key"]] = item
    return table


def advisory_row(
    entry: dict,
    source: dict,
    advisories: list,
    exceptions: list[dict] = (),
    today: _dt.date | None = None,
    used: set | None = None,
) -> list[Row]:
    """Rows for one extension from its repository's advisories: fail when one covers the pinned version.

    A repository of one product accepts any package name (the names are free text); a monorepo is filtered by the
    names in the table (an advisory that names only packages of "other_packages", the monorepo's other products, is
    not this extension's and is skipped), and a name in neither list fails like a range that cannot be read. An
    exception for the advisory, this extension and this pinned version turns a failure into "accepted" until its date.
    """
    key, version = entry["key"], entry["version"]
    today = today or _dt.datetime.now(_dt.UTC).date()
    used = used if used is not None else set()
    packages = {p.lower() for p in source.get("packages", [])}
    others = {p.lower() for p in source.get("other_packages", [])}
    dep = Dep(EXTENSION_ECOSYSTEM, key, version, ())
    rows = []

    def finding(advisory: dict, text: str) -> None:
        ident, link = advisory["ghsa_id"], advisory["html_url"]
        detail = {"key": key, "pinned": version, "id": ident, "url": link}
        item = matching_exception({ident, *filter(None, [advisory.get("cve_id")])}, dep, exceptions)
        if item is None:
            rows.append(Row("advisory", "fail", text, detail))
            return
        used.add(id(item))
        until = _dt.date.fromisoformat(item["until"])
        if until < today:
            rows.append(Row("advisory", "fail", f"{text} (exception expired {until}: look at it again)", detail))
        else:
            rows.append(Row("advisory", "accepted", f"{text} (accepted until {until})", {**detail, "exception": item}))

    for advisory in advisories:
        if (
            not isinstance(advisory, dict)
            or not isinstance(advisory.get("state"), str)
            or not all(isinstance(advisory.get(k), str) and advisory[k] for k in ("ghsa_id", "html_url"))
        ):  # a malformed reply is an error row, never a silent skip
            raise ValueError("an advisory without a state, id or link")
        if advisory["state"] != "published" or advisory.get("withdrawn_at"):
            continue
        ident, link = advisory["ghsa_id"], advisory["html_url"]
        covered, problems = None, []
        vulns = advisory.get("vulnerabilities")
        if not isinstance(vulns, list) or not vulns:
            problems.append("it lists no affected package or range")
        for vuln in vulns if isinstance(vulns, list) else []:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("package") or {}, dict):
                raise ValueError(f"{ident}: a vulnerability or its package is not an object")
            name = str((vuln.get("package") or {}).get("name", ""))
            if source["monorepo"] and name.lower() in others:
                continue  # another product of the monorepo, recorded as such in the table: not this extension
            if source["monorepo"] and name.lower() not in packages:
                problems.append(f"it names package {name!r}, which is not this extension's in the table")
                continue
            try:
                if range_covers(vuln.get("vulnerable_version_range"), version):
                    covered = covered or vuln
            except ValueError as exc:
                problems.append(f"a range cannot be read ({exc})")
        if covered:
            fixed = covered.get("patched_versions") or "no fixed version listed"
            finding(
                advisory,
                f"{key} {version} is covered by {ident} [{advisory.get('severity') or 'unrated'}] "
                f"{str(advisory.get('summary', '')).strip()} (range {covered['vulnerable_version_range']!r}, "
                f"fixed in {fixed}): {link}",
            )
        elif problems:
            finding(advisory, f"{key} {version}: {ident} cannot be matched, {'; '.join(problems)}; look at it by hand: {link}")
    return rows


def advisory_rows(net: Net, root: Path = ROOT, exceptions: list[dict] | None = None, today: _dt.date | None = None) -> list[Row]:
    lock = json.loads((root / "browser" / "distribution" / "extensions.lock.json").read_text(encoding="utf-8"))
    table = load_advisory_sources(root / "docs" / "security" / "extension-advisory-sources.json")
    today = today or _dt.datetime.now(_dt.UTC).date()
    if exceptions is None:
        exceptions = load_exceptions(root / "docs" / "security" / "vulnerability-exceptions.json")
    used: set = set()
    keys = [e["key"] for e in lock["extensions"]]
    rows = [
        Row(
            "advisory",
            "fail",
            f"{k} is not in docs/security/extension-advisory-sources.json: add it, with a repository or a reason",
        )
        for k in keys
        if k not in table
    ]
    rows += [
        Row("advisory", "fail", f"docs/security/extension-advisory-sources.json lists {k}, which the lock no longer pins")
        for k in table
        if k not in keys
    ]
    unverified = {k for k in keys if k not in table}  # extensions whose advisories could not be read this run
    for entry in lock["extensions"]:
        source = table.get(entry["key"])
        if source is None:
            continue
        if not source["repo"]:
            rows.append(
                Row(
                    "advisory",
                    "ok",
                    f"{entry['key']}: no public advisory source ({source['reason']})",
                    {"key": entry["key"], "source": None},
                )
            )
            continue
        try:
            advisories = net.github_json(f"{GITHUB}repos/{source['repo']}/security-advisories?per_page=100")
            if not isinstance(advisories, list) or len(advisories) >= 100:
                raise ValueError("expected a list of fewer than 100 advisories")
            found = advisory_row(entry, source, advisories, exceptions, today, used)
        except UNAVAILABLE as exc:  # the other extensions are still checked
            unverified.add(entry["key"])
            rows.append(
                Row(
                    "advisory",
                    "error",
                    f"{entry['key']}: no advisory data from api.github.com ({source['repo']}): {exc}",
                    {"key": entry["key"]},
                )
            )
            continue
        rows += found or [
            Row(
                "advisory",
                "ok",
                f"{entry['key']} {entry['version']}: no published advisory of {source['repo']} covers it",
                {"key": entry["key"]},
            )
        ]
    for item in exceptions:
        # an extension whose advisories were not read cannot say its exception is unused: it may still be needed
        if item["ecosystem"] == EXTENSION_ECOSYSTEM and id(item) not in used and item["package"] not in unverified:
            what = f"{item['id']} for {item['package']} {item['version']}"
            rows.append(Row("exception", "warn", f"exception {what} matches nothing now: remove it"))
    return rows


# Base images -------------------------------------------------------------------------------------


def image_refs(root: Path = ROOT) -> list[tuple[str, str]]:
    refs = []
    for path in sorted((root / "ci" / "containers").glob("*.Containerfile")):
        refs += [(path.name, ref) for ref in re.findall(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.M)]
    return refs


def manifest_url(ref: str) -> str:
    """registry/repository:tag[@digest] -> the registry's v2 manifest URL for the tag."""
    host, _, rest = ref.partition("/")
    repository, _, tag = rest.split("@")[0].rpartition(":")
    if "." not in host or not repository or not tag:
        raise ValueError(f"{ref}: expected registry/repository:tag")
    api = "registry-1.docker.io" if host == "docker.io" else host
    return f"https://{api}/v2/{repository}/manifests/{tag}"


def registry_digest(ref: str, net: Net) -> str:
    """Current digest of repository:tag from the registry's v2 API (anonymous token if the registry asks)."""
    url, headers = manifest_url(ref), {"Accept": INDEX_TYPES}
    status, reply = net.head(url, headers)
    if status == 401:
        challenge = dict(re.findall(r'(\w+)="([^"]*)"', reply.get("www-authenticate", "")))
        realm = challenge.get("realm", "")
        if not realm.startswith("https://"):
            raise ValueError(f"{url}: unexpected authentication challenge")
        query = urllib.parse.urlencode({k: v for k, v in challenge.items() if k in ("service", "scope")})
        token = net.json(f"{realm}?{query}")
        headers["Authorization"] = "Bearer " + (token.get("token") or token["access_token"])
        status, reply = net.head(url, headers)
    if status != 200 or not reply.get("docker-content-digest", "").startswith("sha256:"):
        raise ValueError(f"{url}: HTTP {status}, no digest")
    return reply["docker-content-digest"]


def image_rows(net: Net, root: Path = ROOT) -> list[Row]:
    rows = []
    for name, ref in image_refs(root):
        if "@sha256:" not in ref:
            rows.append(Row("image", "fail", f"{name}: {ref} is not pinned by digest"))
            continue
        tag, _, pinned = ref.partition("@")
        try:
            latest = registry_digest(ref, net)
        except UNAVAILABLE as exc:  # one registry down: the other images are still checked
            rows.append(Row("image", "error", f"{name}: no data for {tag}: {exc}"))
            continue
        if pinned == latest:
            rows.append(Row("image", "ok", f"{name}: {tag} is current"))
        else:
            rows.append(
                Row("image", "warn", f"{name}: {tag} has a newer build {latest} (Dependabot's docker update or a manual refresh)")
            )
    return rows


# Report ------------------------------------------------------------------------------------------


def osv_rows(deps: list[Dep], net: Net, exceptions: list[dict], today: _dt.date) -> list[Row]:
    findings = osv_findings(deps, net)
    details = {vid: net.json(f"{OSV}vulns/{urllib.parse.quote(vid)}") for vid in sorted({vid for _, vid in findings})}
    return vulnerability_rows(findings, details, exceptions, today)


def run(net: Net, now: _dt.datetime, root: Path = ROOT, exceptions: list[dict] | None = None) -> tuple[list[Dep], list[Row]]:
    deps = inventory(root)
    exceptions = (
        load_exceptions(root / "docs" / "security" / "vulnerability-exceptions.json") if exceptions is None else exceptions
    )
    sections = (
        ("osv", "OSV.dev", lambda: osv_rows(deps, net, exceptions, now.date())),
        ("extension", "addons.mozilla.org", lambda: extension_rows(net, now, root)),
        ("advisory", "api.github.com", lambda: advisory_rows(net, root, exceptions, now.date())),
        ("image", "the registries", lambda: image_rows(net, root)),
    )
    rows: list[Row] = []
    for check, source, section in sections:
        try:
            rows += section()
        except UNAVAILABLE as exc:  # the other checks still run and report
            rows.append(Row(check, "error", f"no data from {source}: {type(exc).__name__}: {exc}"))
    return deps, rows


ORDER = {"fail": 0, "error": 1, "accepted": 2, "warn": 3, "ok": 4}


def exit_status(rows: list[Row]) -> int:
    if any(r.state == "fail" for r in rows):
        return 1
    return 2 if any(r.state == "error" for r in rows) else 0


def report(deps: list[Dep], rows: list[Row]) -> str:
    shipped = sum(d.ships for d in deps)
    extensions = sum(r.check == "extension" and r.state != "error" for r in rows)
    images = sum(r.check == "image" and r.state != "error" for r in rows)
    sourceless = sorted(r.detail["key"] for r in rows if r.check == "advisory" and r.detail.get("source", 1) is None)
    watched = len({r.detail["key"] for r in rows if r.check == "advisory" and r.state != "error" and "key" in r.detail}) - len(
        sourceless
    )
    osv_down = any(r.check == "osv" and r.state == "error" for r in rows)
    head = (
        f"{'Could not check' if osv_down else 'Checked'} {len(deps)} pinned packages against OSV.dev ({shipped} ship in the APK)"
    )
    advisories = f"{watched} extensions' repositories for security advisories" + (
        f" ({', '.join(sourceless)}: no public source)" if sourceless else ""
    )
    lines = [f"{head}; checked {extensions} extensions, {advisories} and {images} base images."]
    lines += [f"{r.state.upper():8} {r.text}" for r in sorted(rows, key=lambda r: ORDER[r.state]) if r.state != "ok"]
    return "\n".join(lines)


def markdown(deps: list[Dep], rows: list[Row]) -> str:
    items = [f"- **{r.state}** {r.text}" for r in sorted(rows, key=lambda r: ORDER[r.state]) if r.state != "ok"]
    head = report(deps, rows).splitlines()[0]
    return "### Pinned dependencies\n\n" + head + "\n\n" + "\n".join(items or ["- nothing to act on"]) + "\n"


def read_token(stream=None) -> str | None:
    """The GitHub token, from the first line of stdin: it travels there, not in argv or a child's environment (I3)."""
    line = (stream or sys.stdin).readline().strip()
    return line or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, help="append a Markdown summary (GitHub job summary)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        help="read a GitHub token from the first line of stdin (never argv or the environment)",
    )
    parser.add_argument("--list", action="store_true", help="print the inventory and exit (no network)")
    args = parser.parse_args()
    if args.list:
        for dep in inventory():
            print(dep.label())
        return 0
    try:
        deps, rows = run(Net(token=read_token() if args.token_stdin else None), _dt.datetime.now(_dt.UTC))
    except UNAVAILABLE as exc:  # the repository's own files (inventory, exceptions) could not be read
        print(f"watch_dependencies: cannot read the pins: {exc}", file=sys.stderr)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as handle:
                handle.write(f"### Pinned dependencies\n\nCannot read the pins: {exc}\n")
        return 2
    if args.json:
        results = [dataclasses.asdict(r) for r in rows]
        print(json.dumps({"checked": len(deps), "shipped": sum(d.ships for d in deps), "results": results}, indent=2))
    else:
        print(report(deps, rows))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(markdown(deps, rows))
    return exit_status(rows)


if __name__ == "__main__":
    raise SystemExit(main())
