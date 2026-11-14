#!/usr/bin/env python3
"""Why the AI review ended without a result, in words of our own (scripts/ci/ai_review_api.py).

A model API error is shown as its HTTP status and what that status usually means here, and for a
refusal (4xx) which of a few known causes the API's message names, as a line of our own from
REFUSALS. The API's message itself is never printed: the review reads untrusted pull request text,
and the line goes to a public job log.
"""

from __future__ import annotations

# What an HTTP status of the model API usually means here. The text is ours, never the API's.
STATUS = {
    400: "the request was refused: a parameter or a model the API does not take, or no credit left on the account",
    401: "the credential was refused: check the ANTHROPIC_API_KEY secret",
    402: "the account has no credit",
    403: "the credential may not use this model, workspace or organization",
    404: "the model was not found for this credential",
    413: "the request was too large",
    429: "rate limited, or the account's spending limit was reached",
    529: "the model API is overloaded; run the review again",
}
# What the API's error message says, for the refusals an HTTP status alone does not tell apart (a
# 400 is a refused parameter as well as an empty account). Only these fixed phrases from the API's
# documented error messages are searched for; what is printed is the text on the right, never the message.
CHECK_REQUEST = "check the model and the request in scripts/ci/ai_review_api.py against the API"
REFUSALS = (
    ("credit balance is too low", "the organization's credit balance is too low: add credit (Claude Console, Plans & Billing)"),
    ("usage limit", "a spending limit was reached: raise the workspace's or organization's limit, or wait for its reset"),
    ("extra inputs are not permitted", f"a parameter was refused: {CHECK_REQUEST}"),
    ("does not support", f"the model does not take a parameter the review sends: {CHECK_REQUEST}"),
    ("not supported", f"the model does not take a parameter the review sends: {CHECK_REQUEST}"),
)


def known_refusal(message: object) -> str | None:
    """Which of REFUSALS the API's message names, as our own line; never the message itself."""
    if not isinstance(message, str):
        return None
    message = " ".join(message[:4000].lower().split())
    return next((meaning for phrase, meaning in REFUSALS if phrase in message), None)


def api_error_line(status: object, message: object = None) -> str:
    """One line for an HTTP error of the model API: the status and our meaning of it."""
    if not (isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599):
        return "the model API answered with an unknown status"
    meaning = (known_refusal(message) if 400 <= status < 500 else None) or STATUS.get(
        status, "the model API failed; run the review again" if status >= 500 else "the model API refused the request"
    )
    return f"the model API answered HTTP {status} ({meaning})"
