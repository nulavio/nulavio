#!/usr/bin/env python3
"""Read a build's Rust library for the engine's networking check, and record the release that passed (#430).

    python3 -I scripts/build/networking_check.py <firefox-version> [--work DIR] [--write]

The engine has a build-time check, check_networking (python/mozbuild/mozbuild/action/check_binary.py):
its Rust library must import none of a list of networking functions (recv, send, the gethostby…,
getserv… and getproto… families), so that Rust code does not talk to the network around the engine's
own network stack, and so around a proxy the person set. The build system runs it only when Rust gets
its own link-time optimisation. A cross-language build (the release build since #364) and a
sanitised one skip it.

This does the same reading on a build that can be read, the mozconfig.no-lto variant: the undefined
symbols of libgkrust.a, against the list in the very source tree that was built. It takes nobody's
word: it refuses a tree that is not the pinned release, a build whose library cannot say anything (no
Rust LTO, cross-language LTO, a sanitiser), a library older than its source tree, and a reading that
looks empty. Run it after a build (the pre-check does): the build is what makes the library current.
With --write a passing result becomes browser/build/networking-check.json, which a unit test compares
with engine.json (test_track_b) and release_manifest.py with a manifest: the engine pin cannot move to,
and nothing can be published from, a release the record does not name. The record is a statement by
whoever ran this, not a proof CI makes (residual risk R79).

Exit status: 0 passed; 1 the library imports a listed function (named on stderr); 2 it could not be
checked (why, on stderr). It starts one process, readelf, with an argument list.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_patches  # noqa: E402

RECORD = ROOT / "browser" / "build" / "networking-check.json"
ENGINE = ROOT / "browser" / "build" / "engine.json"
CHECK_SOURCE = "python/mozbuild/mozbuild/action/check_binary.py"
# What makes the build system skip its own check (run_cargo.py), or the library unreadable for it.
MUST_BE_UNSET = ("MOZ_LTO_RUST_CROSS", "MOZ_ASAN", "MOZ_TSAN", "MOZ_UBSAN", "RUST_SANCOV_FLAGS", "MOZ_PROFILE_GENERATE")
# A reading of a real library has thousands of undefined names, these among them.
CANARIES = ("read", "write", "memcpy", "pthread_mutex_lock")
MIN_UNDEFINED = 1000
COMMENT = (
    "The Firefox release whose Rust code passed the engine's networking check (check_networking: the Rust library "
    "imports no recv, send, gethostby*, getserv* or getproto* function). Written by scripts/build/networking_check.py "
    "from a reading of libgkrust.a in a build with the mozconfig.no-lto variant; scripts/release/rehearse_release.sh "
    "--precheck runs it. A unit test requires this record to name the release engine.json pins, and "
    "release_manifest.py refuses to publish any other. It is a statement by whoever ran the script, reviewed in the "
    "pull request that lands it: CI checks that it names the pinned release, not that the build happened. Only the "
    'maintainer may pin a release without the check: "result": "accepted" with "accepted_in" naming the issue or '
    'pull request where he said so, and "built_with" as `networking_check.py <version> --inputs` prints it.'
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The only lines build_nulavio.sh appends to the tree's mozconfig after the variant.
MACHINE_LINE = re.compile(
    r"mk_add_options MOZ_PARALLEL_BUILD=\d{1,3}"
    r"|ac_add_options CARGO=/nulavio-build/cargo_serial\.sh"
    r"|ac_add_options CARGOFLAGS=--jobs=1"
)
MOZCONFIG = "browser/build/mozconfig"
VARIANT = "browser/build/mozconfig.no-lto"
SERIES = "browser/patches/series"


def inputs(read) -> dict:
    """What decides a build's Rust code besides the Firefox source: the release mozconfig, the variant the
    pre-check appends to it, and the patch stack. `read(path)` gives a repository file's bytes (from a
    checkout, or from a commit: release_manifest.py). A record carries these digests, and is only good for
    a tree whose three inputs still have them: a change to a patch or to the mozconfig asks for a new
    reading. Raises OSError (or what `read` raises) when a file is missing."""
    stack = hashlib.sha256()
    for line in read(SERIES).decode("utf-8").splitlines():
        name = line.strip()
        if name and not name.startswith("#"):
            stack.update(name.encode() + b"\0" + read(f"browser/patches/{name}"))
    return {
        "mozconfig_sha256": hashlib.sha256(read(MOZCONFIG)).hexdigest(),
        "variant_sha256": hashlib.sha256(read(VARIANT)).hexdigest(),
        "patch_stack_sha256": stack.hexdigest(),
    }


def repository_inputs(repo: Path = ROOT) -> dict:
    return inputs(lambda path: (repo / path).read_bytes())


def built_with(tree: Path, repo: Path = ROOT) -> dict:
    """The repository's inputs, once the tree is seen to have them: its mozconfig is the release mozconfig,
    then the variant, then lines of the machine's own (how many jobs), as build_nulavio.sh writes it; and
    every patch of this checkout's series is applied in it (apply_patches.py's own check, on a scratch copy:
    the tree is not touched). What this cannot see is that the library was built after them: that is why it
    runs after a build and not instead of one."""
    try:
        used = (tree / "mozconfig").read_bytes()
        expected = (repo / MOZCONFIG).read_bytes() + (repo / VARIANT).read_bytes()
    except OSError as error:
        raise CannotCheck(f"the build's mozconfig cannot be compared with the repository's ({error})") from None
    if not used.startswith(expected):
        raise CannotCheck(
            "the build's mozconfig is not this checkout's release mozconfig followed by mozconfig.no-lto: "
            "build again from this checkout (rehearse_release.sh --precheck does)"
        )
    # What may follow: the lines build_nulavio.sh adds for the machine (how many jobs, Cargo run one job at a
    # time). Any other option after the variant could change what was built without changing a digest here.
    extra = [line for line in used[len(expected) :].decode("utf-8", "replace").splitlines() if line.strip()]
    unknown = [line for line in extra if not MACHINE_LINE.fullmatch(line)]
    if unknown:
        raise CannotCheck(f"the build's mozconfig has an option this does not know after the variant: {unknown[0][:80]!r}")
    patches = repo / "browser" / "patches"
    try:
        names = [line.strip() for line in (patches / "series").read_text(encoding="utf-8").splitlines()]
        stack = [patches / name for name in names if name and not name.startswith("#")]
        applied = apply_patches.applied_prefix(tree, stack) if stack else 0
        found = repository_inputs(repo)
    except OSError as error:
        raise CannotCheck(f"the patch stack cannot be read ({error})") from None
    if applied != len(stack):
        raise CannotCheck(
            f"the source tree has {applied} of this checkout's {len(stack)} patches applied: it was built with another "
            "stack; build again from this checkout"
        )
    return found


class CannotCheck(RuntimeError):
    """The check could not be made: nothing is known about the library."""


def listed_functions(source_tree: Path) -> list[str]:
    """The names the engine's own check looks for, read from the tree that was built (it follows upstream)."""
    path = source_tree / CHECK_SOURCE
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise CannotCheck(f"{path}: the engine's check cannot be read ({error})") from None
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "check_networking":
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "networking_functions" for target in inner.targets)
                    and isinstance(inner.value, ast.Call)
                    and inner.value.args
                ):
                    try:
                        names = sorted(ast.literal_eval(inner.value.args[0]))
                    except ValueError:
                        break
                    if all(isinstance(name, str) for name in names) and {"recv", "send"} <= set(names) and len(names) >= 10:
                        return names
    raise CannotCheck(f"{path}: check_networking's list of functions is not where it was; read the engine's change first")


