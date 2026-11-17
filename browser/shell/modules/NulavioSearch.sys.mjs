/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio Search (docs/adr/0002-nulavio-search.md).

   A thin layer over the engine's Search Service: curated providers, input
   validation, independent defaults for normal and private windows, and
   per-provider consent for remote suggestions. Nulavio adds no search back
   end: searches go from the browser straight to the provider the user chose.
   This module makes no network request of its own (adding an OpenSearch
   description downloads that description, at the user's request). */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  ConfigSearchEngine: "moz-src:///toolkit/components/search/ConfigSearchEngine.sys.mjs",
  SearchService: "moz-src:///toolkit/components/search/SearchService.sys.mjs",
  SearchUtils: "moz-src:///toolkit/components/search/SearchUtils.sys.mjs",
  UserSearchEngine: "moz-src:///toolkit/components/search/UserSearchEngine.sys.mjs",
});

/** Engine ids allowed to receive typed text (read by patch 0004 in SearchSuggestionController). */
export const PREF_OPTIN = "nulavio.search.suggest.optin";
/** Per-profile migration version. */
export const PREF_MIGRATION = "nulavio.search.migration";
const PREF_SUGGEST = "browser.search.suggest.enabled";
const PREF_SUGGEST_PRIVATE = "browser.search.suggest.enabled.private";
const MIGRATION_VERSION = 1;
const MAX_URL_LENGTH = 2048;
const SUGGEST_TYPE = "application/x-suggestions+json";

/* Providers Nulavio offers by name. URLs come from each provider's own
   OpenSearch description (checked 2026-10-25; Ecosia, Qwant and Startpage
   2026-11-16, docs/research/search-providers.md). `firstRun` providers are
   added to every new profile; the others only when the user asks. Listed to
   the person by name, alphabetically (#151): this order means nothing. */
export const PROVIDERS = Object.freeze({
  duckduckgo: Object.freeze({
    name: "DuckDuckGo",
    configId: "ddg",
    alias: "@ddg",
    search: "https://duckduckgo.com/?q={searchTerms}",
    suggest: "https://duckduckgo.com/ac/?q={searchTerms}&type=list",
    firstRun: true,
  }),
  brave: Object.freeze({
    name: "Brave Search",
    alias: "@brave",
    search: "https://search.brave.com/search?q={searchTerms}",
    suggest: "https://search.brave.com/api/suggest?q={searchTerms}",
    firstRun: true,
  }),
  mojeek: Object.freeze({
    name: "Mojeek",
    alias: "@mojeek",
    search: "https://www.mojeek.com/search?q={searchTerms}",
    suggest: null,
    firstRun: true,
  }),
  kagi: Object.freeze({
    name: "Kagi",
    alias: "@kagi",
    search: "https://kagi.com/search?q={searchTerms}",
    suggest: "https://kagisuggest.com/api/autosuggest?q={searchTerms}",
    firstRun: false,
  }),
  ecosia: Object.freeze({
    name: "Ecosia",
    alias: "@ecosia",
    search: "https://www.ecosia.org/search?q={searchTerms}",
    suggest: "https://ac.ecosia.org/autocomplete?q={searchTerms}&type=list",
    firstRun: false,
  }),
  qwant: Object.freeze({
    name: "Qwant",
    alias: "@qwant",
    search: "https://www.qwant.com/?q={searchTerms}",
    suggest: "https://api.qwant.com/v3/suggest/?q={searchTerms}&client=opensearch",
    firstRun: false,
  }),
  startpage: Object.freeze({
    name: "Startpage",
    alias: "@startpage",
    search: "https://www.startpage.com/sp/search?query={searchTerms}",
    suggest: "https://www.startpage.com/osuggestions?q={searchTerms}",
    firstRun: false,
  }),
});

/* Providers with accounts (#151). Whether this profile is signed in is read from the presence of the provider's
   session cookie, by name: its value is never read and nothing is sent. The name and the sign-in page are the
   provider's own (Kagi: help.kagi.com/kagi/privacy/cookies.html, checked 2026-11-16). */
export const ACCOUNTS = Object.freeze({
  kagi: Object.freeze({ host: "kagi.com", cookie: "kagi_session", signIn: "https://kagi.com/signin" }),
});

