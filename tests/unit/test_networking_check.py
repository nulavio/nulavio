"""The engine's networking check, read from a build's Rust library (scripts/build/networking_check.py, #430)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import networking_check as nc  # noqa: E402

VERSION = "199.0"
DIGEST = "ab" * 32
ENGINE = {"firefox": VERSION, "source_sha256": DIGEST}
# The engine's own file, as far as this reads it.
CHECK_BINARY = """
def check_networking(binary):
    retcode = 0
    networking_functions = set([
        # socketpair is not concerning; it is restricted to AF_UNIX
        "recv",
        "send",
        "gethostbyname",
        "gethostbyaddr",
        "gethostent",
        "sethostent",
        "endhostent",
        "getservbyname",
        "getprotobyname",
        "getprotoent",
    ])
    socket_functions = set(["connect", "accept", "listen"])
    return retcode
"""
CONFIG = """#!/usr/bin/python
from mozbuild.configure.constants import *
defines = {   'ACCESSIBILITY': '1'}
substs = {   'ACCESSIBILITY': '1',
    'OS_ARCH': 'Linux',
    'OS_TARGET': OS('GNU'),
    'RUST_LTO_CFLAGS': [],
    'RUST_LTO_ELIGIBLE': '1',%s
    'top_srcdir': '/src'}
