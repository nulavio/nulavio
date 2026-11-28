// Runs the Guard's start-up check and "Restore previous engine" (resolve(id, "undo") on a search-changed finding,
// browser/shell/modules/NulavioGuard.sys.mjs) against stand-ins for the engine's search service and the record (#896).
// Each case writes a record whose search defaults are `record`, starts a fresh Guard with the engine's defaults at
// `now` and the engines in `installed`, then clicks undo `clicks` times. Prints, as JSON, for each case: the findings
// of the check, what each click answered (the findings left, or the error's code) with the engine's defaults and the
// finding after it, and the record's search defaults at the end. Used by tests/unit/test_shell.py
// (GuardSearchUndoTest).
//
//     node tests/lib/guard_search_undo_driver.mjs <NulavioGuard module>

import { pathToFileURL } from "node:url";

const files = new Map(); // the record, by path
const search = { default: null, private: null, installed: new Set(), unreadable: false, set: [] };
const engine = name => (search.installed.has(name) ? { name } : null);

globalThis.Ci = {
  nsIFile: {},
  nsIPrefBranch: { PREF_INVALID: 0, PREF_STRING: 32, PREF_INT: 64, PREF_BOOL: 128 },
  nsIEnterprisePolicies: { ACTIVE: 1 },
  nsIX509CertDB: {},
  nsIPKCS11ModuleDB: {},
  nsITimer: { TYPE_ONE_SHOT: 0 },
  nsISearchService: { CHANGE_REASON_USER: 1 },
};
globalThis.Cc = {
  "@mozilla.org/timer;1": { createInstance: () => ({ initWithCallback: () => {}, cancel: () => {} }) },
  "@mozilla.org/security/x509certdb;1": { getService: () => ({ getCerts: async () => [] }) },
  "@mozilla.org/security/pkcs11moduledb;1": { getService: () => ({ listModules: async () => [] }) },
};
globalThis.PathUtils = { join: (...parts) => parts.join("/"), filename: path => path.split("/").at(-1) };
const missing = async () => {
  throw new Error("no such file");
};
globalThis.IOUtils = {
  readJSON: async path => {
    if (!files.has(path)) {
      throw new Error("no such file");
    }
    return structuredClone(files.get(path));
  },
  writeJSON: async (path, data) => void files.set(path, structuredClone(data)),
  setPermissions: async () => {},
  getChildren: missing,
  readUTF8: missing,
  read: missing,
  stat: missing,
};
globalThis.Services = {
  prefs: {
    prefIsLocked: () => false,
    prefHasUserValue: () => false,
    getPrefType: () => 0,
    getChildList: () => [],
    getBoolPref: (name, fallback) => fallback,
    getDefaultBranch: () => ({ getStringPref: (name, fallback) => fallback }),
    addObserver: () => {},
    removeObserver: () => {},
  },
  obs: { addObserver: () => {}, removeObserver: () => {}, notifyObservers: () => {} },
  perms: { ALLOW_ACTION: 1, getAllByTypes: () => [] },
  wm: { getEnumerator: () => [] },
  tm: { dispatchToMainThread: () => {} },
  dirsvc: { get: key => ({ path: `/${key}` }) },
  appinfo: { appBuildID: "20261127000000" },
  policies: { status: 0 },
  search: {
    init: async () => {
      if (search.unreadable) {
        throw new Error("the search service could not be read");
      }
    },
    getDefault: async () => engine(search.default),
    getDefaultPrivate: async () => engine(search.private),
    getEngineByName: engine,
    setDefault: async (e, reason) => {
      search.set.push(["default", e.name, reason]);
      search.default = e.name;
    },
    setDefaultPrivate: async (e, reason) => {
      search.set.push(["private", e.name, reason]);
      search.private = e.name;
    },
  },
};
const fakes = {
  AddonManager: {
    STATE_POSTPONED: 7,
    getAddonsByTypes: async () => [],
    getAllInstalls: async () => [],
    getAddonByID: async () => null,
    addAddonListener: () => {},
    addInstallListener: () => {},
  },
  AddonManagerPrivate: { getNewSideloads: async () => [] },
  AsyncShutdown: { appShutdownConfirmed: { addBlocker: () => {} } },
  NulavioAI: { workspaceAgent: async () => null },
};
globalThis.ChromeUtils = {
  defineESModuleGetters(lazy, modules) {
    for (const name of Object.keys(modules)) {
      if (name in fakes) {
        Object.defineProperty(lazy, name, { get: () => fakes[name] });
      }
    }
  },
  generateQI: () => () => {},
};

