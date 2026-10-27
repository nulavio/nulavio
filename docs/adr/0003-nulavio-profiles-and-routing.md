# ADR 0003 — Nulavio Profiles and Smart Profile Routing

- **Status:** Accepted (2026-10-25). Profiles implemented in Track B (2026-10-26). Routing M4a (links from other apps) and M4b (typed addresses, "Open link in profile") implemented (2026-10-26); temporary profile implemented (2026-10-26); M5 designed.
- **Related:** [ADR 0002](0002-nulavio-search.md), [trust boundaries](../architecture/trust-boundaries.md).

## Context

Firefox 158 ships profile management (`browser.profiles.enabled=true`, `browser/components/profiles/SelectableProfileService.sys.mjs`):
- profiles grouped in a shared store (`Profile Groups/<storeID>.sqlite`), each with a name, avatar and theme colours;
- upstream pages to create, edit and delete profiles, with confirmations;
- `launchInstance(profile, urls)`, which first asks the running instance through the engine's local remote service (`nsIRemoteService.sendCommandLine`) and otherwise starts the binary with an argument list (`nsIProcess.runw`, `--profile <path>`), never a shell.

Verified on the Nulavio build: it works when the current profile is **registered** in `$XDG_CONFIG_HOME/nulavio/nulavio/profiles.ini`. The Track A launcher starts unregistered paths (`--profile <dir>`), so it stays out of this feature.

## Decision

1. **The engine owns profiles in Track B.** Nulavio Profiles is a thin module (`NulavioProfiles.sys.mjs`) in the built-in Shell add-on over `SelectableProfileService`. It adds:
   - **templates**: Personal, Work, Banking, Research; each is a name, avatar and colour, never a mandatory profile;
   - an **always-visible toolbar selector** that shows the current profile's colour and initial;
   - one-click switching (`launchInstance`) and a keyboard shortcut (Alt+Shift+P opens the selector);
   - routing (below).

   Create, edit and delete use the upstream pages, which keep their confirmations and safe deletion: a running profile cannot be deleted.