def substs(config_status: Path) -> dict:
    """The build's configuration values, read as text: config.status is never run here."""
    try:
        module = ast.parse(config_status.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise CannotCheck(f"{config_status}: the build's configuration cannot be read ({error})") from None
    for node in module.body:
        named = isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "substs" for t in node.targets)
        if named and isinstance(node.value, ast.Dict):
            found = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    try:
                        found[key.value] = ast.literal_eval(value)
                    except ValueError:
                        found[key.value] = ast.unparse(value)  # a named constant: set, whatever it is
            return found
    raise CannotCheck(f"{config_status}: no configuration values in it")


def readable_build(values: dict) -> None:
    """Refuse a build whose Rust library says nothing to this check (the conditions of the engine's run_cargo.py)."""
    if values.get("OS_ARCH") != "Linux":
        raise CannotCheck(f"the build is for {values.get('OS_ARCH')!r}: the check reads a Linux library")
    if not values.get("RUST_LTO_ELIGIBLE"):
        raise CannotCheck("Rust was built without its own link-time optimisation: build the mozconfig.no-lto variant")
    for name in MUST_BE_UNSET:
        if values.get(name):
            raise CannotCheck(f"the build has {name}: its Rust library cannot be read for this check; build mozconfig.no-lto")


def symbols(readelf_output: str) -> tuple[int, set[str], set[str]]:
    """(rows read, names at address 0, names that are undefined), from `readelf --wide --syms`.

    The engine's rule is "address 0 and a listed name" (check_binary.py, iter_elf_symbols): every undefined
    symbol has address 0, and so do some defined ones in an object file. The rule is kept as theirs; the
    undefined ones are counted apart, to tell a real reading from an empty one."""
    rows, at_zero, undefined = 0, set(), set()
    for line in readelf_output.splitlines():
        data = line.split()
        if not (len(data) >= 8 and data[0].endswith(":") and data[0][:-1].isdigit()):
            continue
        rows += 1
        try:
            address = int(data[1], 16)
        except ValueError:
            continue
        name = data[7].split("@", 1)[0]
        if address == 0:
            at_zero.add(name)
        if data[6] == "UND":
            undefined.add(name)
    return rows, at_zero, undefined