/* #151: a new profile's search. The profile that creates it writes the choice into the new profile's folder (mode
   0600, through a new temporary file, never through a link), and the new profile's Shell applies it at its first start
   only, then deletes the file. At any later start such a file is deleted unread: it never changes a profile that has
   already run. Only a provider of PROVIDERS can be named, never an address, and it carries no consent for suggestions. */
export const PENDING_FILE = "nulavio-search-choice.json";

/** Whether `path` is a symbolic link (never followed), false for another file, null when nothing is there. */
export function isLink(path) {
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  file.initWithPath(path);
  try {
    return file.isSymlink(); // lstat: true for a link, dangling or not
  } catch {
    return null; // NS_ERROR_FILE_NOT_FOUND
  }
}

/** The checked form of a carried choice, or the error "invalid-choice" / "unknown-provider". */
export function validatePending(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    fail("invalid-choice");
  }
  if (Object.keys(raw).some(key => key !== "provider" && key !== "privateToo")) {
    fail("invalid-choice");
  }
  if (typeof raw.provider !== "string" || !Object.hasOwn(PROVIDERS, raw.provider)) {
    fail("unknown-provider");
  }
  if (raw.privateToo !== undefined && typeof raw.privateToo !== "boolean") {
    fail("invalid-choice");
  }
  return { provider: raw.provider, privateToo: raw.privateToo !== false };
}

/** An error the settings page can translate: `code` is stable, `message` is for logs. */
export class SearchSettingsError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "SearchSettingsError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new SearchSettingsError(code, message);
}

function isLoopback(hostname) {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return host === "localhost" || host === "::1" || /^127(\.\d{1,3}){3}$/.test(host);
}

/**
 * Check a search or suggestion URL template typed by the user.
 *
 * @param {string} raw - Template with {searchTerms} (or %s, normalised).
 * @param {object} [options]
 * @param {boolean} [options.requireTerms=true] - Whether {searchTerms} is required.
 * @returns {string} The normalised template.
 */
export function validateTemplate(raw, { requireTerms = true } = {}) {
  if (typeof raw !== "string") {
    fail("invalid-url");
  }
  const template = raw.trim().replaceAll("%s", "{searchTerms}");
  if (!template || template.length > MAX_URL_LENGTH || /[\s\u0000-\u001f\u007f]/.test(template)) {
    fail("invalid-url");
  }
  if (requireTerms && !template.includes("{searchTerms}")) {
    fail("missing-terms");
  }
  let url;
  try {
    url = new URL(template.replaceAll("{searchTerms}", "nulavio"));
  } catch {
    fail("invalid-url");
  }
  if (url.username || url.password) {
    fail("credentials-in-url");
  }
  if (!url.hostname) {
    fail("invalid-url");
  }
  if (url.protocol === "http:" && !isLoopback(url.hostname)) {
    fail("needs-https");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    fail("needs-https");
  }
  return template;
}

/**
 * Base URL of a SearXNG instance typed by the user, e.g. "https://searx.example.org/".
 * Only the instance the user names is used; Nulavio never picks a public one.
 */
export function validateSearxngBase(raw) {
  const base = validateTemplate(raw, { requireTerms: false });
  const url = new URL(base);
  if (url.search || url.hash) {
    fail("invalid-url", "the instance address cannot have a query or fragment");
  }
  url.pathname = url.pathname.replace(/\/(search)?\/?$/, "") + "/";
  return url.href;
}

/** Aliases are short keywords; "@" is added so the address bar treats them as engine shortcuts. */
export function normalizeAlias(raw) {
  if (raw === undefined || raw === null || raw === "") {
    return "";
  }
  const alias = String(raw).trim().toLowerCase().replace(/^@?/, "@");
  if (!/^@[a-z0-9][a-z0-9_.-]{0,19}$/.test(alias)) {
    fail("invalid-alias");
  }
  return alias;
}

function normalizeName(raw) {
  const name = String(raw ?? "").trim().replace(/\s+/g, " ");
  if (!name || name.length > 60 || /[\u0000-\u001f\u007f]/.test(name)) {
    fail("invalid-name");
  }
  return name;
}

function suggestHost(engine) {
  if (!engine.supportsResponseType(SUGGEST_TYPE)) {
    return null;
  }
  try {
    return engine.getSubmission("nulavio", SUGGEST_TYPE).uri.host;
  } catch {
    return null;
  }
}

