#!/usr/bin/env python3
"""Is any pinned dependency known to be vulnerable, blocked or stale? (daily; the engine has watch_upstream.py)

* Against OSV.dev: the GitHub Actions (commit SHA plus "# vX.Y.Z"), ruff (requirements/dev.txt),
  the Gradle wrapper, and every artifact in android/gradle/verification-metadata.xml (direct,
  transitive and build-time; the ones in android/app/gradle.lockfile ship in the APK). GitHub raises
  no Dependabot alerts for SHA-pinned actions or Gradle, so this is their vulnerability signal.
* The pinned extensions against addons.mozilla.org: Mozilla's blocklist, a replaced or removed file for the
  pinned version (read on every run, also once a newer version is out), and how long the lock has lagged
  behind AMO: since the first version AMO published after the pin, however many came after it.
  One AMO reply missing or malformed hides no failure the others show; AMO's requests get AMO_BUDGET seconds in all,
  the summary and blocklist of every pin first, then the pinned files, then the versions lists.
* The pinned extensions against the security advisories their repositories publish on GitHub (the table in
  docs/security/extension-advisory-sources.json): an advisory whose range covers the pinned version fails at once.
* The base images' tag@digest pins against their registries (a newer build is reported, not failed).

A finding someone has looked at and accepted goes in docs/security/vulnerability-exceptions.json,
for one package version, with a reason and an expiry (docs/security/dependency-updates.md).

    python3 -I scripts/release/watch_dependencies.py [--summary FILE] [--json]
    python3 -I scripts/release/watch_dependencies.py --list     # the inventory only, no network

Exit status: 0 nothing to act on, 1 action needed (a known vulnerability without a valid exception,
a blocked, replaced or removed extension, a published advisory that covers a pinned extension, a pin that
AMO first superseded more than 30 days ago), 2 some data was unavailable and
nothing else needs action. The four checks run independently: one source being down does not hide
what the others found.
Sends only public package names and versions to api.osv.dev, addons.mozilla.org, api.github.com (a GET of a
repository's advisories, with the workflow's read-only token) and the registries.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import http.client
import io
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
AMO_ORIGIN = "https://addons.mozilla.org/"
AMO = AMO_ORIGIN + "api/v5/"
GITHUB = "https://api.github.com/"
ADVISORY_SOURCES = ROOT / "docs" / "security" / "extension-advisory-sources.json"
MIN_REQUEST_SECONDS = 10
RETRY_DELAYS = (2, 8, 30)  # a transient GitHub failure is retried before it is reported (as watch_upstream.py does)
GITHUB_BUDGET = 120  # seconds of retrying across all repositories, so the step ends and writes its summary in time
# seconds for every addons.mozilla.org request together: AMO timing out (30 s a request) cost main 150 s, one request
# for each of the five extensions; the watch now asks AMO up to 7 times each, so it is capped here instead, and
# OSV (60 s) plus AMO (120 s) leave 180 s of the 360 for GitHub (GITHUB_BUDGET) and the registries
AMO_BUDGET = 120
WATCH_BUDGET = 360  # seconds for the whole watch (every request of every check); the step's timeout-minutes is 8 (480 s)
EXCEPTIONS = ROOT / "docs" / "security" / "vulnerability-exceptions.json"
APK_LOCKFILE = "android/app/gradle.lockfile"  # the APK's classpath (releaseRuntimeClasspath), nv1 included
EXTENSION_LAG_DAYS = 30  # counted from the first version AMO published after the pin, not from its newest
VERSIONS_PAGE_SIZE = 50  # AMO's largest page
VERSIONS_PAGES = 4  # versions pages read to find the first one after the pin (newest first)
EXTENSION_ECOSYSTEM = "Browser extension"  # in vulnerability-exceptions.json: package = the lock's key, version = the pin
# network errors, unexpected or malformed replies; Net turns http.client's own errors (a reply cut short, a malformed
# status line), which are not OSErrors, into ConnectionError, and HTTPException is here for any it might not
UNAVAILABLE = (OSError, http.client.HTTPException, ValueError, KeyError, TypeError)
READ_CHUNK = 64 * 1024  # a body is read a socket read at a time (64 KiB at most), the request's end checked after each
MISSING = object()  # an AMO reply the watch could not have: the endpoint was down or the reply malformed
BATCH = 500  # OSV.dev accepts up to 1000 queries per batch
INDEX_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json",
])  # fmt: skip


class Redirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https, and one from addons.mozilla.org only to addons.mozilla.org.

    urllib's own handler follows a 30x to another host and to http://, and the watch would then judge that body as
    the source's (#829). A redirect it refuses is an HTTPError, unavailable data as any other. The redirect's own body
    is never read (urllib's handler reads all of it), and a redirect after the request's end (`Net._open` sets
    `request.time_left`) is not followed: the next request gets what is left, not the first one's timeout.
    """

    def http_error_302(self, req, fp, code, msg, headers):
        # judged before urllib's own scheme check, whose HTTPError names the whole address (a data: URL's, say)
        location = headers["location"] if "location" in headers else headers.get("uri")  # as urllib picks it
        if location is not None:
            self.refuse_off_origin(req, fp, code, headers, urllib.parse.urljoin(req.full_url, location))
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    @staticmethod
    def refuse_off_origin(req, fp, code, headers, newurl):
        allowed = AMO_ORIGIN if same_origin(req.full_url, AMO_ORIGIN) else "https://"
        if same_origin(newurl, allowed):
            return
        if fp is not None:
            fp.close()  # a refusal keeps no socket open
        try:  # no path, query, user or reason phrase: a signed URL's token stays out of the log
            target = urllib.parse.urlsplit(newurl)
            host, scheme = target.hostname or "", target.scheme
        except ValueError:
            host, scheme = "", ""
        if not re.fullmatch(r"[a-z][a-z0-9+.-]{0,15}", scheme):
            where = "an address that cannot be read"
        elif re.fullmatch(r"[a-z0-9.:-]{1,253}", host):
            where = f"{scheme}://{host}"
        else:
            where = f"a {scheme}: address"
        raise urllib.error.HTTPError(req.full_url, code, f"refusing a redirect to {where} (only {allowed})", headers, None)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.refuse_off_origin(req, fp, code, headers, newurl)  # again, on the address urllib quoted and joined
        if fp is not None:
            fp.close()  # urllib then reads nothing of a body the watch does not use
        time_left = getattr(req, "time_left", None)
        if time_left is not None:
            left = time_left()
            if left <= 0:
                raise TimeoutError("a redirect came after the request's time budget")
            timeout = getattr(req, "timeout", None)  # what urllib opens the redirect with
            req.timeout = left if timeout is None else min(timeout, left)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and time_left is not None:
            new.time_left = time_left  # and its own redirects
        return new


