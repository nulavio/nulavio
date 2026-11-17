"""A repository's build inputs and its networking-check record, for tests of the gates that read them (#430)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import networking_check  # noqa: E402

RECORD = "browser/build/networking-check.json"
# A real patch of one line, and the file it touches before and after (for a tree that has it applied or not).
PATCH = "--- a/dom/x.cpp\n+++ b/dom/x.cpp\n@@ -1 +1 @@\n-int before;\n+int after;\n"
PATCHED_FILE, UNPATCHED, PATCHED = "dom/x.cpp", "int before;\n", "int after;\n"


def write_inputs(repo: Path, *, mozconfig: str = "ac_add_options --enable-release\n", patch: str = PATCH) -> None:
    """The three things a record is bound to: the release mozconfig, the variant, and a patch stack of one patch."""
    build, patches = repo / "browser" / "build", repo / "browser" / "patches"
    build.mkdir(parents=True, exist_ok=True)
    patches.mkdir(parents=True, exist_ok=True)
    (build / "mozconfig").write_text(mozconfig)
    (build / "mozconfig.no-lto").write_text("ac_add_options --disable-lto\n")
    (patches / "series").write_text("# the stack\n0001-example.patch\n")
    (patches / "0001-example.patch").write_text(patch)


def record(repo: Path, firefox: str, source_sha256: str, **more) -> dict:
    """A passing record read with the repository's current inputs (pass fields to change or add)."""
    return {
        "firefox": firefox,
        "source_sha256": source_sha256,
        "result": "passed",
        "built_with": networking_check.repository_inputs(repo),
        **more,
    }


def write_record(repo: Path, firefox: str, source_sha256: str, **more) -> dict:
    written = record(repo, firefox, source_sha256, **more)
    (repo / RECORD).write_text(json.dumps(written))
    return written
