# Fingerprinting: what the Nulavio build changes, measured

Phase 3 asks for a fingerprinting regression analysis. This is it for the Nulavio build (Firefox 158.0.1): what the engine's protections do in the tracking-protection category Nulavio uses (Strict), measured on the real engine, and what they do not do.

## Method

`tests/integration/test_privacy.py` (`test_04`) loads a probe page (`/fp-probe` in `tests/lib/harness.py`) in an engine profile of the Nulavio build twice in one session: once in Strict (Nulavio's default), once after switching the category to Standard (the engine's default). The page reads what any script can read: `navigator.hardwareConcurrency`, `navigator.maxTouchPoints`, whether `screen.avail*` equals `screen.*`, the time zone, and a SHA-256 of a canvas readback (gradient and text) taken twice. The run writes `tests/artifacts/privacy/fingerprinting.json`; the assertions hold on every run.

## What Strict turns on

The Strict feature list (`browser.contentblocking.features.strict` in `browser/app/profile/firefox.js`) includes `fp` (block scripts on the known-fingerprinters list, from Remote Settings) and `fpp` (`privacy.fingerprintingProtection`, the engine's fingerprinting protection in normal windows; Standard keeps it for private windows only). With `fpp`, the default targets of `nsRFPService` apply (`toolkit/components/resistfingerprinting/RFPTargetsDefault.inc`): canvas randomization, tiered hardware concurrency, screen "available" area reported as the full screen, collapsed touch points, constant WebGL vendor and renderer strings, font visibility limited to the language pack, fdlibm math.

## Results (Nulavio build, reference laptop, 2026-10-26)

Measured on the reference laptop (16 logical processors, headless engine, probe page served from 127.0.0.1):

| Reading | Strict (Nulavio) | Standard (engine default) |
|---|---|---|
| `navigator.hardwareConcurrency` | **8** (tiered) | 16 (the real count) |
| `navigator.maxTouchPoints` | 0 | 0 |
| `screen.avail*` equals `screen.*` | yes | yes (headless: no panels) |
| Canvas, raw pixels (`getImageData`) | unchanged | baseline |
| Canvas, exported image (`toDataURL`) | unchanged on this page | baseline |
| Time zone | America/Sao_Paulo | America/Sao_Paulo |

What this shows: `fpp` is in effect in Strict (the processor count is tiered) and was not in effect in normal windows before S14. Canvas randomization is among the engine's default targets, but **no canvas noise was observed** on this first-party, local probe page in either category; the engine may apply it in contexts this probe does not reproduce (third-party frames, remote origins, remote override lists). Nulavio therefore does not claim canvas randomization. Readings were stable within a session in both categories.

## What this does not do

- It is not `privacy.resistFingerprinting` (RFP). Nulavio does not turn RFP on: it changes time zones, window sizes and many sites ([hardening](../security/hardening.md), "Deliberately not changed"). Users who need RFP-level uniformity should use Tor Browser.
- The time zone, languages, installed extensions' side effects, window size and the IP address still differ between users. Strict reduces entropy; it does not make users identical.
- Known-fingerprinter blocking depends on Mozilla's lists (Remote Settings), which Nulavio keeps on.

## Regression guard

`test_privacy` fails if the build stops applying Strict (the bug fixed in S14: the category came only as a `distribution.ini` default, so normal windows had neither `fpp` nor tracking-content blocking), if the processor count stops being tiered in Strict, or if canvas readings become unstable within a session (which would break sites that read a canvas twice).
