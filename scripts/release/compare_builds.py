#!/usr/bin/env python3
"""Compare two portable archives of the same commit, built separately: are they the same bytes?

    python3 -I scripts/release/compare_builds.py <first.tar.xz> <second.tar.xz>
        [--summary FILE] [--extract DIR] [--limit N]

Exit 0 when the archives are identical. Otherwise exit 1 and list, per entry, what differs
(content, mode, link target, entries only in one), in Markdown for the job summary; with
--extract, the first N differing files of each build are written to DIR/first and
DIR/second for diffoscope. OpenSSF Best Practices `build_repeatable`;
.github/workflows/repeatable.yml runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
from pathlib import Path, PurePosixPath


def entries(path: Path) -> dict[str, tuple]:
    found = {}
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            digest = ""
            if member.isfile():
                digest = hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest()
            found[member.name] = (member.type, oct(member.mode), member.linkname, digest, member.mtime, member.uid)
    return found


def safe_name(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts) and not PurePosixPath(name).is_absolute() and ".." not in parts


def extract(path: Path, names: list[str], dest: Path) -> None:
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            if member.name in names and member.isfile() and safe_name(member.name):
                target = dest / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--extract", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    if args.first.read_bytes() == args.second.read_bytes():
        report = f"Identical: both builds give the same archive ({args.first.stat().st_size} bytes).\n"
        status = 0
    else:
        a, b = entries(args.first), entries(args.second)
        only_a, only_b = sorted(a.keys() - b.keys()), sorted(b.keys() - a.keys())
        changed = sorted(name for name in a.keys() & b.keys() if a[name] != b[name])
        content = [name for name in changed if a[name][3] != b[name][3]]
        lines = [f"Different: {len(changed)} entries differ ({len(content)} in content), "
                 f"{len(only_a)} only in the first, {len(only_b)} only in the second.", ""]  # fmt: skip
        fields = ("type", "mode", "link", "content", "mtime", "owner")
        for name in changed[:200]:
            what = ", ".join(field for field, x, y in zip(fields, a[name], b[name], strict=True) if x != y)
            lines.append(f"- `{name}`: {what}")
        lines += [f"- only in the first: `{name}`" for name in only_a[:50]]
        lines += [f"- only in the second: `{name}`" for name in only_b[:50]]
        report = "\n".join(lines) + "\n"
        status = 1
        if args.extract:
            sample = content[: args.limit]
            extract(args.first, sample, args.extract / "first")
            extract(args.second, sample, args.extract / "second")
    print(report, end="")
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write("## Repeatable build\n\n" + report)
    return status


if __name__ == "__main__":
    sys.exit(main())