def read_library(library: Path, *, run=subprocess.run, which=shutil.which) -> str:
    tool = which("readelf") or which("llvm-readelf")
    if not tool:
        raise CannotCheck("no readelf on this machine (binutils)")
    try:
        result = run([tool, "--wide", "--syms", str(library)], capture_output=True, text=True, timeout=900, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise CannotCheck(f"readelf did not run: {error}") from None
    if result.returncode != 0:
        raise CannotCheck(f"readelf failed on {library.name}: {(result.stderr or '').strip()[:200]}")
    return result.stdout


def check(
    version: str, work: Path, *, engine: dict, run=subprocess.run, which=shutil.which, today: str | None = None, repo: Path = ROOT
) -> dict:
    """The record for a build of `version` under `work`, or CannotCheck, or a record with "result": "failed"."""
    if engine.get("firefox") != version:
        raise CannotCheck(f"engine.json pins Firefox {engine.get('firefox')}, not {version}")
    tree = work / f"firefox-{version}"
    try:
        built_from = (tree / ".nulavio-source-sha256").read_text(encoding="utf-8").strip()
    except OSError:
        raise CannotCheck(f"{tree}: not a source tree this project extracted") from None
    if built_from != engine.get("source_sha256"):
        raise CannotCheck("the source tree is not the release engine.json pins (its digest differs)")
    objdir = tree / "obj-nulavio"
    config_status = objdir / "config.status"
    readable_build(substs(config_status))
    inputs_used = built_with(tree, repo)
    libraries = sorted(objdir.glob("*/release/libgkrust.a"))
    if len(libraries) != 1:
        raise CannotCheck(f"{objdir}: expected one release/libgkrust.a, found {len(libraries)}")
    library = libraries[0]
    # Not older than the tree it was built from. Its age against config.status says nothing: an incremental
    # build writes the configuration again and leaves a library alone that needs no new link (the first real
    # pre-check was refused for that). Run this after a build, as the pre-check does: the build is what makes
    # the library current, and a library left by a build of another kind fails the reading or the list.
    if library.stat().st_mtime < (tree / ".nulavio-source-sha256").stat().st_mtime:
        raise CannotCheck("the Rust library is older than the source tree it sits in: build again")
    functions = listed_functions(tree)
    rows, at_zero, undefined = symbols(read_library(library, run=run, which=which))
    if len(undefined) < MIN_UNDEFINED or not set(CANARIES) & undefined:
        raise CannotCheck(f"the reading looks empty ({rows} symbols, {len(undefined)} undefined names): nothing can be said")
    imported = sorted(set(functions) & at_zero)
    how = (
        f"scripts/build/networking_check.py read libgkrust.a of a build with Rust's own link-time optimisation and no "
        f"cross-language LTO or sanitiser: {rows} symbols, {len(undefined)} undefined names; by the engine's rule "
        + (
            f"it imports {', '.join(imported)}"
            if imported
            else f"it imports none of the engine's {len(functions)} networking functions"
        )
        + "."
    )
    return {
        "comment": COMMENT,
        "firefox": version,
        "source_sha256": built_from,
        "result": "failed" if imported else "passed",
        "checked": today or _dt.datetime.now(_dt.UTC).date().isoformat(),
        "how": how,
        # What was read, so that a reviewer can compare a record with a build of their own, and what decided
        # the build: the pin test and release_manifest.py require these to be the tree's current ones.
        "library_sha256": sha256(library),
        "built_with": inputs_used,
        "imported": imported,
    }


def main(argv: list[str] | None = None, *, run=subprocess.run, which=shutil.which) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the Firefox release that was built (engine.json's)")
    parser.add_argument("--work", type=Path, help="the build directory (default: NULAVIO_BUILD_DIR, else the build cache)")
    parser.add_argument("--write", action="store_true", help="write a passing result to browser/build/networking-check.json")
    parser.add_argument(
        "--inputs", action="store_true", help='print this checkout\'s "built_with" (for a record the maintainer accepts) and stop'
    )
    args = parser.parse_args(argv)
    if args.inputs:
        try:
            print(json.dumps(repository_inputs(ROOT), indent=2))
        except OSError as error:
            print(f"networking-check: the mozconfig, its variant or the patch stack cannot be read ({error})", file=sys.stderr)
            return 2
        return 0
    env = os.environ
    work = args.work or Path(
        env.get("NULAVIO_BUILD_DIR") or Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "nulavio-build"
    )
    try:
        record = check(args.version, work, engine=json.loads(ENGINE.read_text(encoding="utf-8")), run=run, which=which)
    except CannotCheck as error:
        print(f"networking-check: not checked: {error}", file=sys.stderr)
        return 2
    if record["result"] != "passed":
        print(f"networking-check: FAILED: the Rust library imports {', '.join(record['imported'])}", file=sys.stderr)
        print(record["how"], file=sys.stderr)
        return 1
    del record["imported"]
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        RECORD.write_text(text, encoding="utf-8")
        print(f"networking-check: passed; wrote {RECORD.relative_to(ROOT)}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
