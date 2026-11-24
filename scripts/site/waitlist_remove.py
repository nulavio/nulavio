#!/usr/bin/env python3
"""Remove one address from the waitlist of nulavio.net by hand (CONTRIBUTING, "Website").

    python3 -I scripts/site/waitlist_remove.py [--database nulavio-waitlist] [--dry-run] [--yes]

For someone who lost their link, signed up before links existed or whose address someone else
signed up, once a reply has come back from the address on the list. The address is read from
standard input (typed at the prompt, or one line piped in), never from the command line: it was
typed by someone on the internet, and a command line is read by a shell first. It is shown back
with every character spelled out before anything is removed.

The two DELETE statements quote the address by SQLite's own rule (a quote is doubled), and the
address must hold no control character, so its text never ends a string literal. They are passed
to wrangler as one argument of an argument list, with no shell in between. The comparison is the
column's (COLLATE NOCASE), as in site/_worker.js, so A@b.example removes a@b.example.

Any address that may be on the list is accepted, also one with characters the worker refuses
today: entries made before it narrowed the addresses it takes can still have them.

Exit status: wrangler's, or 2 when the address is refused or the removal is not confirmed.
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


def refused(address: str) -> str | None:
    """Why this address cannot be removed this way, or None."""
    if not address:
        return "no address"
    if len(address) > MAX_LENGTH:
        return f"longer than {MAX_LENGTH} characters, so it is not on the list"
    if any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 or 0xD800 <= ord(c) < 0xE000 for c in address):
        return "it holds a control character"
    if "@" not in address:
        return "it has no @"
    return None


def literal(text: str) -> str:
    """An SQLite string literal for text: a quote inside is doubled, and nothing else is special."""
    return "'" + text.replace("'", "''") + "'"


def statements(address: str) -> str:
    """The SQL that removes the entry and its link's hash. Raises ValueError for a refused address."""
    reason = refused(address)
    if reason:
        raise ValueError(reason)
    # wrangler's --command takes no bound parameters: literal() is the quoting, tested on every ASCII character.
    where = f"WHERE email = {literal(address)}"
    return f"DELETE FROM waitlist {where}; DELETE FROM waitlist_links {where}"  # noqa: S608 - quoted by literal()


def command(address: str, database: str = DATABASE) -> list[str]:
    """The wrangler command, as an argument list."""
    return ["wrangler", "d1", "execute", database, "--remote", "--command", statements(address)]


def run_wrangler(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False).returncode


def main(
    argv: Sequence[str] | None = None,
    read: Callable[[str], str] = input,
    run: Run = run_wrangler,
    out=sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", default=DATABASE, help=f"the D1 database (default {DATABASE})")
    parser.add_argument("--dry-run", action="store_true", help="show the command and remove nothing")
    parser.add_argument("--yes", action="store_true", help="do not ask before removing")
    args = parser.parse_args(argv)  # no positional argument: the address never comes from the command line

    try:
        address = read("Address on the list (as it was replied from): ").strip()
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
        try:
            answer = read("Remove it from the list? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Nothing removed.", file=out)
            return 2
    return run(argv_out)


if __name__ == "__main__":
    sys.exit(main())
