#!/usr/bin/env python3
"""Check that nulavio.net serves a given build of the site (after a deploy).

    python3 -I scripts/site/verify_live.py dist/site [--base https://nulavio.net/] [--wait 300]

The pages in CHECKED must come back byte for byte as built (so the deploy is live
and nothing on the way, such as email obfuscation, rewrote them), and the home page
must carry every header of the build's _headers. Retries until --wait seconds
have passed, because a new deployment can take a moment to reach every edge.
Exit status 0 when everything matches, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

# URL path -> file in the build.
CHECKED = {
    "": "index.html",
    "en/": "en/index.html",
    "lista/": "lista/index.html",  # a page next to /api/*: static files must not go through site/_worker.js
    ".well-known/security.txt": ".well-known/security.txt",
}
USER_AGENT = "nulavio-site-verify (+https://nulavio.net/)"

Fetch = Callable[[str], tuple[int, dict[str, str], bytes]]


def expected_headers(dist: Path) -> dict[str, str]:
    """Header name (lowercase) -> value, from the "/*" rule of the build's _headers."""
    headers: dict[str, str] = {}
    rule = None
    for line in (dist / "_headers").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            rule = line.strip()
        elif rule == "/*":
            name, _, value = line.strip().partition(":")
            headers[name.strip().lower()] = value.strip()
    if not headers:
        raise SystemExit("verify_live: no headers for /* in _headers")
    return headers


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    if not url.startswith("https://"):
        raise ValueError(f"not an https URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})  # noqa: S310 - https only, checked above
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https only, checked above
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def problems(dist: Path, base: str, get: Fetch) -> list[str]:
    """What the live site does differently from the build; empty when it serves the build."""
    found = []
    want_headers = expected_headers(dist)
    for path, name in CHECKED.items():
        url = base + path
        try:
            status, headers, body = get(url)
        except OSError as e:
            found.append(f"{url}: {e}")
            continue
        want = (dist / name).read_bytes()
        if status != 200:
            found.append(f"{url}: HTTP {status}")
        elif body != want:
            got, exp = hashlib.sha256(body).hexdigest()[:12], hashlib.sha256(want).hexdigest()[:12]
            found.append(f"{url}: {len(body)} bytes (sha256 {got}), the build has {len(want)} (sha256 {exp})")
        if path == "":
            for header, value in want_headers.items():
                if headers.get(header) != value:
                    found.append(f"{url}: {header} is {headers.get(header)!r}, _headers says {value!r}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", type=Path, help="the build that was deployed (scripts/site/build_site.py --out)")
    parser.add_argument("--base", default="https://nulavio.net/")
    parser.add_argument("--wait", type=int, default=300, help="seconds to keep retrying")
    args = parser.parse_args()
    base = args.base if args.base.endswith("/") else args.base + "/"
    if not base.startswith("https://"):
        parser.error("--base must be an https URL")
    deadline = time.monotonic() + args.wait
    while True:
        found = problems(args.dist, base, fetch)
        if not found:
            print(f"{base} serves this build: {', '.join(base + p for p in CHECKED)} and the _headers headers")
            return 0
        if time.monotonic() >= deadline:
            print("\n".join(f"verify_live: {p}" for p in found), file=sys.stderr)
            return 1
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
