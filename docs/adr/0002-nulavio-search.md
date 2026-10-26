# ADR 0002 — Nulavio Search

- **Status:** Accepted (2026-10-25). Implemented in Track B (2026-10-26); Track A gets the seed prefs.
- **Deciders:** maintainer, with the assistant as tech lead.
- **Related:** [ADR 0001](0001-engine-selection.md), [trust boundaries](../architecture/trust-boundaries.md), [design system](../design/design-system.md).

## Context

Firefox 158's address bar sends what you type to the default engine (remote suggestions, `browser.search.suggest.enabled=true`) and fetches trending searches on focus (`browser.urlbar.trending.featureGate=true`). The default engine for pt-BR is Google. Found and recorded during the Shell audit ([migration plan](../design/migration-plan.md#decisions-for-the-maintainer)); the maintainer asked for search that favours privacy, is transparent, and is configured per profile.

The engine's Search Service (`moz-src:///toolkit/components/search/SearchService.sys.mjs`) already provides everything else:
- user engines: `addUserEngine({name, url, alias, suggestUrl})`, with `{searchTerms}` templates;
- OpenSearch descriptions: `addOpenSearchEngine(url)`;
- removal: `removeEngine(engine)`, which hides app-provided engines;
- separate normal and private defaults: `setDefault`, `setDefaultPrivate`;
- aliases resolved locally by the address bar, so `@ddg term` goes straight to the engine;
- settings stored in each profile's `search.json.mozlz4`, so search is **per profile by construction**.

## Decision

1. **Reuse the Search Service; add no search back end.** Nulavio adds a thin, privileged module, `NulavioSearch.sys.mjs`, inside the built-in Shell add-on. The Shell's settings page reaches it through the experiment API `browser.nulavioSearch`. No Nulavio proxy, no ranking, no ads, no telemetry.
2. **Curated providers**, added as user engines on a profile's first run:
   - DuckDuckGo: the app-provided engine if present, else a user engine, alias `@ddg`;
   - Brave Search: `@brave`;
   - Mojeek: `@mojeek`.

   **SearXNG** (`@searx`) is added only with a URL the user types. Nulavio never picks a public instance. **Kagi** is added only on request. Custom URL templates and OpenSearch URLs are supported.
3. **Defaults:** on a profile's first run, DuckDuckGo becomes the default for normal and private windows, **only if the default is still the application's own** (a user's earlier choice is kept). Private windows get an independent default (`browser.search.separatePrivateDefault.enabled` + `.featureGate`).
4. **No remote suggestions without consent, per provider.**
   - Seed prefs turn off `browser.search.suggest.enabled` and trending (`browser.urlbar.suggest.trending`).
   - Opting in is per provider and stored in `nulavio.search.suggest.optin` (engine ids).
   - The module keeps `browser.search.suggest.enabled` true only while the default engine is opted in. It does the same for `.private` with the private default.
   - Local suggestions (history, bookmarks, open tabs) are unaffected; they never leave the device.
5. **Input validation** (`validateTemplate`):
   - `https:` only, except `http:` on loopback;
   - a host is required, with no credentials in the URL;
   - `{searchTerms}` (or `%s`, normalised) is required in the search URL;
   - suggestion URLs follow the same rules and must stay on the search URL's host;
   - aliases match `^@?[a-z0-9][a-z0-9_-]{0,19}$` and must be unique.

## Interfaces

```
browser.nulavioSearch (experiment API, built-in Shell only; logic in browser/shell/modules/NulavioSearch.sys.mjs)
  state() -> {engines: [{id, name, alias, aliases, kind, provider, host, isDefault, isDefaultPrivate,
                         canSuggest, suggestHost, suggestOptIn, removable}],
              suggestions, suggestionsPrivate, separatePrivateDefault, providers}
  addProvider("duckduckgo"|"brave"|"mojeek"|"kagi") -> id
  addSearxng({url, alias?}) -> id            // https base URL of an instance the user names
  addCustom({name, url, alias?, suggestUrl?}) -> id
  addOpenSearch({url}) -> id                 // downloads the description once, at the user's request
  remove(id) ; setDefault(id, {private?}) ; setAlias(id, alias)
  setSuggestOptIn(id, enabled) ; setSuggestPrivate(enabled)
  onChanged
Errors are stable codes (needs-https, missing-terms, alias-taken, ...), translated by the page.

Patch 0004 (toolkit/components/search/SearchSuggestionController.sys.mjs):
  remote suggestions and trending also require engine.id ∈ pref nulavio.search.suggest.optin (default "")
```

Where the consent lives: the upstream switch `browser.search.suggest.enabled` stays the master switch; turning it on in the engine's own Settings counts as consent for the current default engine only (the module adds that engine to the list). The Shell's search settings turn the master switch on with the first provider and off with the last.

## Consequences and risks

| Risk | Mitigation |
|---|---|
| Users lose suggestion convenience | One switch per provider, with the disclosure "what you type is sent to X while you type" |
| A provider's URL changes | Providers are user engines the user can edit or remove; the definitions live in one file |
| Search Service APIs change (they moved to `moz-src:` in 158) | Integration tests call the real service; failures show up on rebase |
| Track A (distribution Firefox) cannot load the experiment | Track A gets the privacy prefs (seed) and upstream Settings for engines; documented |
| Kagi needs an account | Added only on request; no token handling (sign-in happens on kagi.com) |

## Verification

`tests/integration/test_search.py` types into the real address bar with key events while recording every HTTP request the browser starts:

- typing and focusing send nothing to any search provider, also with aliases (`@google`, `@bing`, `@ddg`, `@brave`); both tracks;
- **positive control**: a local fixture engine receives suggestion requests only after opting in, and opting in for it does not let `@brave` or `@google` receive typed text (patch 0004); after opting out, nothing again;
- an alias search goes straight to its engine and nowhere else;
- first-run defaults and providers, private default independent of the normal one, validation codes, SearXNG URLs, Kagi on request, removal also removes consent, migration runs once and keeps a choice, the upstream switch counts only for the default engine;
- the settings page adds and removes an engine through its buttons and loads nothing from the network.

Track B 12/12; Track A runs the three "nothing sent" tests (the rest need the build).