def same_origin(url: str, allowed: str) -> bool:
    """Is url on https at allowed's origin ("https://": any https host), by scheme, host and port, not by spelling?"""
    try:
        parts, want = urllib.parse.urlsplit(url), urllib.parse.urlsplit(allowed)
        if parts.scheme.lower() != "https" or not parts.hostname:
            return False
        if not want.hostname:
            return True
        port = 443 if parts.port is None else parts.port  # 0 is a port of its own, not the default
        return (parts.hostname, port) == (want.hostname, 443 if want.port is None else want.port)
    except ValueError:  # a port that is not a number, say
        return False


OPENER = urllib.request.build_opener(Redirects)


def urlopen(request: urllib.request.Request, timeout: float):
    """urllib.request.urlopen, with the redirects Redirects allows (the unit tests replace it)."""
    return OPENER.open(request, timeout=timeout)  # https only: Net._open checks the URL, Redirects every redirect


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
        self.amo_started: float | None = None
        self.deadline = clock() + budget  # no request starts after it, and none may outlast it: the summary always prints

    def _end(self, until: float | None) -> float:
        """When a request must be over: its own end (a budget's), never later than the watch's."""
        return self.deadline if until is None else min(until, self.deadline)

    def _open(
        self,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
        method: str | None = None,
        timeout: float | None = None,
        until: float | None = None,
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
        end = self._end(until)
        request.time_left = lambda: end - self.clock()  # Redirects follows no redirect after it
        try:
            response = urlopen(request, timeout=min(timeout or self.timeout, left))
        except http.client.HTTPException as exc:  # a malformed status line or header, say: not an OSError
            raise ConnectionError(f"a malformed reply: {type(exc).__name__}") from exc  # its text is the server's
        except urllib.error.HTTPError as exc:  # its status and headers are all the watch reads of it
            exc.close()  # the socket is not kept open while the exception is (AMO's rows keep theirs)
            if self.clock() > end:  # a late 404 is no more "not there" than a late 200 is a reply
                raise TimeoutError("the reply's headers came after the request's time budget") from None
            raise
        # the timeout bounds each socket wait, not the connection, its redirects and the headers together
        if self.clock() > end:
            response.close()
            raise TimeoutError("the reply's headers came after the request's time budget")
        self._bound_reads(response, end)
        return response

    def _bound_reads(self, response, end: float) -> None:
        """Every socket read after the headers (body, chunk size lines, trailers) checks the end before and after.

        http.client reads a chunked reply's size line and trailers inside one read1, as many socket reads as the
        server takes; a check at the socket read cuts a server dripping them off one socket wait after `end` at most.
        """
        raw = getattr(getattr(response, "fp", None), "raw", None)
        if not isinstance(raw, io.RawIOBase):
            return
        readinto = raw.readinto

        def bounded(buffer):
            if self.clock() > end:
                raise TimeoutError("the reply's body came after the request's time budget")
            count = readinto(buffer)
            if self.clock() > end:
                raise TimeoutError("the reply's body came after the request's time budget")
            return count

        raw.readinto = bounded  # an instance attribute: the BufferedReader over it looks readinto up on each read

    def _body(self, response, end: float) -> bytes:
        """The whole body, read in chunks: one that arrives after `end` (a server dripping bytes) is cut off.

        read1 waits on the socket once at most (read(n) waits until it has n bytes), and the end is checked after
        every read, the last one (the end of the body) too: a reply that is over only after `end` is not a reply.
        """
        chunks = []
        try:
            while True:
                chunk = response.read1(READ_CHUNK)
                if self.clock() > end:
                    raise TimeoutError("the reply's body came after the request's time budget")
                if not chunk:
                    break
                chunks.append(chunk)
            length = getattr(response, "length", None)  # read1 ends quietly when the server closes before the end
            if isinstance(length, int) and length > 0:
                raise http.client.IncompleteRead(b"".join(chunks), length)
        except http.client.HTTPException as exc:  # IncompleteRead (chunked replies raise it), not an OSError
            raise ConnectionError(f"the reply was cut short: {type(exc).__name__}") from exc
        return b"".join(chunks)

    def _fetch(self, url: str, data: dict | None = None, headers: dict | None = None, timeout=None, until=None):
        """The decoded JSON body; a reply whose body is null is malformed (only a 404 means "not there")."""
        with self._open(url, data, headers=headers, timeout=timeout, until=until) as response:
            body = self._body(response, self._end(until))
        value = json.loads(body)
        if value is None:
            raise ValueError(f"a reply whose body is null (from {urllib.parse.urlsplit(url).hostname})")  # no query
        return value

    def json(self, url: str, data: dict | None = None, missing_ok: bool = False) -> dict | None:
        """The reply's JSON; with missing_ok, None for an HTTP 404 and for nothing else."""
        timeout = until = None
        if url.startswith(AMO):
            if self.amo_started is None:
                self.amo_started = self.clock()
            until = self.amo_started + AMO_BUDGET
            timeout = min(self.timeout, until - self.clock())
            if timeout <= 0:
                raise TimeoutError("the time budget for addons.mozilla.org is spent")  # unavailable data, as a timeout
        try:
            return self._fetch(url, data, timeout=timeout, until=until)
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
                return self._fetch(url, headers=headers, timeout=timeout, until=max(deadline, self.clock() + timeout))
            except urllib.error.HTTPError as exc:
                delay = self.backoff(exc, RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
                failure = exc
                if delay is None:
                    raise
            except OSError as exc:  # a reset, a timeout, DNS, a reply cut short (HTTPError is handled above)
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
    if not isinstance(text, str):
        raise TypeError(f"not a date: {text!r}")  # in UNAVAILABLE, as a malformed reply
    parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"a date without a time zone: {text!r}")  # it could not be compared with AMO's other dates
    return parsed


def amo_file(version: dict) -> dict:
    """What the watch reads of an AMO version object: its number and its file's SHA-256, size and date."""
    file = version["file"]
    if not isinstance(version["version"], str) or not isinstance(file["hash"], str):
        raise TypeError("AMO returned a version or hash that is not text")
    algorithm, _, digest = file["hash"].partition(":")
    digest = digest.lower()  # the lock is compared in lower case too, as the launcher reads it
    if algorithm != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"AMO returned a {algorithm} hash for {version['version']}")
    if not isinstance(file["size"], int) or isinstance(file["size"], bool) or file["size"] <= 0:
        raise ValueError(f"AMO returned a size that is not a positive number for {version['version']}")
    parse_time(file["created"])  # a ValueError or TypeError when it is not a date
    version_key(version["version"])  # a ValueError when it cannot be ordered (a number past int()'s digit limit, say)
    return {"version": version["version"], "sha256": digest, "size": file["size"], "created": file["created"]}


