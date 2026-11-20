"""Ask an installed Nulavio's tools which engine they would start, with a distribution Firefox next to it (#575).

Runs inside the package check containers, as an unprivileged user, with NULAVIO_ENGINE unset: the lookup the tools do
when an agent starts them, as `nulavio-tools/bin/nulavio` does (isolated mode, the tools' own launcher directory).
The advisory GHSA-95h5-h3m4-3jhv was a lookup that found the distribution's Firefox first. Prints one line, or the
wrong answer and exits 1.

    python3 -I engine_lookup_probe.py /usr/lib64/nulavio
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    install = Path(sys.argv[1])
    if os.environ.get("NULAVIO_ENGINE"):
        print("engine_lookup_probe: NULAVIO_ENGINE is set, which would hide the lookup")
        return 1
    sys.path.insert(0, str(install / "nulavio-tools" / "launcher"))
    from nulavio_launcher import engine

    found = engine.find_engine()
    if found.path != (install / "nulavio").resolve() or found.vendor != "Nulavio":
        print(f"engine_lookup_probe: the tools resolve to {found.path} ({found.vendor}), expected {install}/nulavio (Nulavio)")
        return 1
    print(f"nulavio-tools engine: {found.path} ({found.vendor})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
