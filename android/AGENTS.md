# android/: Nulavio Companion, the phone that unlocks protected profiles

Read the root [AGENTS.md](../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

- `app/`: the Android app `net.nulavio.companion` (Java, platform UI, minSdk 30, no AndroidX, no Google services).
- `nv1/`: the phone side of the unlock protocol, plain Java; `tests/fixtures/nv1-vectors.json` holds the test vectors shared with the desktop.
- `fdroid/`: the F-Droid recipe as submitted, and its summary. `gradle/verification-metadata.xml`: the SHA-256 of every build input.

## Rules that apply here

- Cryptography only through Tink and Bouncy Castle (I8). Canonical JSON identical, byte for byte, to the desktop's (`launcher/nulavio_launcher/vault/`); a protocol change gets new vectors on both sides and a new `versionCode` and tag.
- An explicit `Locale` in every format or case conversion; no cleartext traffic, `debuggable`, `allowBackup` or world-readable file.
- Every new entry in `gradle/verification-metadata.xml` has a reason, and nothing in CI writes that file (I5). No Google services, trackers or AndroidX (`tests/unit/test_companion_build.py` says why).
- The release APK is reproducible from the `companion-v*` tag; F-Droid builds from those tags, so a tag is never moved.

Documents: [ADR 0005](../docs/adr/0005-phone-profile-unlock.md) (the protocol, key storage and release order), [vault and unlock](../docs/architecture/vault-and-unlock.md), the [unlock threat model](../docs/security/threat-model-unlock.md). A suspected vulnerability: [nulavio-private-security-fix](../.agents/skills/nulavio-private-security-fix/SKILL.md).

## Checks

- `android/gradlew -p android :nv1:test` and `android/gradlew -p android :app:lintDebug :app:assembleRelease`, with JDK 21 (`JAVA_HOME`) and the Android SDK (`ANDROID_HOME`).
- `python3 -I tests/run.py unit` (`test_companion_build.py`, `test_companion_protocol.py`, `test_phone_link.py`).
- On a device: `tests/integration/test_companion_emulator.py`, opt-in, over adb. The emulator may not start on every machine; a real phone is the evidence that counts.

## Not here

The desktop side of the protocol and the profiles it unlocks are in `launcher/`; the browser's pairing pages are in `browser/shell/vault/`; signing the release APK belongs with the other release signing in `scripts/release/` (#205).
