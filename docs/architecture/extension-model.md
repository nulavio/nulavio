# Extension model

## Classes of extensions

| Class | Examples | Who installs | Source | Updates |
|---|---|---|---|---|
| Default (product) | uBlock Origin | Nulavio setup, disclosed in the plan the user confirms (`--no-ublock` opts out) | Pinned AMO file: SHA-256, size, host allow-list, plus Mozilla signature | Engine auto-update from AMO |
| Provider | Proton Pass, KeePassXC-Browser, Bitwarden | The user, explicitly (`--install-extension` or AMO) | Pinned AMO file (via Nulavio) or AMO directly | Engine auto-update from AMO |
| User | Anything from AMO | The user | AMO | Engine |
| Built-in (Track B) | Nulavio new tab, onboarding, privacy panel | Shipped inside the build | Part of the signed release | With the browser |

No extension is installed silently: everything Nulavio adds is listed in the setup plan or requires an explicit command.

## Facts verified on Firefox 158

- Only Mozilla-signed extensions load on release builds (`xpinstall.signatures.required` cannot be relaxed there; Guard blocks attempts in user prefs).
- A signed XPI placed at `<profile>/extensions/<id>.xpi` is handled per engine build. **Fedora's package** (`extensions.autoDisableScopes=0`) enables it at next start without a prompt. **Mozilla's own builds** (default 15, also Nulavio Track B) keep it disabled until the user approves it from the ☰ menu; the start page and `nulavio doctor` show "waiting for your approval". Nulavio never lowers the value, and Guard warns if a user pref does. On Fedora this is also a same-user tampering vector (residual risk R2).
- Language packs from the distribution (`/usr/lib64/firefox/langpacks/`) are Mozilla-signed. Nulavio copies the one matching the user's locale into the profile and refreshes it when the engine updates.
- Extensions do not run in private windows unless the user allows them per extension. For uBO, the user enables "Run in Private Windows" in Add-ons. Track B will set `private_browsing: true` for uBO via policy, disclosed at setup.
- The Marionette remote agent changes many prefs ("recommended prefs") unless `remote.prefs.recommended=false`. Tests set it to false so they exercise the real configuration.

## Permission review

- `extensions.lock.json` keeps the permissions a maintainer reviewed (`reviewed_permissions`). `scripts/upstream/refresh_extensions_lock.py` flags additions before the lock can change.
- Planned (Guard runtime): show high-risk permissions (`<all_urls>`, `cookies`, `webRequestBlocking`, `nativeMessaging`, `clipboardRead`, `privacy`) in plain language at install, and alert when the installed set changes outside the browser UI.

## Track B mechanics (planned)

- `distribution/policies.json` → `ExtensionSettings`: uBO `normal_installed` (user can disable; not removable while the policy stands) with `private_browsing: true`. Everything else `allowed`. No `force_installed` for user-facing extensions.
- Built-in Nulavio UI as a built-in add-on (no AMO signing needed). The new tab overrides `about:newtab`.
- Keep Firefox's add-on application ID so AMO extensions remain compatible (legal/policy check pending, ADR open item 3).
