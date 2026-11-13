#!/usr/bin/env python3
"""Say why the AI review ended without a result (job "review" of .github/workflows/ai-review.yml).

The action hides Claude Code's output (the model read the pull request, and what it
wrote is untrusted), so a review that fails at its first call to the model API shows
only "did not return structured_output". This reads the result record Claude Code left
in the action's execution file and prints, as one annotation, the HTTP status of the
API error and Claude Code's own reason for stopping: a number and a word from a fixed
list. It never prints the record's text, which can be the model's.

    python3 -I scripts/ci/ai_review_failure.py "$RUNNER_TEMP/claude-execution-output.json"

Exit status: always 0. The step that failed already failed the job.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# What an HTTP status of the model API usually means here. The text is ours, never the API's.
STATUS = {
    400: "the request was refused: often no credit left on the account, or a model the account does not have",
    401: "the credential was refused: check the ANTHROPIC_API_KEY secret, or the federation rule and service account",
    402: "the account has no credit",
    403: "the credential may not use this model, workspace or organization",
    404: "the model was not found for this credential",
    413: "the request was too large",
    429: "rate limited, or the account's spending limit was reached",
    529: "the model API is overloaded; run the review again",
}
WORD = re.compile(r"[a-z][a-z0-9_]{0,39}")


def result_record(data: object) -> dict | None:
    """The last record of type "result": the file is the list of messages, or that one record."""
    records = data if isinstance(data, list) else [data]
    for record in reversed(records):
        if isinstance(record, dict) and record.get("type") == "result":
            return record
    return None


def word(value: object) -> str:
    """A reason as Claude Code names it (api_error, max_turns, …), or "unknown": never free text."""
    return value if isinstance(value, str) and WORD.fullmatch(value) else "unknown"


def explain(data: object) -> str:
    record = result_record(data)
    if record is None:
        return "Claude Code left no result record: it stopped before its first turn (see the step's own error above)"
    status = record.get("api_error_status")
    reason = word(record.get("terminal_reason") or record.get("subtype"))
    turns = record.get("num_turns")
    turns = turns if isinstance(turns, int) and not isinstance(turns, bool) and 0 <= turns < 10_000 else "?"
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        meaning = STATUS.get(
            status, "the model API failed; run the review again" if status >= 500 else "the model API refused the request"
        )
        return f"the model API answered HTTP {status} ({meaning}); Claude Code stopped with {reason} after {turns} turn(s)"
    return f"Claude Code stopped with {reason} after {turns} turn(s) and returned no result"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ai_review_failure.py <execution file>", file=sys.stderr)
        return 0
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        message = "no execution file to read: Claude Code did not start, or the action failed before it (see the step above)"
    else:
        message = explain(data)
    print(f"::error title=AI review did not complete::{message}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