def first_newer(net: Net, guid: str, pinned: dict, newer: list[dict], hidden: set[str]) -> tuple[dict | None, bool]:
    """The earliest listed, public version newer than the pin, and whether the list was read back to the pin.

    AMO lists versions newest first. The pages are read until the pinned version (or one made before it) shows up,
    for at most VERSIONS_PAGES pages; the URLs are built here, a reply's "next" only says whether there is more.
    newer and hidden collect, page by page, the versions after the pin that count and those AMO does not list as
    public: a page that fails later leaves them to the caller, as a lower bound of the lag.
    """
    since = parse_time(pinned["created"])
    floor = version_key(pinned["version"])
    for page in range(1, VERSIONS_PAGES + 1):
        data = net.json(f"{AMO}addons/addon/{guid}/versions/?page={page}&page_size={VERSIONS_PAGE_SIZE}")
        results = data["results"]
        if not isinstance(results, list):
            raise ValueError("AMO's versions list is not a list")
        reached, counted, skipped = False, [], set()  # a page counts only once all of it has been read
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("file"), dict) or not isinstance(item.get("version"), str):
                raise ValueError("AMO's versions list holds an element that is not a version")
            created = parse_time(item["file"]["created"])
            if item["version"] == pinned["version"] or created <= since:
                reached = True
                continue
            channel, status = item.get("channel"), item["file"].get("status")
            if not isinstance(channel, str) or not isinstance(status, str):
                raise ValueError(f"AMO's versions list does not say whether {item['version']} is listed and public")
            if channel != "listed" or status != "public":
                skipped.add(item["version"])
            elif version_key(item["version"]) > floor:
                counted.append({"version": item["version"], "created": item["file"]["created"]})
        more = data["next"]  # null on the last page; a missing or odd one is a malformed reply, not the end
        if more is not None and not isinstance(more, str):
            raise ValueError("AMO's versions list has a next link that is not text")
        newer += counted
        hidden |= skipped
        if reached or more is None:
            return earliest(newer), True
    return earliest(newer), False


