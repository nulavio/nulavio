---
name: nulavio-engine-verification
description: Use to verify a Nulavio change that touches the engine, prefs, policies, profiles, the launcher's engine handling, the Shell or the build, and to report what was and was not verified. Covers the unit and integration suites, running against a Nulavio build, disposable profiles, debugging variables and the one-suite-at-a-time rule.
---

# Verifying a change in the real engine

Unit tests check logic and the repository's rules; only the engine, driven
through Marionette, shows what a user gets. Commands are in
[CONTRIBUTING.md](../../../CONTRIBUTING.md) and
[docs/architecture/build.md](../../../docs/architecture/build.md).

## What to run

| The change touches | Run |
|---|---|
| Anything | `python3 -I tests/run.py unit` (a file: `tests/run.py unit test_shell.py`) |
| Prefs, policies, profiles, the Shell, the window, routing, search | the matching `tests/integration/test_*.py` against a Nulavio build |
| Patches, the engine, the build scripts | a real build (`scripts/build/build_nulavio.sh <version>`), then the integration suite |
| The site | `python3 -I scripts/site/build_site.py` and `tests/run.py unit test_site.py` |

Defaults, guard rules, extensions, search providers and privileged APIs each have
a row in CONTRIBUTING's "Common changes" table: follow it.

## Running the integration tests

- Against a Nulavio build:
  `NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio python3 -I tests/run.py integration [test_x.py]`.
  Without `NULAVIO_ENGINE` it uses the system Firefox (≥ 140, not Snap), and the
  tests that need the build are skipped: a skip is not a pass.
- The harness gives every run a temporary `NULAVIO_HOME`, a throwaway XDG home
  and disposable profiles. Never point a test, a script or the engine at a real
  profile or the real home, and never put real credentials in a test.
- Useful variables: `NULAVIO_TEST_HEADFUL=1` (show the window),
  `NULAVIO_TEST_LANG` (the locale of sessions on a Nulavio build, default
  `pt_BR.UTF-8`; run `en_US.UTF-8` too when strings change),
  `NULAVIO_TEST_ENGINE_LOG=<file>` (engine output; it may contain page console
  output, so never paste it in public), `NULAVIO_TEST_ARTIFACTS=<dir>`.
- One integration suite at a time per machine. Two at once produce Marionette
  timeouts and failed profile creation that are only CPU contention: rerun a
  failure alone before diagnosing it.
- The full build takes long and about 23 GB in `~/.cache/nulavio-build`; it
  needs your own Safe Browsing key. Do not start one when `dev_sync` (see the
  `nulavio-shell-change` skill) or an existing build answers the question, and
  never build in a tree another session is using.

## In CI

The job "does this change need the engine integration run" decides whether the
engine integration jobs run. Their result is not a required check, so whoever
merges reads it. A failure is diagnosed from its log; one shown to be unrelated
and flaky gets an issue (and a fix), not silence.

## Reporting

In the pull request, list each command with its result (tests run, skipped,
failed) and the commit it ran on. Under "Not verified", name what was not run
and why: no build, the system Firefox instead of Nulavio, one locale only, no
real device. Keep local runs, CI and reviews apart; never report a skipped or
unrun check as passing.
