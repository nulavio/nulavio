#!/usr/bin/env python3
"""Is the Nulavio build behind Mozilla's Firefox releases, how urgent is it, and how long is left?

Engine security fast path (docs/architecture/update-policy.md). Compares
browser/build/engine.json with Mozilla's public data:

- product-details.mozilla.org: which Firefox releases have shipped, and on which day;
- archive.mozilla.org: whether the next likely versions are already staged (Mozilla
  uploads the signed checksums hours before it publishes a release);
- Mozilla's security advisories (MFSA, read by scripts/release/mfsa.py): how urgent;
- the product-details git history: the time of publication (the history has only the day).

Every newer release has the policy deadline of 72 hours from Mozilla's
publication; only that deadline makes the verdict "overdue". Urgent releases
(critical or high impact, a sandbox escape, exploitation in the wild reported
or unclear, public exploit code, or an advisory that is missing or unreadable)
also have a 24-hour target. Both are in the report.

    python3 -I scripts/release/watch_upstream.py [--json] [--summary FILE] [--verify]
        [--state FILE] [--offline DIR] [--now ISO8601] [--engine FILE]

--verify checks Mozilla's signature on SHA256SUMS (scripts/upstream/verify_firefox_release.py,
pinned release key) for each target and for the pinned version, whose digest must
equal engine.json's "source_sha256". A staged release counts as staged only once
its signature verifies. --offline reads recorded responses instead of the network
(tests). --state keeps downloaded advisories and successful signature checks for
6 hours (a release is checked again when Mozilla publishes it).

Exit status: 0 up to date, staged, or within the deadline; 1 overdue (72 h
passed); 2 release data unavailable (no verdict, never "up to date");
3 a signature did not verify (nothing may be built from that release).
Only public data is fetched and nothing is sent. GITHUB_TOKEN, when set, goes to
api.github.com only (higher rate limit in GitHub Actions).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))
import mfsa  # noqa: E402

ENGINE = ROOT / "browser" / "build" / "engine.json"
PRODUCT = "https://product-details.mozilla.org/1.0/"
VERSIONS = "firefox_versions.json"
SOURCES = ("firefox_history_major_releases.json", "firefox_history_stability_releases.json")
ARCHIVE = "https://archive.mozilla.org/pub/firefox/releases/{version}/SHA256SUMS.asc"
MFSA_INDEX = "https://api.github.com/repos/mozilla/foundation-security-advisories/contents/announce/{year}"
MFSA_RAW = "https://raw.githubusercontent.com/mozilla/foundation-security-advisories/main/announce/{year}/{name}"
COMMITS = "https://api.github.com/repos/mozilla-releng/product-details/commits"
HOSTS = frozenset({"product-details.mozilla.org", "archive.mozilla.org", "api.github.com", "raw.githubusercontent.com"})
ADVISORIES = "https://www.mozilla.org/security/advisories/"
SLA_HOURS = 72  # the policy deadline, for every release
URGENT_TARGET_HOURS = 24  # the target for urgent releases (the policy's former "stretch")
RELEASE_RE = re.compile(r"^\d+\.0(\.\d+)?$")  # Release channel only: ESR dot lines share majors (153.1.0)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_VERIFY = 4  # newest targets whose signature is checked per run
MAX_CLOCKS = 6  # shipped targets whose publication time is looked up per run
MAX_ADVISORY_FILES = 80
CACHE_TTL = _dt.timedelta(hours=6)
RETRY_DELAYS = (2, 8, 30)


class DataUnavailable(Exception):
    """Mozilla's release history could not be read: no verdict."""


class VerificationFailed(Exception):
    """Mozilla's signature on SHA256SUMS did not verify against the pinned key."""


class ListingMissing(OSError):
    """Mozilla's advisory directory for a year does not exist (HTTP 404)."""


def advisory_listing(data) -> list[str]:
    """File names in a GitHub contents listing; anything but a list is an error, never "no advisory"."""
    if not isinstance(data, list):
        raise ValueError(f"the advisory listing is a JSON {type(data).__name__}, not a list")
    return [item["name"] for item in data if isinstance(item, dict) and isinstance(item.get("name"), str)]


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.replace("esr", "").split("."))


