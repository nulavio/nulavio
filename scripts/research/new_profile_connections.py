#!/usr/bin/env python3
"""Record what a new profile contacts by itself (docs/security/new-profile-connections.md).

Starts a Track B build as its desktop entry starts it (no flags, no remote control), headless, in a new throwaway home,
with the engine's own network log on, leaves it alone and prints every host it asked for and every name it resolved:

    python3 -I scripts/research/new_profile_connections.py <build>/nulavio/nulavio [--seconds 600] [--lang pt_BR] [--keep <dir>]

Hosts that are not in docs/security/new-profile-connections.json are marked. The integration test
(tests/integration/test_new_profile_connections.py) makes the same comparison over the first 75 seconds; this is the
longer look, for writing the page after an engine or content blocker update. It reaches the real services.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import connections  # noqa: E402


def record(engine: Path, seconds: int, lang: str, folder: Path) -> None:
    home = folder / "home"
    (home / "run").mkdir(parents=True, mode=0o700)
    env = {
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(home / "run"),
        "PATH": "/usr/bin:/bin",
        "LANG": f"{lang}.UTF-8",
        "MOZ_HEADLESS": "1",
        "MOZ_LOG": connections.ENGINE_LOG,
        "MOZ_LOG_FILE": str(folder / "engine"),
    }
    with open(folder / "engine.out", "ab") as output:
        process = subprocess.Popen([str(engine)], env=env, stdout=output, stderr=output, start_new_session=True)
        try:
            time.sleep(seconds)
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("engine", type=Path)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--lang", default="pt_BR")
    parser.add_argument("--keep", type=Path, help="keep the home directory and the engine's log in this new directory")
    args = parser.parse_args()
    if args.keep:
        args.keep.mkdir(parents=True)
    folder = (args.keep or Path(tempfile.mkdtemp(prefix="nulavio-connections-"))).resolve()
    try:
        record(args.engine.resolve(), args.seconds, args.lang, folder)
        addresses, names = connections.read_log(folder)
    finally:
        if not args.keep:
            shutil.rmtree(folder, ignore_errors=True)
    listed, names_only = connections.allowed(args.lang[:2])
    asked = dict.fromkeys((urlsplit(address).scheme, urlsplit(address).hostname) for address in addresses)
    unlisted = 0
    for scheme, host in asked:
        mark = "" if (scheme, host) in listed else "   NOT LISTED"
        unlisted += bool(mark)
        print(f"{scheme:5} {host}{mark}")
    for name in sorted(set(names) - {host for _, host in asked}):
        mark = "" if name in names_only else "   NOT LISTED"
        unlisted += bool(mark)
        print(f"name  {name}{mark}")
    if not asked:
        print("the engine's log names no request: did the build start?", file=sys.stderr)
        return 2
    return 1 if unlisted else 0


if __name__ == "__main__":
    sys.exit(main())