class NulavioSearchClass {
  #listeners = new Set();
  #observing = false;
  #writingSuggestPref = false;
  #started = null;

  // -- consent ----------------------------------------------------------

  optInIds() {
    return Services.prefs
      .getStringPref(PREF_OPTIN, "")
      .split(",")
      .map(id => id.trim())
      .filter(Boolean);
  }

  #writeOptIn(ids) {
    Services.prefs.setStringPref(PREF_OPTIN, [...new Set(ids)].join(","));
  }

  #setSuggestMaster(pref, value) {
    this.#writingSuggestPref = true;
    try {
      Services.prefs.setBoolPref(pref, value);
    } finally {
      this.#writingSuggestPref = false;
    }
  }

  // -- engines ----------------------------------------------------------

  async #engine(id) {
    await lazy.SearchService.init();
    const engine = lazy.SearchService.getEngineById(id);
    if (!engine || engine.hidden) {
      fail("not-found");
    }
    return engine;
  }

  #kind(engine) {
    if (engine instanceof lazy.ConfigSearchEngine) {
      return "builtin";
    }
    if (engine instanceof lazy.UserSearchEngine) {
      return "user";
    }
    return engine.constructor?.name === "OpenSearchEngine" ? "opensearch" : "addon";
  }

  #providerKey(engine) {
    for (const [key, provider] of Object.entries(PROVIDERS)) {
      if (engine.id === provider.configId || engine.name === provider.name) {
        return key;
      }
    }
    return engine.name.startsWith("SearXNG") ? "searxng" : null;
  }

  async #aliasTaken(alias, exceptId = null) {
    if (!alias) {
      return false;
    }
    for (const engine of await lazy.SearchService.getEngines()) {
      if (engine.id !== exceptId && engine.aliases.map(a => a.toLowerCase()).includes(alias)) {
        return true;
      }
    }
    return false;
  }

  async list() {
    await lazy.SearchService.init();
    const [engines, normal, privateDefault] = await Promise.all([
      lazy.SearchService.getVisibleEngines(),
      lazy.SearchService.getDefault(),
      lazy.SearchService.getDefaultPrivate(),
    ]);
    const optIn = new Set(this.optInIds());
    return engines.map(engine => ({
      id: engine.id,
      name: engine.name,
      alias: engine.alias ?? "", // the user's own alias (editable)
      aliases: engine.aliases, // the user's alias plus the engine's built-in ones
      kind: this.#kind(engine),
      provider: this.#providerKey(engine),
      host: engine.searchUrlDomain,
      isDefault: engine.id === normal.id,
      isDefaultPrivate: engine.id === privateDefault.id,
      canSuggest: Boolean(suggestHost(engine)),
      suggestHost: suggestHost(engine),
      suggestOptIn: optIn.has(engine.id),
      removable: engines.length > 1,
    }));
  }

  async state() {
    // UX3G N5: a page asking before the first-run migration ran (the first new
    // tab) waits for it, so it never shows an engine that is about to change.
    if (Services.prefs.getIntPref(PREF_MIGRATION, 0) < MIGRATION_VERSION) {
      await this.startup().catch(e => console.error("Nulavio Search: first-run migration", e));
    }
    return {
      engines: await this.list(),
      suggestions: Services.prefs.getBoolPref(PREF_SUGGEST, false),
      suggestionsPrivate: Services.prefs.getBoolPref(PREF_SUGGEST_PRIVATE, false),
      separatePrivateDefault:
        Services.prefs.getBoolPref("browser.search.separatePrivateDefault.featureGate", false) &&
        Services.prefs.getBoolPref("browser.search.separatePrivateDefault.enabled", false),
      providers: Object.entries(PROVIDERS)
        .map(([key, p]) => ({
          key,
          name: p.name,
          alias: p.alias,
          account: key in ACCOUNTS,
          suggests: Boolean(p.suggest),
          suggestHost: p.suggest ? new URL(p.suggest.replace("{searchTerms}", "x")).host : null,
        }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    };
  }

  /** The host an engine sends typed text to for suggestions, or null: the engine's own, whatever its name. */
  suggestHostOf(id) {
    const engine = lazy.SearchService.getEngineById(String(id));
    return engine ? suggestHost(engine) : null;
  }

  /**
   * #151: whether this profile is signed in to each provider that has accounts, from the presence of its session
   * cookie in this profile's normal (not private) cookie jar. `signedIn` is null when the cookies could not be read.
   */
  accounts() {
    const result = {};
    for (const [key, account] of Object.entries(ACCOUNTS)) {
      let signedIn = null;
      try {
        signedIn = Services.cookies.getCookiesFromHost(account.host, {}).some(cookie => cookie.name === account.cookie);
      } catch (e) {
        console.error(`Nulavio Search: cookies of ${account.host}`, e);
      }
      result[key] = { signedIn, signIn: account.signIn, host: account.host };
    }
    return result;
  }

  /**
   * #151: one engine becomes this profile's search in one step. Either `provider`, a curated key (added when the
   * profile does not have it), or `id`, an engine already in the list (a SearXNG instance, a custom engine, an
   * OpenSearch one). It becomes the default for normal windows and, unless `privateToo` is false, for private
   * windows. `suggest` true or false allows or stops sending what is typed to it (the per-provider consent);
   * left out, the consent stays as it is. Nothing is sent to the provider by choosing it.
   */
  async choose({ provider = null, id = null, privateToo = true, suggest = undefined } = {}) {
    await lazy.SearchService.init();
    if ((provider === null) === (id === null) || (suggest !== undefined && typeof suggest !== "boolean")) {
      fail("invalid-choice");
    }
    if (provider !== null && !Object.hasOwn(PROVIDERS, provider)) {
      fail("unknown-provider");
    }
    const engine = await this.#engine(provider !== null ? await this.addProvider(provider) : id);
    if (suggest === true && !engine.supportsResponseType(SUGGEST_TYPE)) {
      fail("no-suggestions");
    }
    await lazy.SearchService.setDefault(engine, lazy.SearchService.CHANGE_REASON.USER);
    if (privateToo) {
      await lazy.SearchService.setDefaultPrivate(engine, lazy.SearchService.CHANGE_REASON.USER_PRIVATE_SPLIT);
    }
    if (suggest !== undefined) {
      await this.setSuggestOptIn(engine.id, suggest);
    }
    return engine.id;
  }

  async #addUserEngine({ name, search, suggest, alias }) {
    name = normalizeName(name);
    alias = normalizeAlias(alias);
    const url = validateTemplate(search);
    const suggestUrl = suggest ? validateTemplate(suggest) : undefined;
    if (lazy.SearchService.getEngineByName(name)) {
      fail("name-taken");
    }
    if (await this.#aliasTaken(alias)) {
      fail("alias-taken");
    }
    const engine = await lazy.SearchService.addUserEngine({ name, url, alias: alias || undefined, suggestUrl });
    return engine.id;
  }

  async addProvider(key) {
    await lazy.SearchService.init();
    const provider = PROVIDERS[key];
    if (!provider) {
      fail("unknown-provider");
    }
    if (provider.configId) {
      const builtin = lazy.SearchService.getEngineById(provider.configId);
      if (builtin) {
        builtin.hidden = false; // restore it if the user had removed it
        return builtin.id;
      }
    }
    const existing = lazy.SearchService.getEngineByName(provider.name);
    if (existing) {
      existing.hidden = false;
      return existing.id;
    }
    const alias = (await this.#aliasTaken(provider.alias)) ? "" : provider.alias;
    return this.#addUserEngine({ name: provider.name, search: provider.search, suggest: provider.suggest, alias });
  }

  async addSearxng({ url, alias = "@searx" }) {
    await lazy.SearchService.init();
    const base = validateSearxngBase(url);
    const host = new URL(base).host;
    return this.#addUserEngine({
      name: `SearXNG (${host})`,
      search: `${base}search?q={searchTerms}`,
      suggest: `${base}autocompleter?q={searchTerms}`,
      alias: (await this.#aliasTaken(normalizeAlias(alias))) ? "" : alias,
    });
  }

  async addCustom({ name, url, alias, suggestUrl }) {
    await lazy.SearchService.init();
    const search = validateTemplate(url);
    let suggest = null;
    if (suggestUrl) {
      suggest = validateTemplate(suggestUrl);
      // A custom engine may only send typed text to its own host.
      if (new URL(suggest.replaceAll("{searchTerms}", "x")).host !== new URL(search.replaceAll("{searchTerms}", "x")).host) {
        fail("suggest-other-host");
      }
    }
    return this.#addUserEngine({ name, search, suggest, alias });
  }

  async addOpenSearch({ url }) {
    await lazy.SearchService.init();
    const description = validateTemplate(url, { requireTerms: false });
    try {
      const engine = await lazy.SearchService.addOpenSearchEngine(description, null);
      return engine.id;
    } catch (e) {
      fail("opensearch-failed", String(e?.message ?? e));
    }
    return null;
  }

  async remove(id) {
    const engine = await this.#engine(id);
    if ((await lazy.SearchService.getVisibleEngines()).length <= 1) {
      fail("last-engine");
    }
    await lazy.SearchService.removeEngine(engine, lazy.SearchService.CHANGE_REASON.USER);
    this.#writeOptIn(this.optInIds().filter(x => x !== id));
    this.#syncSuggestMasters();
  }

  async setDefault(id, { private: isPrivate = false } = {}) {
    const engine = await this.#engine(id);
    if (isPrivate) {
      await lazy.SearchService.setDefaultPrivate(engine, lazy.SearchService.CHANGE_REASON.USER_PRIVATE_SPLIT);
    } else {
      await lazy.SearchService.setDefault(engine, lazy.SearchService.CHANGE_REASON.USER);
    }
  }

  async setAlias(id, alias) {
    const engine = await this.#engine(id);
    alias = normalizeAlias(alias);
    if (await this.#aliasTaken(alias, id)) {
      fail("alias-taken");
    }
    engine.alias = alias;
  }

  /**
   * Allow or stop remote suggestions from one engine. Allowing also turns on
   * the engine's global switch (the user asked for suggestions); stopping the
   * last one turns it off.
   */
  async setSuggestOptIn(id, enabled) {
    const engine = await this.#engine(id);
    if (enabled && !engine.supportsResponseType(SUGGEST_TYPE)) {
      fail("no-suggestions");
    }
    const ids = this.optInIds().filter(x => x !== id);
    if (enabled) {
      ids.push(id);
    }
    this.#writeOptIn(ids);
    this.#syncSuggestMasters();
  }

  async setSuggestPrivate(enabled) {
    this.#setSuggestMaster(PREF_SUGGEST_PRIVATE, Boolean(enabled));
  }

  #syncSuggestMasters() {
    const any = this.optInIds().length > 0;
    if (Services.prefs.getBoolPref(PREF_SUGGEST, false) !== any) {
      this.#setSuggestMaster(PREF_SUGGEST, any);
    }
    if (!any && Services.prefs.getBoolPref(PREF_SUGGEST_PRIVATE, false)) {
      this.#setSuggestMaster(PREF_SUGGEST_PRIVATE, false);
    }
  }

  // -- migration --------------------------------------------------------

  /**
   * First run of a profile: add the curated providers and make DuckDuckGo the
   * default for normal and private windows, but only where the default is
   * still the application's own (a choice the user made is kept). Runs once.
   */
  async migrate() {
    await lazy.SearchService.init();
    if (Services.prefs.getIntPref(PREF_MIGRATION, 0) >= MIGRATION_VERSION) {
      return { migrated: false };
    }
    const added = [];
    for (const [key, provider] of Object.entries(PROVIDERS)) {
      if (!provider.firstRun) {
        continue;
      }
      try {
        added.push(await this.addProvider(key));
      } catch (e) {
        console.error(`Nulavio Search: could not add ${provider.name}`, e);
      }
    }
    const ddg = lazy.SearchService.getEngineById(PROVIDERS.duckduckgo.configId) ??
      lazy.SearchService.getEngineByName(PROVIDERS.duckduckgo.name);
    const result = { migrated: true, added, defaultChanged: false, privateDefaultChanged: false };
    if (ddg) {
      const appDefault = lazy.SearchService.appDefaultEngine;
      if ((await lazy.SearchService.getDefault()).id === appDefault?.id && ddg.id !== appDefault?.id) {
        await lazy.SearchService.setDefault(ddg, lazy.SearchService.CHANGE_REASON.UNKNOWN);
        result.defaultChanged = true;
      }
      const appPrivate = lazy.SearchService.appPrivateDefaultEngine;
      if ((await lazy.SearchService.getDefaultPrivate()).id === appPrivate?.id && ddg.id !== appPrivate?.id) {
        await lazy.SearchService.setDefaultPrivate(ddg, lazy.SearchService.CHANGE_REASON.UNKNOWN);
        result.privateDefaultChanged = true;
      }
    }
    Services.prefs.setIntPref(PREF_MIGRATION, MIGRATION_VERSION);
    return result;
  }

  // -- lifecycle and change notifications --------------------------------

  /** Called once per process by the Shell (after first paint). Idempotent. */
  startup() {
    this.#started ??= (async () => {
      this.#observe();
      // The first start of a profile is the one before its search migration has run.
      const firstStart = Services.prefs.getIntPref(PREF_MIGRATION, 0) < MIGRATION_VERSION;
      const result = await this.migrate();
      if (firstStart) {
        await this.applyPending();
      } else {
        await this.#dropPending();
      }
      return result;
    })();
    return this.#started;
  }

  /**
   * #151: the choice left for a new profile (PENDING_FILE), applied at its first start (`startup` calls this only
   * then; at any later start the file is removed unread). The file is deleted before the choice is applied, so a
   * choice that fails is not tried again; the failure is logged.
   */
  /** A choice file in a profile that has run before was not left by the profile that created it: removed unread. */
  async #dropPending() {
    try {
      const path = PathUtils.join(PathUtils.profileDir, PENDING_FILE);
      if (isLink(path) !== null) {
        await IOUtils.remove(path, { ignoreAbsent: true });
        console.warn("Nulavio Search: a search choice file in a profile that has run before was removed unread");
      }
    } catch (e) {
      console.error("Nulavio Search: the search choice file", e);
    }
  }

  async applyPending() {
    let path;
    try {
      path = PathUtils.join(PathUtils.profileDir, PENDING_FILE);
    } catch {
      return null;
    }
    const link = isLink(path);
    if (link === null) {
      return null; // nothing there: the usual start
    }
    // Read once, then deleted whatever happens, so a bad file is not tried again at every start. A link is never
    // followed: it is removed unread.
    let raw = null;
    try {
      if (!link) {
        raw = await IOUtils.readJSON(path);
      }
    } catch (e) {
      console.error("Nulavio Search: the search choice left by another profile could not be read", e);
    }
    await IOUtils.remove(path, { ignoreAbsent: true }).catch(e => console.error("Nulavio Search: the search choice file", e));
    if (raw === null) {
      return null;
    }
    try {
      const choice = validatePending(raw);
      return await this.choose({ provider: choice.provider, privateToo: choice.privateToo });
    } catch (e) {
      console.error("Nulavio Search: the search choice left by another profile was not applied", e);
      return null;
    }
  }


  #observe() {
    if (this.#observing) {
      return;
    }
    this.#observing = true;
    Services.obs.addObserver(this, lazy.SearchUtils.TOPIC_ENGINE_MODIFIED);
    for (const pref of [PREF_OPTIN, PREF_SUGGEST, PREF_SUGGEST_PRIVATE]) {
      Services.prefs.addObserver(pref, this);
    }
  }

  observe(_subject, topic, data) {
    if (topic === "nsPref:changed" && data === PREF_SUGGEST && !this.#writingSuggestPref) {
      this.#onSuggestSwitchedElsewhere().catch(e => console.error("Nulavio Search: consent sync", e));
    }
    for (const listener of this.#listeners) {
      try {
        listener();
      } catch (e) {
        console.error(e);
      }
    }
  }

  /* The upstream Settings switch ("Show search suggestions") speaks for the
     default engine: turning it on there is consent for that engine. */
  async #onSuggestSwitchedElsewhere() {
    if (!Services.prefs.getBoolPref(PREF_SUGGEST, false)) {
      return;
    }
    const engine = await lazy.SearchService.getDefault();
    if (engine && !this.optInIds().includes(engine.id) && engine.supportsResponseType(SUGGEST_TYPE)) {
      this.#writeOptIn([...this.optInIds(), engine.id]);
    }
  }

  subscribe(listener) {
    this.#observe();
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]);
}

export const NulavioSearch = new NulavioSearchClass();
