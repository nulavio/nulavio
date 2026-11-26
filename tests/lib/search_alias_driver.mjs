// Runs Nulavio Search's keep on the assistant's "@ia" keyword (#663: RESERVED_ALIASES, normalizeAlias and
// releaseReservedAliases in browser/shell/modules/NulavioSearch.sys.mjs) against a stand-in for the engine's search
// service, and prints, as JSON, what each case did. The stand-in notifies a change to an engine the way the engine's
// SearchUtils.notifyAction does: synchronously, from the alias setter. Used by tests/unit/test_search_alias.py; the
// real engine is exercised by tests/integration/test_search.py (05b, 08).
//
//     node tests/lib/search_alias_driver.mjs <NulavioSearch module>

import { pathToFileURL } from "node:url";

const flush = async () => {
  for (let i = 0; i < 20; i++) {
    await new Promise(resolve => setTimeout(resolve, 0));
  }
};

// -- stand-ins for what the engine gives the module ----------------------------------------------------

const TOPIC = "browser-search-engine-modified";
const observers = new Map();
const prefs = new Map([["nulavio.search.migration", 1]]); // a profile that has run before: no first-run migration
const logged = [];
let enginesRead = 0;

globalThis.Services = {
  prefs: {
    getIntPref: (name, fallback) => (prefs.has(name) ? prefs.get(name) : fallback),
    getBoolPref: (name, fallback) => (prefs.has(name) ? prefs.get(name) : fallback),
    getStringPref: (name, fallback) => (prefs.has(name) ? prefs.get(name) : fallback),
    setIntPref: (name, value) => prefs.set(name, value),
    setBoolPref: (name, value) => prefs.set(name, value),
    setStringPref: (name, value) => prefs.set(name, value),
    addObserver: () => {},
  },
  obs: {
    addObserver(observer, topic) {
      observers.set(topic, [...(observers.get(topic) ?? []), observer]);
    },
    notifyObservers(subject, topic, data) {
      for (const observer of observers.get(topic) ?? []) {
        observer.observe(subject, topic, data);
      }
    },
  },
};

class ConfigSearchEngine {}
class UserSearchEngine {
  #alias;
  constructor({ id, name, url, alias = "", suggestUrl }) {
    Object.assign(this, { id, name, url, suggestUrl, hidden: false });
    this.#alias = alias;
  }
  get alias() {
    return this.#alias;
  }
  // The engine's SearchEngine: trims, keeps the case, and tells every observer of the topic at once.
  set alias(value) {
    this.#alias = value ? value.trim() : "";
    Services.obs.notifyObservers(this, TOPIC, "engine-changed");
  }
  get aliases() {
    return this.#alias ? [this.#alias] : [];
  }
  supportsResponseType() {
    return false;
  }
}

const engines = [];
let nextId = 1;
const SearchService = {
  CHANGE_REASON: { USER: 1 },
  init: async () => {},
  getEngines: async () => {
    enginesRead++;
    return [...engines];
  },
  getVisibleEngines: async () => engines.filter(e => !e.hidden),
  getEngineById: id => engines.find(e => e.id === id) ?? null,
  getEngineByName: name => engines.find(e => e.name === name) ?? null,
  async addUserEngine({ name, url, alias, suggestUrl }) {
    const engine = new UserSearchEngine({ id: `user-${nextId++}`, name, url, alias: alias ?? "", suggestUrl });
    engines.push(engine);
    Services.obs.notifyObservers(engine, TOPIC, "engine-added");
    return engine;
  },
};

const stand = {
  ConfigSearchEngine,
  UserSearchEngine,
  SearchService,
  SearchUtils: {
    TOPIC_ENGINE_MODIFIED: TOPIC,
    MODIFIED_TYPE: { CHANGED: "engine-changed", ADDED: "engine-added", REMOVED: "engine-removed" },
    URL_TYPE: { SEARCH: "text/html", SUGGEST_JSON: "application/x-suggestions+json" },
  },
};

globalThis.ChromeUtils = {
  defineESModuleGetters(lazy, modules) {
    for (const name of Object.keys(modules)) {
      Object.defineProperty(lazy, name, {
        get: () => {
          if (!(name in stand)) {
            throw new Error(`no stand-in for ${name}`);
          }
          return stand[name];
        },
      });
    }
  },
  generateQI: () => () => {},
};

console.warn = (...args) => logged.push(args.map(String).join(" "));
console.error = (...args) => {
  // The choice file of a new profile is looked for at every start; there is no profile folder here.
  const text = args.map(a => a?.code ?? String(a)).join(" ");
  if (!text.startsWith("Nulavio Search: the search choice file")) {
    logged.push(text);
  }
};

const mod = await import(pathToFileURL(process.argv[2]).href);
const { NulavioSearch, normalizeAlias, RESERVED_ALIASES } = mod;

const code = async action => {
  try {
    await action();
    return null;
  } catch (e) {
    return e?.code ?? String(e);
  }
};
const add = (name, alias) => SearchService.addUserEngine({ name, url: `https://${name.toLowerCase()}.example/?q={searchTerms}`, alias });

// Engines a profile had before this change: one with "@IA" as the engine stores what its edit dialog was given.
const archive = await add("Archive", "@IA");
const ddg = await add("Duck", "@ddg");

const out = { reserved: RESERVED_ALIASES };

out.normalized = {};
for (const typed of ["ia", "@ia", "@IA", "  Ia ", "iab", "@ddg", "", "media"]) {
  out.normalized[typed] = await code(() => normalizeAlias(typed)) ?? normalizeAlias(typed);
}

// At start-up the old "@IA" goes; nothing else changes.
logged.length = 0;
await NulavioSearch.startup();
await flush();
out.startup = {
  archive: archive.alias,
  ddg: ddg.alias,
  released: await NulavioSearch.releasedAliases(),
  logged: [...logged],
};

// The Shell's own ways in refuse it.
const before = engines.length;
out.refused = {
  setAlias: await code(() => NulavioSearch.setAlias(ddg.id, "ia")),
  setAliasKept: ddg.alias,
  addCustom: await code(() => NulavioSearch.addCustom({ name: "Custom", url: "https://custom.example/?q=%s", alias: "@IA" })),
  addSearxng: await code(() => NulavioSearch.addSearxng({ url: "https://searx.example.org/", alias: "ia" })),
  added: engines.length - before,
};

// The engine's own dialogs write the alias themselves: an edit and a new engine both lose it right after.
logged.length = 0;
enginesRead = 0;
ddg.alias = "@Ia";
const fresh = await add("Fresh", "@ia");
await flush();
out.afterChange = {
  ddg: ddg.alias,
  fresh: fresh.alias,
  released: (await NulavioSearch.releasedAliases()).sort(),
  passesBounded: enginesRead > 0 && enginesRead <= 4,
  logged: logged.length,
};

// Another alias given afterwards: Settings no longer names that engine.
archive.alias = "@archive";
await flush();
out.afterNewAlias = { archive: archive.alias, released: (await NulavioSearch.releasedAliases()).sort() };

process.stdout.write(JSON.stringify(out));
