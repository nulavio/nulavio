"""#482: the build container's image is built again from nothing when podman's copy is old.

The Containerfile installs `rust` without a version, so a cached image keeps its Rust compiler for as long as
it exists. scripts/build/build_image.sh decides by the image's age, which these tests drive with a stub
`podman` that records what it was asked to do."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build" / "build_image.sh"

STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$1 $2" in
"image inspect")
    [ -n "$STUB_CREATED" ] || exit 1
    echo "$STUB_CREATED" ;;
"run --rm") echo "rustc 1.99.1 (58cf8f9c 2026-01-01)" ;;
esac
exit 0
"""


class BuildImageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        (tmp / "bin").mkdir()
        stub = tmp / "bin" / "podman"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.log = tmp / "podman.log"
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("NULAVIO_")},
            "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
        }

    def build(self, created_days_ago=None, **env):
        self.log.unlink(missing_ok=True)
        env = {**self.env, **env}
        if created_days_ago is not None:
            env["STUB_CREATED"] = str(int(time.time() - created_days_ago * 86400))
        else:
            env["STUB_CREATED"] = ""
        done = subprocess.run(
            ["bash", str(SCRIPT), "localhost/img:t", "ci/F", "ci", "--memory=1g"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return done, [c for c in calls if c.startswith("build ")]

    def test_a_missing_image_is_built_without_the_cache(self):
        done, builds = self.build(None)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(builds), 1)
        self.assertIn("--no-cache", builds[0])

    def test_an_old_image_is_built_again_without_the_cache(self):
        done, builds = self.build(5)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--no-cache", builds[0])
        self.assertIn("5 day(s) old", done.stdout)

    def test_a_young_image_keeps_the_cache(self):
        done, builds = self.build(0.2)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(builds), 1)
        self.assertNotIn("--no-cache", builds[0])

    def test_the_limit_is_configurable_and_zero_means_every_time(self):
        self.assertIn("--no-cache", self.build(0.2, NULAVIO_IMAGE_MAX_AGE_DAYS="0")[1][0])
        self.assertNotIn("--no-cache", self.build(5, NULAVIO_IMAGE_MAX_AGE_DAYS="30")[1][0])

    def test_a_bad_limit_is_refused_before_any_build(self):
        done, builds = self.build(5, NULAVIO_IMAGE_MAX_AGE_DAYS="soon")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(builds, [])

    def test_options_reach_podman_and_the_compiler_is_reported(self):
        done, builds = self.build(0.2)
        self.assertIn("--memory=1g", builds[0])
        self.assertIn("-t localhost/img:t -f ci/F ci", builds[0])
        self.assertIn("localhost/img:t has rustc 1.99.1", done.stdout)

    def test_the_build_script_goes_through_it(self):
        text = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text(encoding="utf-8")
        self.assertIn('"$repo/scripts/build/build_image.sh"', text)
        self.assertNotIn("podman build", text)


if __name__ == "__main__":
    unittest.main()
