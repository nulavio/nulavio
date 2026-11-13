#!/usr/bin/env python3
"""Say why the AI review ended without a result (job "review" of .github/workflows/ai-review.yml).

The action hides what Claude Code writes (the model read the pull request, and what it
wrote is untrusted), so a review that fails at its first call to the model API shows
only "did not return structured_output". This reads the result record Claude Code left
in the action's execution file and prints, as one annotation, the HTTP status of the
API error and Claude Code's own reason for stopping: a number from 100 to 599 and a
word from the lists below. It never prints anything else of the file, which holds what
the model read and wrote.

    python3 -I scripts/ci/ai_review_failure.py "$RUNNER_TEMP/claude-execution-output.json"

Exit status: always 0. The step that failed already failed the job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# What an HTTP status of the model API usually means here. The text is ours, never the API's.
STATUS = {
    400: "the request was refused: a parameter or a model the API does not take, or no credit left on the account",
    401: "the credential was refused: check the ANTHROPIC_API_KEY secret, or the federation rule and service account",
    402: "the account has no credit",
    403: "the credential may not use this model, workspace or organization",
    404: "the model was not found for this credential",
    413: "the request was too large",
    429: "rate limited, or the account's spending limit was reached",
    529: "the model API is overloaded; run the review again",
}
# Claude Code's own words for how a run ended (terminal_reason, then subtype), as documented for
# the pinned version. A word that is not here is printed as "unknown": update the list with the pin.
REASONS = frozenset(
    {
        "completed", "max_turns", "tool_deferred", "aborted_streaming", "aborted_tools", "hook_stopped",
        "stop_hook_prevented", "background_requested", "blocking_limit", "rapid_refill_breaker", "prompt_too_long",
        "image_error", "model_error", "api_error", "malformed_tool_use_exhausted", "budget_exhausted",
        "structured_output_retry_exhausted", "tool_deferred_unavailable", "turn_setup_failed",
        "success", "error_max_turns", "error_during_execution", "error_max_budget_usd",
        "error_max_structured_output_retries",
    }
)  # fmt: skip


def result_record(data: object) -> dict | None:
    """The last top-level record of type "result". The file is the list of the run's messages (or
    that one record); what the model wrote sits deeper, inside other records, and is not looked at."""
    records = data if isinstance(data, list) else [data]
    for record in reversed(records):
        if isinstance(record, dict) and record.get("type") == "result":
            return record
    return None


def word(value: object) -> str:
    return value if isinstance(value, str) and value in REASONS else "unknown"


def explain(data: object) -> str:
    record = result_record(data)
    if record is None:
        return "Claude Code left no result record: it ended without one (see the review step's own error)"
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
    except (OSError, ValueError, RecursionError, MemoryError):
        message = "no readable execution file: Claude Code did not start, or the action failed before or while writing it"
    else:
        message = explain(data)
    print(f"::error title=AI review did not complete::{message}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