def earliest(versions: list[dict]) -> dict | None:
    return min(versions, key=lambda v: parse_time(v["created"]), default=None)


def after_pin(current, served: dict, hidden: set[str]) -> bool:
    """Does AMO's current version count as one published after the pin: listed and public, higher, made later?"""
    return (
        isinstance(current, dict)
        and current["version"] not in hidden
        and version_key(current["version"]) > version_key(served["version"])
        and parse_time(current["created"]) > parse_time(served["created"])
    )


def extension_verdict(
    entry: dict,
    served: dict | None,
    current: dict,
    newer: dict | None,
    block: dict | None,
    now: _dt.datetime,
    complete: bool = True,
    hidden: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, str]:
    """The extension row's state and text.

    served: AMO's file for the pinned version (None: AMO no longer has it); current: AMO's current version;
    newer: the first version AMO published after the pin (None when there is none, or the pin is current);
    complete: whether the versions list was read back to the pin (otherwise the lag is a lower bound);
    hidden: the versions after the pin that AMO's versions list does not show as listed and public.
    """
    pinned = entry["version"]
    failure = pin_failure(entry, served, block, current)
    if failure:
        return "fail", failure
    if current["version"] == pinned:
        return "ok", f"{entry['key']} {pinned} is AMO's current version"
    # the earliest of the list's first newer version and AMO's current one, when that came after the pin: the same
    # selection as when a reply is missing, so a version the list does not show still counts
    since = earliest(([newer] if newer else []) + ([current] if after_pin(current, served, hidden) else []))
    if since is None:  # AMO's current version is a backport, say: following it would downgrade the pin
        why = "is not listed and public in AMO's versions list" if current["version"] in hidden else "is not newer than the pin"
        text = f"{entry['key']} pinned {pinned}, AMO's current version {current['version']} {why}"
        if not complete:
            return "error", f"{text}, and AMO's versions list was not read back to the pin"
        return "warn", text
    return lag(entry, since, current, now, complete)


