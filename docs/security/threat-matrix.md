# Threat matrix

At-a-glance view of [threat-model.md](threat-model.md). Ratings use likelihood (L) and impact (I) on a 1–3 scale; residual risk is after controls marked **Now**.

| ID | Scenario | Adversary | L | I | Controls now (Track A, verified) | Next controls | Evidence / tests | Residual |
|---|---|---|---|---|---|---|---|---|
| S1 | Malicious page | T-WEB | 3 | 2 | Fission, sandbox, ETP Strict, uBO, HTTPS-Only | Per-site dashboard | `test_03`, `test_04`, `test_08` | Medium |
| S2 | Malicious/compromised extension | T-EXT, T-SUPPLY | 2 | 3 | Signature required, 1 pinned default ext, blocklist on, doctor inventory | Permission review UI, new-extension alert | lock unit tests | Medium-high |
| S3 | Over-privileged extension | — | 2 | 2 | Reviewed permissions in lock, diff on refresh | Host-permission explainer | lock refresh | Medium |
| S4 | Compromised renderer | T-WEB | 2 | 2 | seccomp + userns + Fission, env stripping | Release SLA (B) | `test_04`, env unit test | Medium |
| S5 | Sandbox escape | T-WEB | 1 | 3 | Upstream sandbox, SELinux host | Evaluate outer confinement | — | Low L / critical I |
| S6 | Phishing / lookalike | T-WEB | 3 | 3 | Safe Browsing on, provider origin matching | Suspicious-login interstitial, passkeys | guard rule | Medium-high |
| S7 | Malicious download | T-WEB | 2 | 3 | No auto-open, SB downloads, 0600 files | Executable warning flow | `test_07` | Medium |
| S8 | Cookie/session leak | T-WEB, T-NET, T-LOCAL | 2 | 3 | TCP, ETP Strict, HTTPS-Only, 0700 profile | Clear-on-close, containers | `test_03`, `test_06`, `test_09` | High vs T-LOCAL |
| S9 | Autofill exfiltration | T-WEB, T-EXT | 2 | 3 | Single provider, engine fill off for external providers | Gesture-required fill, certification | provider unit tests | Medium |
| S10 | Native host compromised | T-LOCAL, T-SUPPLY | 1 | 3 | doctor manifest checks, allowed IDs | Package-ownership warning | doctor | High vs T-LOCAL |
| S11 | Same-user infostealer | T-LOCAL | 2 | 3 | Guard, doctor, data minimisation guidance | Integrity manifest, ext-change alert | guard tests | **High (out of prevention scope)** |
| S12 | Root malware | T-ROOT | 1 | 3 | — | — | — | **Accepted** |
| S13 | Dependency supply chain | T-SUPPLY | 1 | 3 | Stdlib-only launcher, SHA-256 pins, pinned Mozilla key, SBOM, SHA-pinned CI actions | Hermetic builds, provenance | integrity tests, `verify_firefox_release.py` | Medium |
| S14 | Update/package attack | T-SUPPLY, T-NET | 1 | 3 | Distro-signed engine, AMO signing, downgrade protection kept | Signed RPM repo (B) | env unit test | Low-medium |
| S15 | 3rd-party ext steals creds | T-EXT | 2 | 3 | doctor inventory | Sensitive-sites container | — | Medium-high |
| S16 | Cross-origin redirects | T-WEB | 2 | 2 | Default referrer policy, HTTPS-Only, query stripping | Redirect provenance on login pages | `test_06` | Medium |

## Web threats vs. host threats

| | Web threats (S1–S4, S6, S7, S9, S15, S16) | Host threats (S10, S11, S12) |
|---|---|---|
| What Nulavio can do | Prevent, contain and warn | Minimise data at rest, detect cheap tampering, guide the user |
| What Nulavio cannot do | Guarantee absence of engine zero-days | Stop same-user or root malware from reading files, memory or IPC |
| Main lever | Upstream sandbox + patch latency + defaults | Host hygiene, external vault that locks, short sessions |