def release_history(history: dict) -> dict[str, str]:
    """Desktop Release-channel versions (158.0, 158.0.1) with a valid day; drops ESR (153.1.0) and junk."""
    return {
        version: day
        for version, day in history.items()
        if isinstance(version, str) and isinstance(day, str) and RELEASE_RE.match(version) and DATE_RE.match(day)
    }


def status(pinned: str, history: dict[str, str], now: _dt.datetime) -> dict:
    """Newer releases than `pinned`, the earliest one's deadline (from its day), and the verdict."""
    history = release_history(history)
    newer = sorted((v for v in history if version_key(v) > version_key(pinned)), key=lambda v: (history[v], version_key(v)))
    if not newer:
        return {"pinned": pinned, "state": "up-to-date", "newer": []}
    first = newer[0]
    released = _dt.datetime.fromisoformat(history[first]).replace(tzinfo=_dt.UTC)
    deadline = released + _dt.timedelta(hours=SLA_HOURS)
    left = (deadline - now).total_seconds() / 3600
    return {
        "pinned": pinned,
        "state": "overdue" if left < 0 else "pending",
        "newer": newer,
        "first": first,
        "released": history[first],
        "deadline": deadline.isoformat(),
        "hours_left": round(left, 1),
        "advisories": ADVISORIES,
    }


def describe(result: dict) -> str:
    if result.get("schema") == 2:
        return describe_report(result)
    if result["state"] == "up-to-date":
        return f"Nulavio ships Firefox {result['pinned']}, the latest release."
    head = f"Firefox {result['first']} was released on {result['released']}; Nulavio ships {result['pinned']}."
    if result["state"] == "overdue":
        return f"{head} OVERDUE: the {SLA_HOURS}-hour target passed at {result['deadline']}."
    return f"{head} Deadline {result['deadline']} ({result['hours_left']} hours left). Newer: {', '.join(result['newer'])}."


def next_candidates(pinned: str, latest: str | None) -> list[str]:
    """Versions Mozilla may stage next. Android takes dot numbers desktop skips, so look up to three ahead."""
    base = pinned
    if latest and RELEASE_RE.match(latest) and version_key(latest) > version_key(base):
        base = latest
    parts = version_key(base)
    major, patch = parts[0], parts[2] if len(parts) == 3 else 0
    return [f"{major}.0.{patch + 1}", f"{major}.0.{patch + 2}", f"{major}.0.{patch + 3}", f"{major + 1}.0", f"{major + 1}.0.1"]


def history_kind(version: str) -> str:
    return "major" if version.count(".") == 1 else "stability"


def release_clock(day: str, commits: list | None) -> tuple[_dt.datetime, str]:
    """When Mozilla published: the first product-details commit of that day, else the day's start (earlier, stricter)."""
    midnight = _dt.datetime.fromisoformat(day).replace(tzinfo=_dt.UTC)
    times = []
    for item in commits or []:
        try:
            stamp = _dt.datetime.fromisoformat(item["commit"]["committer"]["date"].replace("Z", "+00:00"))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if stamp.tzinfo is not None and midnight <= stamp < midnight + _dt.timedelta(days=1):
            times.append(stamp.astimezone(_dt.UTC))
    return (min(times), "product-details-commit") if times else (midnight, "date")


