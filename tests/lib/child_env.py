"""The environment of a child that runs this Python (`sys.executable`), built from scratch (#833).

A test that gives such a child a small environment of its own (`env={"PATH": ...}`) drops what the
interpreter itself needs to start: a relocated or self-built Python finds `libpython` only through
`LD_LIBRARY_PATH`, and without it the child stops in the dynamic loader before Python runs, so the test fails
for a reason unrelated to what it checks. `child_env` adds the loader's search path from this process, and
nothing else from it. tests/unit/test_child_env.py checks that each unit test that starts `sys.executable` with
an environment of its own builds it here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# What the dynamic loader reads to find the interpreter's shared libraries (Linux; macOS).
INTERPRETER = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH")


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """`env`, plus the loader variables of INTERPRETER that this process has and `env` does not name."""
    kept = {name: os.environ[name] for name in INTERPRETER if name in os.environ}
    return {**kept, **env}