def lag(entry: dict, since: dict, current, now: _dt.datetime, complete: bool) -> tuple[str, str]:
    """How long the pin has lagged since `since`, the first version AMO published after it (a lower bound if not complete).

    current may be MISSING (the add-on's summary did not come).
    """
    pinned = entry["version"]
    days = (now - parse_time(since["created"])).days
    text = f"{entry['key']} pinned {pinned}, AMO has had {since['version']} for {'at least ' if not complete else ''}{days} days"
    if isinstance(current, dict) and since["version"] != current["version"]:
        text += f" (current {current['version']})"
    if days > EXTENSION_LAG_DAYS:
        if isinstance(current, dict) and version_key(current["version"]) <= version_key(pinned):
            # refresh_extensions_lock.py takes AMO's current version: here that would downgrade the pin
            return "fail", f"{text}: update the lock to {since['version']} by hand and review"
        return "fail", f"{text}: run scripts/upstream/refresh_extensions_lock.py and review"
    if not complete:
        return "error", f"{text}: AMO's versions list was not read back to the pin"
    return "warn", text


def pin_failure(entry: dict, served, block, current) -> str | None:
    """What the blocklist, the pinned version's own file or, when it is the pin, AMO's current file shows on its own.

    Any of them may be MISSING, a reply the watch could not have.
    """
    pinned = entry["version"]
    if (
        block is not MISSING
        and block
        and (block.get("is_all_versions") or pinned in block.get("blocked", []) + block.get("soft_blocked", []))
    ):
        return f"{entry['key']} {pinned} is on Mozilla's blocklist: refresh the lock now"
    if served is None:
        return f"{entry['key']} {pinned}: AMO no longer serves the pinned version: refresh the lock now"
    if served is not MISSING and (served["sha256"] != entry["sha256"].lower() or served["size"] != int(entry["size"])):
        return f"{entry['key']} {pinned}: AMO now serves a different file than the pinned SHA-256 and size"
    if current is not MISSING and current["version"] == pinned and current["sha256"] != entry["sha256"].lower():
        return f"{entry['key']} {pinned}: AMO now serves a different file than the pinned SHA-256"
    return None


def read(problems: list[Exception], fetch, *args, **kwargs):
    """fetch(*args, **kwargs), or MISSING with the reason kept in problems: one reply missing hides nothing the others show."""
    try:
        return fetch(*args, **kwargs)
    except UNAVAILABLE as exc:
        problems.append(exc)
        return MISSING


def current_file(net: Net, guid: str) -> dict:
    return amo_file(net.json(f"{AMO}addons/addon/{guid}/")["current_version"])


def pinned_file(net: Net, guid: str, entry: dict) -> dict | None:
    """The pinned version's own file, on every run: a replaced file is seen also once a newer version is out."""
    version = urllib.parse.quote(entry["version"], safe="")
    found = net.json(f"{AMO}addons/addon/{guid}/versions/{version}/", missing_ok=True)  # 404: gone from AMO
    if found is None:
        return None
    served = amo_file(found)
    if served["version"] != entry["version"]:
        raise ValueError(f"AMO answered with version {served['version']} for {entry['version']}")
    return served


def blocklist_entry(net: Net, guid: str) -> dict | None:
    """Mozilla's blocklist entry for the extension (None: a 404, not blocked); a malformed one is unavailable data."""
    block = net.json(f"{AMO}blocklist/block/{guid}/", missing_ok=True)
    if block is None:
        return None
    if not isinstance(block, dict) or not isinstance(block["is_all_versions"], bool):
        raise ValueError("AMO's blocklist entry does not say whether it covers every version")
    lists = {key: block[key] for key in ("blocked", "soft_blocked")}
    if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in lists.values()):
        raise ValueError("AMO's blocklist entry does not list the blocked versions as text")
    return {"is_all_versions": block["is_all_versions"], **lists}