def plain(text, limit: int = 300) -> str:
    """External text made inert for Markdown (job summary, issues): no HTML, mentions, links to issues or tables."""
    text = re.sub(r"\s+", " ", str(text)).strip().replace("<!--", "").replace("-->", "")
    text = re.sub(r"[\\|`*_\[\]]", lambda match: "\\" + match.group(0), text).replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"#(?=\d)", "#\u200b", text.replace("@", "@\u200b"))
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- where the data comes from ------------------------------------------------


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in HOSTS:
            raise urllib.error.HTTPError(newurl, code, "redirect outside the allowed https hosts refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _verify_signed(version: str) -> tuple[str, str]:
    import verify_firefox_release

    try:
        return verify_firefox_release.signed_source_digest(version)
    except SystemExit as exc:
        raise VerificationFailed(str(exc.code)) from None
    except subprocess.CalledProcessError as exc:
        raise VerificationFailed(f"gpg could not import Mozilla's KEY file ({exc.returncode})") from None


def pinned_primary() -> str:
    import verify_firefox_release

    return verify_firefox_release.PINNED_PRIMARY


class Network:
    """Live data: fixed https hosts, a few retries, bounded sizes, and an overall time budget."""

    def __init__(self, token: str | None = None, budget: float = 200.0, sleep=time.sleep, opener=None):
        self.token = token
        self.deadline = time.monotonic() + budget
        self.sleep = sleep
        self.opener = opener or urllib.request.build_opener(_HttpsOnlyRedirects())

    def request(self, url: str, *, method: str = "GET", limit: int = 4 << 20, accept: str | None = None) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in HOSTS:
            raise ValueError(f"refusing to fetch {url}")
        error: OSError | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            request = urllib.request.Request(url, method=method, headers={"User-Agent": "nulavio-watch-upstream"})  # noqa: S310
            if accept:
                request.add_header("Accept", accept)
            if self.token and parts.hostname == "api.github.com":
                # Unredirected: urllib does not copy it to a redirect target.
                request.add_unredirected_header("Authorization", f"Bearer {self.token}")
            try:
                with self.opener.open(request, timeout=30) as response:
                    data = b"" if method == "HEAD" else response.read(limit + 1)
                    if len(data) > limit:
                        raise ValueError(f"{url}: response larger than {limit} bytes")
                    return response.status, data
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code == 404:
                    return 404, b""
                if exc.code < 500 and exc.code != 429:
                    raise
                error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                error = exc
            if attempt == len(RETRY_DELAYS) or time.monotonic() + RETRY_DELAYS[attempt] > self.deadline:
                break
            self.sleep(RETRY_DELAYS[attempt])
        raise error or OSError(f"{url}: no answer")

    def _json(self, url: str, **kwargs):
        code, data = self.request(url, **kwargs)
        if code != 200:
            raise OSError(f"{url}: HTTP {code}")
        return json.loads(data)

    def product(self, name: str):
        if name not in (VERSIONS, *SOURCES):
            raise ValueError(name)
        return self._json(PRODUCT + name, limit=1 << 20)

    def staged(self, version: str) -> bool:
        if not RELEASE_RE.match(version):
            raise ValueError(version)
        code, _ = self.request(ARCHIVE.format(version=version), method="HEAD")
        if code not in (200, 404):
            raise OSError(f"archive.mozilla.org answered HTTP {code} for {version}")
        return code == 200

    def verify(self, version: str) -> tuple[str, str]:
        if not RELEASE_RE.match(version):
            raise ValueError(version)
        return _verify_signed(version)

    def advisory_names(self, year: int) -> list[str]:
        url = MFSA_INDEX.format(year=int(year))
        code, data = self.request(url, accept="application/vnd.github+json")
        if code == 404:
            raise ListingMissing(f"{url}: HTTP 404")
        if code != 200:
            raise OSError(f"{url}: HTTP {code}")
        return advisory_listing(json.loads(data))

    def advisory_text(self, year: int, name: str) -> str:
        if not mfsa.NAME_RE.match(name):
            raise ValueError(name)
        code, data = self.request(MFSA_RAW.format(year=int(year), name=name), limit=1 << 20)
        if code != 200:
            raise OSError(f"{name}: HTTP {code}")
        return data.decode("utf-8")

    def release_commits(self, kind: str, day: str) -> list:
        if kind not in ("major", "stability") or not DATE_RE.match(day):
            raise ValueError(f"{kind} {day}")
        query = urllib.parse.urlencode(
            {
                "sha": "production",
                "path": f"public/1.0/firefox_history_{kind}_releases.json",
                "since": f"{day}T00:00:00Z",
                "until": f"{day}T23:59:59Z",
                "per_page": "100",
            }
        )
        return self._json(f"{COMMITS}?{query}", accept="application/vnd.github+json")


class Offline:
    """Recorded responses, for tests. Layout under the directory:

    product-details/<file>                 the three product-details files
    archive/<version>/SHA256SUMS.asc       present = staged on archive.mozilla.org
    archive/<version>/verified.json        {"source_sha256", "signing_subkey"} or {"error": "..."}
    github/announce/<year>.json            the contents listing ([{"name": "mfsa2026-118.yml"}, ...])
    github/commits/<major|stability>-<day>.json
    mfsa/<name>                            advisory files
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def product(self, name: str):
        return json.loads((self.root / "product-details" / name).read_text(encoding="utf-8"))

    def staged(self, version: str) -> bool:
        return (self.root / "archive" / version / "SHA256SUMS.asc").is_file()

    def verify(self, version: str) -> tuple[str, str]:
        path = self.root / "archive" / version / "verified.json"
        if not path.is_file():
            raise OSError(f"no recorded verification for {version}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("error"):
            raise VerificationFailed(str(data["error"]))
        return data["source_sha256"], data["signing_subkey"]

    def advisory_names(self, year: int) -> list[str]:
        path = self.root / "github" / "announce" / f"{int(year)}.json"
        if not path.is_file():
            raise ListingMissing(f"no recorded listing for {int(year)}")
        return advisory_listing(json.loads(path.read_text(encoding="utf-8")))

    def advisory_text(self, year: int, name: str) -> str:
        return (self.root / "mfsa" / name).read_text(encoding="utf-8")

    def release_commits(self, kind: str, day: str) -> list:
        path = self.root / "github" / "commits" / f"{kind}-{day}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


# --- advisories ----------------------------------------------------------------


def _fresh(entry, stamp: str, now: _dt.datetime | None) -> bool:
    """A cache entry younger than CACHE_TTL (anything malformed is stale)."""
    try:
        return isinstance(entry, dict) and now - _dt.datetime.fromisoformat(entry[stamp]) < CACHE_TTL
    except (KeyError, TypeError, ValueError):
        return False


def _cached_text(cache: dict | None, name: str, fetch, now: _dt.datetime) -> str:
    entries = cache.setdefault("mfsa", {}) if cache is not None else {}
    entry = entries.get(name)
    if _fresh(entry, "fetched_at", now) and isinstance(entry.get("text"), str):
        return entry["text"]
    text = fetch()
    entries[name] = {"fetched_at": now.isoformat(), "text": text}
    return text


def find_advisories(src, versions: list[str], days: dict[str, str | None], now: _dt.datetime, cache: dict | None = None):
    """Advisories for each target version, and the versions whose advisory could not be read.

    Reads the newest advisory files first (numeric order) and stops after three
    in a row that were announced before the earliest target's day, minus one day.
    Mozilla's directory for a year appears with its first advisory, so only the
    current year may be missing or empty, and only while no target was released
    in it; anywhere else that means the index moved: an error, not "no advisory".
    """
    today = now.date()
    released = [_dt.date.fromisoformat(day) for day in days.values() if day]
    oldest = min([*released, today]) - _dt.timedelta(days=1)
    names = []
    for year in range(oldest.year, today.year + 1):
        try:
            listed = [name for name in src.advisory_names(year) if mfsa.NAME_RE.match(name)]
        except ListingMissing:
            listed = None
        if not listed and (year < today.year or any(day.year >= year for day in released)):
            state = "missing" if listed is None else "empty"
            raise OSError(f"Mozilla's advisory listing for {year} is {state}, but {year} must have advisories")
        names += listed or []
    names.sort(key=mfsa.sort_key, reverse=True)
    found: dict[str, list] = {version: [] for version in versions}
    unreadable: dict[str, str] = {}
    older_in_a_row = 0
    for count, name in enumerate(names):
        if count >= MAX_ADVISORY_FILES:
            raise OSError(f"more than {MAX_ADVISORY_FILES} advisories since {oldest}; not searching further")
        year = mfsa.sort_key(name)[0]
        text = _cached_text(cache, name, lambda year=year, name=name: src.advisory_text(year, name), now)
        try:
            advisory = mfsa.parse(text, name)
        except mfsa.MfsaFormatError as exc:
            for version in versions:
                if mfsa.mentions_desktop(text, version):
                    unreadable[version] = str(exc)
            continue
        for version in versions:
            if mfsa.applies_to(advisory, version):
                found[version].append(advisory)
        older_in_a_row = older_in_a_row + 1 if advisory.announced < oldest else 0
        if older_in_a_row >= 3:
            break
    return found, unreadable


# --- the report ------------------------------------------------------------------


def _hours(delta: _dt.timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def _stamp(moment: _dt.datetime | None) -> str | None:
    return moment.astimezone(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if moment else None


def _verify_into(src, version: str, record: dict, *, cache: dict | None = None, phase: str = "", now=None) -> bool:
    """Check Mozilla's signature for `version` and fill `record`. False only when it did not verify.

    With a cache (the local timer's state), a success is reused for 6 hours while the
    release stays in the same phase; publication forces a fresh check. Failures are
    never cached. Builds verify again on their own (bump_engine.py, fetch_firefox_source.py).
    """
    entries = cache.setdefault("verified", {}) if cache is not None else {}
    key = f"{version}:{phase}"
    hit = entries.get(key)
    usable = (
        _fresh(hit, "checked_at", now) and isinstance(hit.get("source_sha256"), str) and SHA256_RE.match(hit["source_sha256"])
    )
    try:
        digest, subkey = (hit["source_sha256"], hit.get("signing_subkey")) if usable else src.verify(version)
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            raise VerificationFailed(f"unexpected digest {digest!r}")
    except VerificationFailed as exc:
        entries.pop(key, None)
        record.update(verified=False, verification_error=str(exc))
        return False
    if not usable and cache is not None:
        entries[key] = {"checked_at": now.isoformat(), "source_sha256": digest, "signing_subkey": subkey}
    record.update(verified=True, source_sha256=digest, signing_primary=pinned_primary(), signing_subkey=subkey)
    return True


def check(*, pinned: str, pinned_sha256: str | None, src, now: _dt.datetime, verify: bool, cache: dict | None = None) -> dict:
    """The schema-2 report (fields: docs/architecture/update-policy.md)."""
    if not RELEASE_RE.match(pinned):
        raise ValueError(f"engine.json 'firefox' must be a Release version such as 158.0.1, not {pinned!r}")
    errors: list[str] = []
    try:
        versions_doc = src.product(VERSIONS)
        raw: dict = {}
        for name in SOURCES:
            raw.update(src.product(name))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise DataUnavailable(f"Mozilla's release data is unavailable: {exc}") from exc
    history = release_history(raw)
    if not history:
        raise DataUnavailable("Mozilla's release history is empty")
    latest = versions_doc.get("LATEST_FIREFOX_VERSION") if isinstance(versions_doc, dict) else None
    latest = latest if isinstance(latest, str) and RELEASE_RE.match(latest) else None
    if latest and latest not in history and version_key(latest) > version_key(pinned):
        day = versions_doc.get("LAST_RELEASE_DATE")
        history[latest] = day if isinstance(day, str) and DATE_RE.match(day) else now.date().isoformat()
        errors.append(f"{latest} is the latest release but missing from the history; dated {history[latest]}")

    pinned_record: dict = {"firefox": pinned, "source_sha256": pinned_sha256, "verified": None}
    verification_failed = False
    if verify and pinned_sha256:
        record: dict = {}
        try:
            if _verify_into(src, pinned, record, cache=cache, phase="pinned", now=now):
                if record["source_sha256"] != pinned_sha256:
                    pinned_record.update(verified=False)
                    signed = record["source_sha256"]
                    errors.append(f"engine.json pins {pinned_sha256} for {pinned}, Mozilla's signed SHA256SUMS lists {signed}")
                    verification_failed = True
                else:
                    pinned_record.update(verified=True, signing_subkey=record["signing_subkey"])
            else:
                pinned_record.update(verified=False, verification_error=record["verification_error"])
                verification_failed = True
        except (OSError, ValueError) as exc:
            errors.append(f"signature check for the pinned {pinned} could not run: {exc}")

    shipped = sorted((v for v in history if version_key(v) > version_key(pinned)), key=lambda v: (history[v], version_key(v)))
    on_archive = []
    for version in next_candidates(pinned, latest):
        if version in history or version_key(version) <= version_key(pinned):
            continue
        try:
            if src.staged(version):
                on_archive.append(version)
        except (OSError, ValueError) as exc:
            errors.append(f"archive.mozilla.org check for {version} failed: {exc}")

    targets = [
        {"version": v, "shipped": v in history, "released": history.get(v), "verified": None} for v in shipped + on_archive
    ]
    newest = sorted((t["version"] for t in targets), key=version_key, reverse=True)[:MAX_VERIFY]
    for target in targets:
        if not verify or target["version"] not in newest:
            continue
        try:
            phase = "shipped" if target["shipped"] else "staged"
            if not _verify_into(src, target["version"], target, cache=cache, phase=phase, now=now):
                verification_failed = True
        except (OSError, ValueError) as exc:
            errors.append(f"signature check for {target['version']} could not run: {exc}")

    found: dict = {}
    unreadable: dict = {}
    advisories_down = False
    if targets:
        try:
            days = {t["version"]: t["released"] for t in targets}
            found, unreadable = find_advisories(src, list(days), days, now, cache)
        except (OSError, ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
            advisories_down = True
            errors.append(f"advisories unavailable: {exc}")

    clocks = 0
    for target in targets:
        version = target["version"]
        if target["shipped"]:
            target["phase"] = "shipped"
        elif target["verified"] is True or (not verify and target["verified"] is None):
            target["phase"] = "staged"
        else:
            target["phase"] = "unconfirmed"  # on the archive; signature failed or could not be checked yet
        target["staged"] = target["phase"] == "staged"
        released_at = released_by = None
        clock_source = None
        if target["shipped"]:
            commits = None
            if clocks < MAX_CLOCKS:
                clocks += 1
                try:
                    commits = src.release_commits(history_kind(version), target["released"])
                except (OSError, ValueError) as exc:
                    errors.append(f"publication time of {version} unavailable, using the start of its day: {exc}")
            released_at, clock_source = release_clock(target["released"], commits)
            released_by = released_at if clock_source == "product-details-commit" else released_at + _dt.timedelta(days=1)
        verdict = mfsa.classify(
            found.get(version, []), released_by=released_by, now=now, error=unreadable.get(version), unavailable=advisories_down
        )
        target_hours = URGENT_TARGET_HOURS if verdict.urgency == "urgent" else SLA_HOURS
        target.update(
            released_at=_stamp(released_at),
            clock_source=clock_source,
            urgency=verdict.urgency,
            advisory_status=verdict.advisory_status,
            reasons=list(verdict.reasons),
            itw=verdict.itw,
            public_exploit=verdict.public_exploit,
            sandbox_escape=verdict.sandbox_escape,
            emergency=verdict.emergency,
            max_impact=verdict.max_impact,
            platform_notes=list(verdict.platform_notes),
            advisories=[mfsa.summary(advisory) for advisory in found.get(version, [])],
            target_hours=target_hours,
            deadline_hours=SLA_HOURS,
            target=None,
            target_hours_left=None,
            target_missed=False,
            deadline=None,
            hours_left=None,
            overdue=False,
        )
        if released_at is not None:
            target_at = released_at + _dt.timedelta(hours=target_hours)
            deadline = released_at + _dt.timedelta(hours=SLA_HOURS)
            target.update(
                target=_stamp(target_at),
                target_hours_left=_hours(target_at - now),
                target_missed=now > target_at,
                deadline=_stamp(deadline),
                hours_left=_hours(deadline - now),
                overdue=now > deadline,
            )

    overdue = any(t["overdue"] for t in targets)
    if overdue:
        state = "overdue"
    elif any(t["shipped"] for t in targets):
        state = "pending"
    elif any(t["staged"] for t in targets):
        state = "staged"
    else:
        state = "up-to-date"
    first = next((t for t in targets if t["shipped"]), None)
    report = {
        "schema": 2,
        "checked_at": _stamp(now),
        "pinned": pinned_record,
        "policy": {"deadline_hours": SLA_HOURS, "urgent_target_hours": URGENT_TARGET_HOURS},
        "state": state,
        "verification_failed": verification_failed,
        "exit_code": 3 if verification_failed else 1 if overdue else 0,
        "newer": shipped,
        "first": first["version"] if first else None,
        "target": first["target"] if first else None,
        "deadline": first["deadline"] if first else None,
        "hours_left": first["hours_left"] if first else None,
        "targets": targets,
        "errors": errors,
        "advisories_index": ADVISORIES,
    }
    report["summary"] = describe_report(report)
    return report


def _when(stamp: str | None) -> str:
    if not stamp:
        return "?"
    return stamp.replace("T", " ").removesuffix("Z").removesuffix(":00") + " UTC"


def describe_target(target: dict) -> str:
    version = target["version"]
    urgency = f"{target['urgency'].upper()} ({'; '.join(target['reasons'])})"
    if target["phase"] == "unconfirmed":
        if target.get("verified") is False:
            return (
                f"Firefox {version}: signature verification FAILED ({target.get('verification_error')}): "
                "a key rotation, an upload in progress, or tampering. Nothing may be built from it."
            )
        return f"Firefox {version}: on archive.mozilla.org, signature not confirmed yet."
    if target["phase"] == "staged":
        checked = "signature verified" if target.get("verified") else "signature not checked"
        return (
            f"Firefox {version}: staged on archive.mozilla.org ({checked}), not published yet; the "
            f"{target['target_hours']} h target and the {SLA_HOURS} h deadline start when Mozilla publishes. "
            f"Urgency so far: {urgency}."
        )
    clock = "" if target["clock_source"] == "product-details-commit" else " (start of the day: time unknown)"
    head = f"Firefox {version}: released {_when(target['released_at'])}{clock}. {urgency}."
    if target["overdue"]:
        return f"{head} OVERDUE: the {SLA_HOURS}-hour deadline passed at {_when(target['deadline'])}."
    goal = f"Target {_when(target['target'])} ({target['target_hours']} h, {target['target_hours_left']} h left)"
    if target["target_missed"]:
        goal = f"Target {_when(target['target'])} ({target['target_hours']} h) MISSED"
    return f"{head} {goal}; deadline {_when(target['deadline'])} ({SLA_HOURS} h, {target['hours_left']} h left)."


def describe_report(report: dict) -> str:
    if report.get("state") == "unavailable":
        return f"No verdict: {'; '.join(report.get('errors') or ['release data unavailable'])}"
    pinned = report["pinned"]["firefox"]
    lines = [f"Nulavio ships Firefox {pinned}" + (", the latest release." if not report["targets"] else ".")]
    if report["pinned"].get("verified") is False:
        lines.append(f"The pinned Firefox {pinned} did NOT match Mozilla's signed checksums: see the errors.")
    lines += [describe_target(t) for t in report["targets"]]
    return "\n".join(lines)


def markdown(report: dict) -> str:
    """The GitHub job summary. Every line goes through plain(): data from outside is inert."""
    lines = ["### Upstream Firefox", ""]
    lines += [f"- {plain(line, 1000)}" for line in describe_report(report).splitlines()]
    if report.get("targets"):
        lines += [
            "",
            "| Firefox | Phase | Urgency | Target | Deadline (72 h) | In the wild | Advisories |",
            "|---|---|---|---|---|---|---|",
        ]
        for target in report["targets"]:
            advisories = ", ".join(f"[{a['id']}]({a['url']})" for a in target["advisories"] if mfsa.ID_RE.match(a["id"]))
            cells = [
                plain(target["version"]),
                plain(target["phase"]),
                plain(f"{target['urgency']}: {'; '.join(target['reasons'])}"),
                plain(f"{_when(target['target'])} ({target['target_hours']} h)" if target["target"] else "starts at publication"),
                plain(_when(target["deadline"]) if target["deadline"] else "starts at publication"),
                plain(target["itw"]),
                advisories or plain(target["advisory_status"]),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    if report.get("errors"):
        lines += ["", "Problems:"] + [f"- {plain(error)}" for error in report["errors"]]
    lines += ["", f"Advisories: {ADVISORIES}", ""]
    return "\n".join(lines)


# --- command line -------------------------------------------------------------------


def load_engine(path: Path) -> tuple[str, str | None]:
    engine = json.loads(path.read_text(encoding="utf-8"))
    digest = engine.get("source_sha256")
    if digest is not None and not (isinstance(digest, str) and SHA256_RE.match(digest)):
        raise ValueError("engine.json source_sha256 must be 64 lowercase hex digits")
    return engine["firefox"], digest


def load_cache(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(path: Path | None, cache: dict | None, now: _dt.datetime) -> None:
    if path is None or cache is None:
        return
    kept = {
        section: {key: entry for key, entry in (cache.get(section) or {}).items() if _fresh(entry, stamp, now)}
        for section, stamp in (("mfsa", "fetched_at"), ("verified", "checked_at"))
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(kept), encoding="utf-8")
    partial.replace(path)


def evaluate(*, engine: Path, src, now: _dt.datetime, verify: bool, state: Path | None = None) -> dict:
    """check() for the command line and autobuild.py: never raises; no verdict is reported as exit code 2."""
    try:
        pinned, digest = load_engine(engine)
        cache = load_cache(state)
        report = check(pinned=pinned, pinned_sha256=digest, src=src, now=now, verify=verify, cache=cache)
        save_cache(state, cache, now)
        return report
    except DataUnavailable as exc:
        problem = str(exc)
    except Exception as exc:  # a crash must not read as "up to date" or as "overdue"
        traceback.print_exc()
        problem = f"watcher error: {exc.__class__.__name__}: {exc}"
    return {"schema": 2, "checked_at": _stamp(now), "state": "unavailable", "exit_code": 2, "targets": [], "errors": [problem]}


def parse_now(text: str | None) -> _dt.datetime:
    if not text:
        return _dt.datetime.now(_dt.UTC)
    moment = _dt.datetime.fromisoformat(text)
    return moment.replace(tzinfo=_dt.UTC) if moment.tzinfo is None else moment.astimezone(_dt.UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the schema-2 report as JSON")
    parser.add_argument("--summary", type=Path, help="append a Markdown summary (GitHub job summary)")
    parser.add_argument("--verify", action="store_true", help="check Mozilla's signature for each target and the pinned version")
    parser.add_argument("--state", type=Path, help="cache file for advisories and verified signatures (6 hours)")
    parser.add_argument("--offline", type=Path, help="read recorded responses from this directory (tests)")
    parser.add_argument("--now", help="evaluate at this time (ISO 8601; UTC if no offset)")
    parser.add_argument("--engine", type=Path, default=ENGINE, help="engine.json to compare (default: the repository's)")
    args = parser.parse_args(argv)
    src = Offline(args.offline) if args.offline else Network(token=os.environ.get("GITHUB_TOKEN") or None)
    report = evaluate(engine=args.engine, src=src, now=parse_now(args.now), verify=args.verify, state=args.state)
    if report["exit_code"] == 2:
        print(f"watch_upstream: {report['errors'][0]}", file=sys.stderr)
    print(json.dumps(report, indent=2) if args.json else describe_report(report))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(markdown(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
