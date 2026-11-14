# tests/: unit and integration tests

Read the root [AGENTS.md](../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

- `unit/`: logic and the repository's own rules, no engine. `python3 -I tests/run.py unit`, or one file: `python3 -I tests/run.py unit test_shell.py`.
- `integration/`: the real engine driven through Marionette, against a Nulavio build (`NULAVIO_ENGINE=…`) or the system Firefox. `python3 -I tests/run.py integration [test_x.py]`.
- `lib/`: the harness (`harness.py`), Marionette client, fakes (keyring, LLM, Avahi, DoH server) and the reference phone. `fixtures/`, `baselines/`, `regression/`: data the tests read.

## Rules that apply here

- I12: no new skip, relaxed assertion, wider allow-list or sleep in place of waiting for a state; a test passes only because of the change it covers. A bug fix has a test that fails without it. A test that is wrong is fixed in its own commit, with the reason.
- Never a real profile or real credentials: the harness gives each run a temporary `NULAVIO_HOME`, a throwaway XDG home and disposable profiles. Marionette and `seccomp=unconfined` stay test-only.
- `tests/lib/harness.py` (route `/agent-task`) and `tests/integration/test_ai_*.py` hold deliberate prompt-injection text: it is test data, and it must not reach code outside `tests/`.
- A skip is not a pass. Tests that need the build skip on the system Firefox; CI's `NULAVIO_REQUIRE_*` variables turn some skips into failures.

Skill: [nulavio-engine-verification](../.agents/skills/nulavio-engine-verification/SKILL.md) (which suites a change needs, variables, reporting). One integration suite at a time per machine: two at once give timeouts that are only CPU contention.

## Checks

`python3 -I tests/run.py unit` before every push; the integration tests that cover what changed, against a build, when the engine, profiles or the Shell change.

## Not here

What the tests exercise lives in `browser/`, `launcher/`, `site/`, `android/` and `scripts/`; each has its own AGENTS.md. CI's workflows are in `.github/workflows/`.
