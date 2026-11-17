"""Check what `nulavio-doctor --json` says on a clean package install (#470).

Runs inside the package check containers, on the doctor's JSON (standard input), with the directory the package
put the engine in. A package install must find that engine, see it owned by the nulavio package, and find the codec
library the package recommends. Prints one line, or the failed check and exits 1.

    nulavio-doctor --json | python3 -I doctor_probe.py /usr/lib64/nulavio
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    engine_dir = sys.argv[1].rstrip("/") + "/"
    checks = {(c["area"], c["name"]): c for c in json.load(sys.stdin)}
    wanted = {
        ("engine", "binary"): lambda c: c["status"] == "ok" and engine_dir in c["detail"] and "Nulavio" in c["detail"],
        # Owned by the nulavio package itself: "package nulavio-<v>-<r>.<arch>" (rpm) or "package nulavio <v>" (dpkg).
        ("engine", "updates"): lambda c: c["status"] == "ok" and c["detail"].startswith(("package nulavio-", "package nulavio ")),
        ("media", "codec library"): lambda c: c["status"] == "ok",
    }
    for key, holds in wanted.items():
        check = checks.get(key)
        if check is None or not holds(check):
            print(f"nulavio-doctor: {key}: {check}")
            return 1
    print(f"nulavio-doctor: the package's engine ({checks[('engine', 'updates')]['detail']}), codecs found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
