#!/usr/bin/env python3
"""Remove one address from the waitlist of nulavio.net by hand (CONTRIBUTING, "Website").

    python3 -I scripts/site/waitlist_remove.py [--database nulavio-waitlist] [--dry-run] [--yes]

For someone who lost their link, signed up before links existed or whose address someone else
signed up, once a reply has come back from the address on the list. The address is read from
standard input, never from the command line: it was typed by someone on the internet, and a
command line is read by a shell first. Type or paste it at the prompt; without a terminal, give it
as a file (`< address.txt`), never through `echo` or `printf`, which put it back on a shell line.
It is shown back with every character spelled out before anything is removed.

The address is in the two DELETE statements only as the hexadecimal of its UTF-8 bytes
(CAST(X'…' AS TEXT)), so the text of the SQL holds none of its characters. The statements are
passed to wrangler as one argument of an argument list, with no shell in between. The comparison
is the column's (COLLATE NOCASE), as in site/_worker.js, so A@b.example removes a@b.example. That
comparison stops at a NUL character, so an address holding one is also matched byte for byte.

Any address that may be on the list is accepted, also one with characters the worker refuses
today, control characters included: entries made before it narrowed the addresses it takes can
hold any character but whitespace and @. Only what the worker never stored is refused: whitespace
(it is trimmed at both ends, as the worker trims it), no @, more than 254 characters. Paste one
line only: anything typed ahead of the question is dropped before it is asked.

wrangler prints how many rows the statements changed: none means the address was not on the list.

Exit status: wrangler's, or 2 when the address is refused, the removal is not confirmed or
wrangler is not installed.
Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence

DATABASE = "nulavio-waitlist"
MAX_LENGTH = 254  # what site/_worker.js accepts

Run = Callable[[Sequence[str]], int]


# What the worker trims and what its address pattern never took (JavaScript's \s; U+FEFF is the
# byte order mark a file can start with). Not str.isspace(), which also holds U+001C-U+001F and
# U+0085: an older entry can hold those.
WHITESPACE = "\t\n\v\f\r \u00a0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u2028\u2029\u202f\u205f\u3000\ufeff"


def refused(address: str) -> str | None:
    """Why this address cannot be on the list, or None. Control characters are not a reason."""
    if not address:
        return "no address"
    if len(address) > MAX_LENGTH:  # the worker counts UTF-16 units, never fewer than these
        return f"longer than {MAX_LENGTH} characters, so it is not on the list"
    if any(c in WHITESPACE for c in address):
        return "it holds whitespace, so it is not on the list"
    if any(0xD800 <= ord(c) < 0xE000 for c in address):
        return "it is not valid UTF-8"
    if "@" not in address:
        return "it has no @"
    return None


def literal(text: str) -> str:
    """An SQLite expression for text that holds none of its characters: a blob literal of its UTF-8 bytes, as TEXT."""
    return f"CAST(X'{text.encode('utf-8').hex()}' AS TEXT)"


def statements(address: str) -> str:
    """The SQL that removes the entry and its link's hash. Raises ValueError for a refused address."""
    reason = refused(address)
    if reason:
        raise ValueError(reason)
    # wrangler's --command takes no bound parameters: literal() is hexadecimal digits only.
    where = f"WHERE email = {literal(address)}"
    if "\0" in address:  # NOCASE stops at a NUL: the bytes after it have to match too
        where += f" AND hex(email) = '{address.encode('utf-8').hex().upper()}'"
    return f"DELETE FROM waitlist {where}; DELETE FROM waitlist_links {where}"  # noqa: S608 - hex digits only


def command(address: str, database: str = DATABASE) -> list[str]:
    """The wrangler command, as an argument list."""
    return ["wrangler", "d1", "execute", database, "--remote", "--command", statements(address)]


def run_wrangler(argv: Sequence[str]) -> int:
    try:
        return subprocess.run(list(argv), check=False).returncode
    except FileNotFoundError:
        print(f"{argv[0]} was not found: install it (ci/site/package-lock.json pins the version) and run this again.")
        return 2


def drop_typeahead() -> None:
    """Drop what a paste left at the terminal after the address, so that it cannot answer the question."""
    try:
        import termios

        if sys.stdin.isatty():
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, OSError, ValueError):
        pass


def main(
    argv: Sequence[str] | None = None,
    read: Callable[[str], str] = input,
    run: Run = run_wrangler,
    out=sys.stdout,
    before_asking: Callable[[], None] = drop_typeahead,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", default=DATABASE, help=f"the D1 database (default {DATABASE})")
    parser.add_argument("--dry-run", action="store_true", help="show the command and remove nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask before removing")
    args = parser.parse_args(argv)  # no positional argument: the address never comes from the command line

    try:
        address = read("Address on the list (as it was replied from): ").strip(WHITESPACE)
    except EOFError:
        address = ""
    try:
        argv_out = command(address, args.database)
    except ValueError as error:
        print(f"Refused: {error}.", file=out)
        return 2
    # ascii(): every character spelled out, so a look-alike or an invisible one shows.
    print(f"Address: {address!a}", file=out)
    print(f"Runs: {argv_out!a}", file=out)
    if args.dry_run:
        return 0
    if not args.yes:
        before_asking()
        try:
            answer = read("Remove it from the list? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing removed.", file=out)
            return 2
    print("wrangler says how many rows changed: none means the address was not on the list.", file=out)
    return run(argv_out)


if __name__ == "__main__":
    sys.exit(main())