def extension_rows(net: Net, now: _dt.datetime, root: Path = ROOT) -> list[Row]:
    lock = json.loads((root / "browser" / "distribution" / "extensions.lock.json").read_text(encoding="utf-8"))
    # AMO's summary and the blocklist of every pin first, then every pinned file, then the versions lists: when AMO is
    # slow, AMO_BUDGET runs out on the lag of the last pins, not on the blocklist of a pin read after another's pages
    pins = []
    for entry in lock["extensions"]:
        guid = urllib.parse.quote(entry["id"], safe="")
        problems: list[Exception] = []  # each reply is read on its own: the other extensions are still checked too
        current = read(problems, current_file, net, guid)
        block = read(problems, blocklist_entry, net, guid)
        pins.append((entry, guid, problems, current, block))
    served_files = [read(problems, pinned_file, net, guid, entry) for entry, guid, problems, _, _ in pins]
    rows = []
    for (entry, guid, problems, current, block), served in zip(pins, served_files, strict=True):
        found, newer, complete = MISSING, None, True
        seen: list[dict] = []  # the versions after the pin the list showed, also when a later page failed
        hidden: set[str] = set()
        if isinstance(served, dict) and not (isinstance(current, dict) and current["version"] == entry["version"]):
            found = read(problems, first_newer, net, guid, served, seen, hidden)  # also without AMO's summary
            if found is not MISSING:
                newer, complete = found
        try:
            if not problems:
                state, text = extension_verdict(entry, served, current, newer, block, now, complete, hidden)
            elif failure := pin_failure(entry, served, block, current):  # confirmed whatever the missing reply says
                state, text = "fail", failure
            elif isinstance(served, dict) and (
                since := earliest(seen + ([current] if after_pin(current, served, hidden) else []))
            ):
                # a lag needs the pin's own reply; what did come bounds it, and over the limit it is confirmed
                state, text = lag(entry, since, current, now, found is not MISSING and complete)
            else:
                state = "error"
        except UNAVAILABLE as exc:  # a malformed date, say
            problems.append(exc)
            state = "error"
        if state != "fail" and problems:
            text = f"{entry['key']}: no data from addons.mozilla.org: {problems[0]}"
            rows.append(Row("extension", "error", text, {"key": entry["key"]}))
            continue
        amo = current["version"] if isinstance(current, dict) else None
        detail = {"key": entry["key"], "pinned": entry["version"], "amo": amo}
        if newer:
            detail["newer"] = newer["version"]
        rows.append(Row("extension", state, text, detail))
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
        covered, problems, skipped = None, [], []
        vulns = advisory.get("vulnerabilities")
        if not isinstance(vulns, list) or not vulns:
            problems.append("it lists no affected package or range")
        for vuln in vulns if isinstance(vulns, list) else []:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("package") or {}, dict):
                raise ValueError(f"{ident}: a vulnerability or its package is not an object")
            name = str((vuln.get("package") or {}).get("name", ""))
            if source["monorepo"] and name.lower() in others:
                skipped.append(name)  # another product of the monorepo, recorded as such in the table
                continue
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
        elif skipped:  # a trace in the summary: the advisory was not matched, and why
            names = ", ".join(map(repr, skipped))
            text = f"{key}: {ident} skipped, it names only {names}, listed in other_packages (not this extension): {link}"
            rows.append(Row("advisory", "ok", text, {"key": key, "id": ident, "url": link, "skipped": True}))
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
        rows += found
        if all(r.detail.get("skipped") for r in found):
            rows += [
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


def shown(row: Row) -> bool:
    """The summary lists what needs a look, and an advisory skipped as another product's (a trace, not a finding)."""
    return row.state != "ok" or bool(row.detail.get("skipped"))


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
    lines += [f"{r.state.upper():8} {r.text}" for r in sorted(rows, key=lambda r: ORDER[r.state]) if shown(r)]
    return "\n".join(lines)


def markdown(deps: list[Dep], rows: list[Row]) -> str:
    items = [f"- **{r.state}** {r.text}" for r in sorted(rows, key=lambda r: ORDER[r.state]) if shown(r)]
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