"""


def readelf_text(*imports: str, undefined: int = 1500, defined_at_zero: tuple[str, ...] = ()) -> str:
    """`readelf --wide --syms` of an archive: a header, defined symbols, and undefined ones (Ndx UND, value 0)."""
    lines = ["", "File: libgkrust.a(gkrust.o)", "", "Symbol table '.symtab' contains 9 entries:",
             "   Num:    Value          Size Type    Bind   Vis      Ndx Name"]  # fmt: skip
    lines.append("     0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND ")
    lines.append("     1: 0000000000001040   312 FUNC    GLOBAL DEFAULT    4 _ZN6gkrust4mainE")
    for index, name in enumerate(defined_at_zero):
        lines.append(f"     {index + 2}: 0000000000000000    24 FUNC    GLOBAL DEFAULT    7 {name}")
    names = ["read", "write", "memcpy", *(f"extern_{n}" for n in range(undefined)), *imports]
    for index, name in enumerate(names):
        lines.append(f"  {index + 20}: 0000000000000000     0 NOTYPE  GLOBAL DEFAULT  UND {name}@GLIBC_2.2.5")
    return "\n".join(lines) + "\n"


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-netcheck-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tree = self.tmp / f"firefox-{VERSION}"
        check = self.tree / nc.CHECK_SOURCE
        check.parent.mkdir(parents=True)
        check.write_text(CHECK_BINARY)
        (self.tree / ".nulavio-source-sha256").write_text(DIGEST + "\n")
        objdir = self.tree / "obj-nulavio"
        (objdir / "x86_64-unknown-linux-gnu" / "release").mkdir(parents=True)
        self.config = objdir / "config.status"
        self.config.write_text(CONFIG % "")
        self.library = objdir / "x86_64-unknown-linux-gnu" / "release" / "libgkrust.a"
        self.library.write_bytes(b"!<arch>\n")
        now = time.time()
        os.utime(self.config, (now - 60, now - 60))
        self.output = readelf_text()
        self.calls: list[list[str]] = []

    def run_tool(self, argv, **_kwargs):
        self.calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=self.output, stderr="")

    def check(self, **more) -> dict:
        return nc.check(VERSION, self.tmp, engine=ENGINE, run=self.run_tool, which=lambda name: f"/usr/bin/{name}",
                        today="2026-11-16", **more)  # fmt: skip

    def refused(self) -> str:
        with self.assertRaises(nc.CannotCheck) as ctx:
            self.check()
        return str(ctx.exception)


class CheckTest(TreeCase):
    def test_a_library_that_imports_none_of_the_functions_passes(self):
        record = self.check()
        self.assertEqual((record["result"], record["firefox"], record["source_sha256"]), ("passed", VERSION, DIGEST))
        self.assertEqual(record["checked"], "2026-11-16")
        self.assertIn("networking_check.py", record["how"])
        self.assertIn("none of the engine's 10 networking functions", record["how"])
        self.assertEqual(self.calls, [["/usr/bin/readelf", "--wide", "--syms", str(self.library)]])  # an argument list
        # What was read and what built it, for a reviewer with a build of their own.
        self.assertEqual(record["library_sha256"], nc.sha256(self.library))
        self.assertEqual(record["built_with"]["mozconfig_sha256"], None)  # this tree has no mozconfig
        (self.tree / "mozconfig").write_text("ac_add_options --disable-lto\n")
        again = self.check()
        self.assertEqual(again["built_with"]["mozconfig_sha256"], nc.sha256(self.tree / "mozconfig"))
        self.assertRegex(again["built_with"]["patch_stack_sha256"], r"^[0-9a-f]{64}$")  # this repository's stack

    def test_a_library_that_imports_recv_fails(self):
        self.output = readelf_text("recv", "gethostbyname")
        record = self.check()
        self.assertEqual(record["result"], "failed")
        self.assertEqual(record["imported"], ["gethostbyname", "recv"])
        self.assertIn("it imports gethostbyname, recv", record["how"])

    def test_the_engines_rule_is_address_zero_also_for_a_defined_symbol(self):
        self.output = readelf_text(defined_at_zero=("send",))
        self.assertEqual(self.check()["imported"], ["send"])

    def test_the_names_come_from_the_tree_that_was_built(self):
        self.assertEqual(len(nc.listed_functions(self.tree)), 10)
        self.assertNotIn("connect", nc.listed_functions(self.tree))  # the engine keeps those for the crash monitor
        (self.tree / nc.CHECK_SOURCE).write_text("def check_networking(binary):\n    return main(binary)\n")
        self.assertIn("is not where it was", self.refused())
        (self.tree / nc.CHECK_SOURCE).unlink()
        self.assertIn("cannot be read", self.refused())

    def test_a_tree_that_is_not_the_pinned_release_is_refused(self):
        (self.tree / ".nulavio-source-sha256").write_text("cd" * 32)
        self.assertIn("not the release engine.json pins", self.refused())
        with self.assertRaises(nc.CannotCheck) as ctx:
            nc.check("198.0", self.tmp, engine=ENGINE, run=self.run_tool, which=lambda name: name)
        self.assertIn("engine.json pins Firefox 199.0, not 198.0", str(ctx.exception))
        (self.tree / ".nulavio-source-sha256").unlink()
        self.assertIn("not a source tree this project extracted", self.refused())

    def test_a_build_whose_library_says_nothing_is_refused(self):
        for extra, said in (
            ("\n    'MOZ_LTO_RUST_CROSS': '1',", "MOZ_LTO_RUST_CROSS"),  # the release build from #364 on
            ("\n    'MOZ_ASAN': '1',", "MOZ_ASAN"),
            ("\n    'MOZ_TSAN': '1',", "MOZ_TSAN"),
            ("\n    'RUST_SANCOV_FLAGS': ['-Cpasses=sancov'],", "RUST_SANCOV_FLAGS"),
            ("\n    'MOZ_PROFILE_GENERATE': '1',", "MOZ_PROFILE_GENERATE"),
        ):
            self.config.write_text(CONFIG % extra)
            os.utime(self.config, (time.time() - 60,) * 2)
            self.assertIn(said, self.refused(), extra)
        self.config.write_text((CONFIG % "").replace("    'RUST_LTO_ELIGIBLE': '1',", ""))
        os.utime(self.config, (time.time() - 60,) * 2)
        self.assertIn("without its own link-time optimisation", self.refused())
        self.config.write_text((CONFIG % "").replace("'OS_ARCH': 'Linux'", "'OS_ARCH': 'Darwin'"))
        os.utime(self.config, (time.time() - 60,) * 2)
        self.assertIn("'Darwin'", self.refused())
        self.assertEqual(self.calls, [])  # nothing was read

    def test_a_library_older_than_the_configuration_is_refused(self):
        os.utime(self.config, None)
        os.utime(self.library, (time.time() - 3600,) * 2)
        self.assertIn("older than the build's configuration", self.refused())

    def test_a_reading_that_looks_empty_is_refused_not_passed(self):
        for output in (
            "",
            readelf_text(undefined=20),
            readelf_text().replace(" read@", " r3ad@").replace(" write@", " wr1te@").replace(" memcpy@", " m3mcpy@"),
        ):
            self.output = output
            self.assertIn("looks empty", self.refused())

    def test_no_library_two_libraries_or_no_readelf_is_refused(self):
        other = self.library.parents[2] / "aarch64-unknown-linux-gnu" / "release"
        other.mkdir(parents=True)
        (other / "libgkrust.a").write_bytes(b"!<arch>\n")
        self.assertIn("found 2", self.refused())
        shutil.rmtree(other.parent)
        with self.assertRaises(nc.CannotCheck) as ctx:
            nc.check(VERSION, self.tmp, engine=ENGINE, run=self.run_tool, which=lambda _name: None)
        self.assertIn("no readelf", str(ctx.exception))
        self.library.unlink()
        self.assertIn("found 0", self.refused())

    def test_config_status_is_read_and_never_run(self):
        self.config.write_text("import os\nos.system('touch " + str(self.tmp / "ran") + "')\n" + CONFIG % "")
        os.utime(self.config, (time.time() - 60,) * 2)
        self.assertEqual(self.check()["result"], "passed")
        self.assertFalse((self.tmp / "ran").exists())


class MainTest(TreeCase):
    def main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        record = self.tmp / "networking-check.json"
        engine = self.tmp / "engine.json"
        engine.write_text(json.dumps(ENGINE))
        with (
            mock.patch.object(nc, "RECORD", record),
            mock.patch.object(nc, "ENGINE", engine),
            mock.patch.object(nc, "ROOT", self.tmp),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = nc.main([VERSION, "--work", str(self.tmp), *args], run=self.run_tool, which=lambda name: f"/usr/bin/{name}")
        return code, out.getvalue(), err.getvalue()

    def test_a_pass_is_printed_and_written_only_when_asked(self):
        code, out, _ = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["result"], "passed")
        self.assertNotIn("imported", json.loads(out))
        self.assertFalse((self.tmp / "networking-check.json").exists())
        code, out, _ = self.main("--write")
        self.assertEqual(code, 0)
        written = json.loads((self.tmp / "networking-check.json").read_text())
        self.assertEqual((written["firefox"], written["source_sha256"], written["result"]), (VERSION, DIGEST, "passed"))

    def test_a_finding_exits_1_names_the_functions_and_writes_nothing(self):
        self.output = readelf_text("recv")
        code, out, err = self.main("--write")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("FAILED: the Rust library imports recv", err)
        self.assertFalse((self.tmp / "networking-check.json").exists())

    def test_what_cannot_be_checked_exits_2_and_writes_nothing(self):
        self.library.unlink()
        code, out, err = self.main("--write")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not checked", err)
        self.assertFalse((self.tmp / "networking-check.json").exists())


@unittest.skipUnless(shutil.which("readelf") and shutil.which("cc") and shutil.which("ar"), "readelf, cc and ar are needed")
class RealArchiveTest(unittest.TestCase):
    """The reading against real object files: one archive that calls recv, one that does not."""

    def archive(self, tmp: Path, name: str, body: str) -> Path:
        source = tmp / f"{name}.c"
        source.write_text(body)
        subprocess.run(["cc", "-c", "-o", str(tmp / f"{name}.o"), str(source)], check=True, capture_output=True)
        subprocess.run(["ar", "rcs", str(tmp / f"lib{name}.a"), str(tmp / f"{name}.o")], check=True, capture_output=True)
        return tmp / f"lib{name}.a"

    def test_recv_is_seen_in_a_real_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            includes = "#include <sys/socket.h>\n#include <unistd.h>\n"
            calls = includes + "long f(int s, void *b) { return recv(s, b, 1, 0) + write(s, b, 1); }\n"
            quiet = "#include <unistd.h>\nlong f(int s, void *b) { return write(s, b, 1); }\n"
            _, at_zero, undefined = nc.symbols(nc.read_library(self.archive(Path(tmp), "calls", calls)))
            self.assertIn("recv", at_zero)
            self.assertLessEqual({"recv", "write"}, undefined)
            _, at_zero, undefined = nc.symbols(nc.read_library(self.archive(Path(tmp), "quiet", quiet)))
            self.assertNotIn("recv", at_zero)
            self.assertIn("write", undefined)


if __name__ == "__main__":
    unittest.main()