2. **Full profiles, not containers.** Each profile is a separate engine instance with its own directory, which isolates cookies, storage, history, extensions, credentials and preferences. Containers (contextual identities) only split cookies and storage inside one profile; they share history, extensions and preferences. Both stay available, and the UI never calls a container a profile.
3. **Search and passwords per profile** follow from the profile directory: `search.json`, installed extensions (Proton Pass, KeePassXC-Browser), and `logins.json`.
4. **Temporary profile: offered only with deletion on close implemented and tested** (see [Temporary profile](#temporary-profile-implementation)). It is an action ("New temporary window"), not a template.

## Smart Profile Routing (designed, staged)

Local router, explicit rules only, never inferred.

**Precedence:**
1. The user's explicit choice for this navigation.
2. An exact host rule.
3. A registrable-domain rule. The domain is computed with the engine's Public Suffix List (`Services.eTLD`); subdomains match only when the rule enables them.
4. The workspace or profile policy.
5. Stay in the current profile.

**Rule actions:**
- `open-in <profile>`;
- `ask` (dialog with "remember");
- `never-switch`.

Private windows have a separate policy: the default is never to switch, and rules apply only if enabled for private.

**Normalisation:** lower-case, IDN to punycode (`Services.io.newURI().asciiHost`), trailing dot removed. IP literals match only exact rules.

**Where it runs (staged, safest first):**
- **M4a External links (implemented).** URLs from the desktop handler reach the engine as a command line, through the remote service or at start-up. The router decides **before any network request**. If another profile is the target, the link goes there with the routed flag and nothing opens in the current one. See [M4a implementation](#m4a-implementation).
- **M4b Typed URLs (implemented).** The decision runs on the address-bar submission, before navigation, with the same hand-off. Links clicked inside pages are moved only by an explicit choice: "Open link in profile" in the link's menu. See [M4b implementation](#m4b-implementation).
- **M5 In-page navigation.** Only after a security review: top-level, user-initiated, `GET` navigations to `http(s)` only.

**Never transferred:**
- `POST`, downloads and redirects mid-flight;
- `javascript:`, `data:`, `blob:`, `file:` and internal (`about:`, `moz-extension:`) URLs.

**Failure is conservative.** If a mandatory rule's target cannot start or does not confirm, the URL is **not** opened in the wrong profile. The user sees an error with "open here anyway" as an explicit choice. The original tab is kept until the target confirms. Session cookies or tokens are never moved; a sign-in does not follow the user to another profile.

**No duplicate instances:** the remote service is tried first, and the profile lock decides the race (`launchInstance` behaviour).

## Interfaces

```
browser.nulavioProfiles (experiment API, built-in Shell only; logic in browser/shell/modules/NulavioProfiles.sys.mjs)
  list() -> {available, reason: null|"unregistered"|"disabled", profiles: [{id, name, avatar, color, isCurrent}]}
  options() -> {templates: [{id, avatar, color}], colors, avatars}
  create({name, templateId?, avatar?, color?}) -> id      // not launched
  update(id, {name?, avatar?, color?})
  switchTo(id) -> {action: "current"|"launched"}          // SelectableProfileService.launchInstance
  remove(id)                                              // refuses the current one and running ones (engine lock)
  openManager() ; openCurrentPage("edit"|"delete")        // upstream pages
  avatarSvg(avatar, ink)                                   // the engine's icon for extension pages
  onChanged
Identity colour: pref nulavio.profiles.colors (JSON id -> colour key), tracked by the engine's shared-prefs
store so every profile of the group sees it. Reading never creates the group store.

NulavioRouter.sys.mjs (pure decisions, no state or I/O)
  normalizeHost(urlOrHost) -> {host, registrable, isIP, display}
  validateRule({site, match: "host"|"domain", action: "open-in"|"ask"|"stay", profileId?}) -> {match, value, action, profileId}
  decide({url, rules, enabled, currentProfileId, isPrivate, explicitProfileId})
    -> {action: "stay"|"open-in"|"ask", profileId, ruleId, reason}
  parseCommandLine(args) -> {supported, items: [{start, end, value}]}

NulavioRouting.sys.mjs (rules in shared prefs, command lines, hand-off) and browser.nulavioRouting:
  state() ; setEnabled(bool) ; addRule({site, match, action, profileId?}) ; removeRule(id)
  setRuleAction(id, action) ; ruleFor(url) ; openIn(profileId, url)   // explicit choice
  onChanged
```

Verification: `tests/integration/test_profiles.py` runs a registered profile in a disposable home (`harness.GeckoProfileSession`) and drives the second instance the switch starts: a cookie and `localStorage` set in one profile are absent in the other, a second switch keeps one process, a running profile cannot be deleted, the popup switches with one click, the settings page asks before deleting and the toolbar follows a rename (10/10).

## M4a implementation

- **Hook.** `browser/branding/nulavio/components.conf` registers `NulavioCommandLine.sys.mjs` as the command-line handler `l-nulavio-routing`. Handlers run in alphabetical order, so it runs before the browser opens URLs (`m-browser`, `x-default`), both at start-up and for command lines from the remote service. It is registered at build time from Nulavio's branding directory: no Mozilla file is patched, and it works before the Shell add-on starts.
- **What is routed.** Only plain URL command lines: bare URLs, `-url`, `-new-tab`, `-new-window`, with `http`/`https` after the engine's own URL fixup. A command line with any other flag (`-private-window`, `-search`, `-kiosk`, files...) is left entirely to the browser.
- **Running instance.** The rules in this profile's prefs are current (the engine pushes shared-pref changes to running instances), so the decision is immediate; only the links that move are removed from the command line.
- **Start-up.** The group's rules may be newer in the group store than in this profile, so web links are held until the engine's profile service has loaded them; links that belong here then open in a new tab next to the start page.
- **Hand-off.** `--nulavio-routed -new-tab <url>` through the engine's remote service (D-Bus on Linux), or a new instance started with an argument list. The flag marks an explicit or routed open: the receiving profile never routes it again, so rules cannot loop.
- **Failure.** A missing target profile, a failed start or an internal error opens a local Nulavio page that shows the address as text, loads nothing, and offers "Try again" or "Open in this profile anyway" (the user's explicit choice). "Ask" rules open a local question page, with "Remember for this site".
- **Rules UI.** Settings → Profiles → Smart routing (global switch, rules list with the target profile, add/remove); the toolbar selector offers "Always open <site> in this profile" for the active tab (`activeTab`, only after a click). Nothing creates a rule without one of these actions.
- **Verification.** `tests/integration/test_routing.py`: decision matrix on the engine's PSL and IDN, rule validation, command-line forms, and end-to-end links delivered through the remote service: the link loads once and only in the rule's profile; a running target gets it without a second instance; "ask" loads nothing until the choice; routed and private command lines are not moved; routing off; a deleted target never falls back silently; a link that starts the browser waits for the rules; the rules editor.

## M4b implementation

- **Hook.** Patch 0005 adds one call in `UrlbarParentController.loadURL`, the single parent-side place where every address-bar load starts (`initiatedByURLBar`), to `resource:///modules/nulavio/NulavioUrlbarRouting.sys.mjs` (branding directory). It returns false ("load here") unless a rule moves the address or asks first; then the current tab is left as it is and the address bar reverts. The module catches its own errors: if routing is unavailable, typing still works.
- **Never routed:** POST loads (search engines that POST), `save` (downloads), private windows, non-web schemes, and instances whose profile group is not loaded yet.
- **Link menu.** "Open link in profile" (WebExtension `menus`, `http(s)` links only, hidden in private windows) lists the other profiles; choosing one is an explicit choice, sent with the routed flag, so no rule moves it again. Only the address moves; cookies and sessions stay in each profile.
- **Verification.** `test_routing` 11–14: a typed address with a rule opens once, only in the rule's profile, and this tab does not navigate; "ask" holds it; private, POST, download and internal addresses are not routed; the real link context menu opens a link in the chosen profile.

## Temporary profile implementation

A new, empty engine profile in its own instance, deleted when that instance exits.

- **Where.** `$XDG_RUNTIME_DIR/nulavio/temporary/tmp-<random>/` (0700). On systemd desktops that is a per-user tmpfs: the profile is kept in memory and also disappears at logout or reboot. The runtime directory is used only if it is the user's own and private; otherwise the profile goes to the cache directory on disk. The marker file records which case applies (`/proc/self/mountinfo`) and whether a swap area on disk is active (`/proc/swaps`; zram is memory); the UI says "kept in memory only" only when both hold.
- **Who deletes it.** The Nulavio tools (`launcher/nulavio_launcher/temporary.py`), never the browser. They create the folder and take an exclusive `flock` on its guard file; the holder deletes it: the supervising `nulavio run --temporary`, or, when the browser opens one ("New temporary window" in the selector or in Settings → Profiles), a detached watcher that inherits the lock, waits for the engine to take the profile (2 minutes at most) and then for it to exit. A folder with a free guard lock and no engine is an orphan (its watcher was killed) and is deleted the next time a temporary profile is created, or with `nulavio temporary clean`. Deletion is limited to marked folders directly under the temporary root, never through a symlink (`shutil.rmtree`'s fd-based version).
- **What it is.** Not part of the profile group, so no switching or routing from it (rules neither move pages into nor out of it). The engine's own defaults and policies apply (the Nulavio build installs uBlock Origin by policy; the launcher installs the pinned copy for distribution Firefox). Prefs that follow from "deleted on close": downloads stay out of the desktop's recent files, the password manager does not offer to save (a saved password would be deleted), no crash restore, no "what's new" page. Nothing that protects the user is changed.
- **Identity.** A dashed ring with "T" on the toolbar button and in Shell pages, the tooltip "Temporary profile (deleted on close)", and a bar in every window: "Temporary profile: nothing here is kept." plus where it is kept.
- **Verification.** `tests/unit/test_temporary.py` (16: storage detection, private runtime directory, marker and prefs, guard lock, orphans, refusals, the real watcher); `tests/integration/test_temporary.py` (4, real engine): the selector starts an ordinary instance (no automation flags) whose folder is deleted after it exits; inside it the identity, the storage note, no switching or routing, and the prefs; Settings offers it; `nulavio run --temporary` deletes the profile after the engine exits and even a dry run leaves nothing. A probe of the disposable home after a temporary session (cookies and site storage written) found no new or changed file outside the deleted folder except the launcher's log ("created", "deleted"; no addresses).
- **Limits** ([R37](../security/residual-risks.md)): files saved to Downloads and data kept by other apps (password managers through native messaging, the clipboard) are not part of the profile; memory may be written to a swap area on disk; a crash leaves the folder until the next temporary profile, logout or reboot.

## Risks

| Risk | Mitigation |
|---|---|
| Upstream profile management changes (it is new) | Thin module; integration tests use the real service in an isolated home |
| Track A and Track B profile models differ | Documented: Track A keeps launcher profiles (CLI); Track B uses engine profiles |
| A user thinks a switch keeps them signed in | UI copy: "Each profile has its own sessions; you will sign in again" |
| Routing loops (A sends to B, B rule sends back) | The decision carries `source`; a routed open is always treated as an explicit choice in the target |
| Leaking which sites a user visits through rules | Rules stay local (profile group store or prefs) and are never logged with URLs |
| An explicit `-P <profile>` on a command line cannot be told apart from a link (the engine consumes it before handlers run) | Routing applies; turn routing off or use "Never switch" for that site. In-browser explicit choices carry the routed flag |
| A link that starts the browser opens next to the start page when it stays | Documented ([R22](../security/residual-risks.md)); the alternative (reading the group database synchronously at start-up) was rejected |
| A user expects a temporary profile to leave no trace anywhere | The UI says where it is kept and that only the profile is deleted; [R37](../security/residual-risks.md) lists what stays outside it |
| Upstream behaviours on the first extra profile: the current one becomes "Original profile" and a chooser appears at start-up | Kept as upstream does; renaming is one click in Nulavio settings ([R18](../security/residual-risks.md)) |