const guard = await import(pathToFileURL(process.argv[2]).href);
const Guard = guard.NulavioGuard.constructor;
const path = PathUtils.join(Services.dirsvc.get("ProfD").path, guard.RECORD);

/** One start: the record's search defaults (`record`; undefined: a record without them), the engine's defaults now,
    the engines installed, and how many times "Restore previous engine" is clicked. */
async function start({ record, now, installed, clicks = 1, unreadable = false }) {
  files.clear();
  const snapshot = { build: Services.appinfo.appBuildID, extensions: {}, prefs: {}, roots: {}, modules: {} };
  Object.assign(snapshot, { hosts: {}, policies: null, userJs: null });
  if (record !== undefined) {
    snapshot.search = record;
  }
  files.set(path, { schema: 1, snapshot, pending: [], expected: {}, owned: {} });
  Object.assign(search, { ...now, installed: new Set(installed), unreadable, set: [] });
  const fresh = new Guard();
  const checked = await fresh.check();
  const finding = () => fresh.findings().find(f => f.kind === "search-changed") ?? null;
  const brief = f => (f ? { before: f.before, after: f.after } : null);
  const out = { found: brief(finding()), others: checked.findings.filter(f => f.kind !== "search-changed").length, clicks: [] };
  for (let i = 0; i < clicks && finding(); i++) {
    search.set = [];
    let answer;
    try {
      answer = { left: (await fresh.resolve(finding().id, "undo")).length };
    } catch (e) {
      answer = { error: e?.code ?? String(e) };
    }
    out.clicks.push({
      ...answer,
      engine: { default: search.default, private: search.private },
      set: search.set,
      finding: brief(finding()),
      saved: brief(files.get(path).pending.find(f => f.kind === "search-changed")),
    });
  }
  out.record = files.get(path).snapshot.search ?? null;
  return out;
}

const all = ["A", "B", "C", "D"]; // A and B: the previous defaults; C and D: what they are now
const was = { default: "A", private: "B" };
const changed = { default: "C", private: "D" };
const out = {
  // Both previous engines installed: both are put back.
  both: await start({ record: was, now: changed, installed: all }),
  // The previous regular engine is gone: the private one is put back, the regular one stays and is still reported.
  regularGone: await start({ record: was, now: changed, installed: ["B", "C", "D"], clicks: 2 }),
  // The previous private engine is gone: the regular one is put back, the private one stays and is still reported.
  privateGone: await start({ record: was, now: changed, installed: ["A", "C", "D"], clicks: 2 }),
  // Neither is installed: nothing is changed.
  neither: await start({ record: was, now: changed, installed: ["C", "D"] }),
  // Only the private default changed, and its previous engine is gone: the regular default is not touched.
  privateOnlyGone: await start({ record: { default: "C", private: "B" }, now: changed, installed: ["C", "D"] }),
  // Only the private default changed, and its previous engine is there: only it is put back.
  privateOnly: await start({ record: { default: "C", private: "B" }, now: changed, installed: all }),
  // OpenCodeReview round 2 on #876: a record whose search defaults could not be read at its start (null), and a
  // record from before the search check (no field): nothing to compare against, and the record takes them now.
  recordNull: await start({ record: null, now: changed, installed: all }),
  recordWithout: await start({ record: undefined, now: changed, installed: all }),
  // The defaults cannot be read at this start: the record keeps the ones it had, for the next start to compare with.
  unreadableNow: await start({ record: was, now: changed, installed: all, unreadable: true }),
};
console.log(JSON.stringify(out));
