<!--
Title: a conventional commit, for example "fix(launcher): refuse symlinked profile directories".
It becomes the squash-merge commit. Process: docs/process/pull-requests.md.
-->

## What changed

## Why

## How it was verified

<!-- Commands and their results, for example: python3 -I tests/run.py unit -> OK (N tests). -->

## Not verified

<!-- What you could not run or check (engine build, real device, network, runtime behaviour). "Nothing" needs a reason. -->

## Status

- [ ] Implemented (tested)
- [ ] Prototype (works, not hardened or not fully tested)
- [ ] Planned (docs only)

## Security

- Security-relevant: yes / no
- Invariants touched (definitions in `.github/ai-review/instructions.md`; tick each one the change affects and say how it still holds):
  - [ ] I1 protections (sandbox, Fission, TLS, signatures, Safe Browsing, Remote Settings, updates, downgrade)
  - [ ] I2 no telemetry, no Nulavio-operated remote service
  - [ ] I3 secrets only on stdin or in 0600 files
  - [ ] I4 processes started with argument lists
  - [ ] I5 every external input pinned by version and hash or signature
  - [ ] I6 patch policy
  - [ ] I7 AI Bridge least privilege
  - [ ] I8 vault cryptography only through the vetted libraries
  - [ ] I9 file modes, paths and launcher flags
  - [ ] I10 Shell input validation and theme rules
  - [ ] I11 honest docs (trust boundaries, threat model, residual risks)
  - [ ] I12 tests and CI not weakened

## Checklist

- [ ] Conventional commits, signed off (`git commit -s`)
- [ ] `ruff check .`, `ruff format --check .` and `python3 -I tests/run.py unit` pass locally
- [ ] Integration tests run where the change touches the engine, profiles or the Shell (or listed under "Not verified")
- [ ] Docs updated where behaviour changed
- [ ] Opened by an agent: name the tool below; the agent does not merge

<!-- Agent: tool and model, if any. The advisory AI review comment, if one appears, is not an approval. -->
