// Runs NulavioAgentNetwork.arm() (browser/shell/modules/NulavioAgentNetwork.sys.mjs), which the Shell calls at its
// start, against stand-ins for the engine's prefs, its BlockAboutProfiles way of blocking a page, its windows and the
// agent's environment, and prints, as JSON, what each case did, in order: prefs set on the default branch and locked,
// pages blocked, tabs loaded again, and READY_FILE written (the Bridge uses the engine only once it is there). Used by
// tests/unit/test_profiles_launch.py; the real engine is exercised by tests/integration/test_routing.py.
//
//     node tests/lib/agent_engine_driver.mjs <NulavioAgentNetwork module>

import { pathToFileURL } from "node:url";

const state = { env: {}, locked: {}, values: {}, events: [], tabs: [] };

const defaults = {
  setBoolPref: (name, value) => {
    state.values[name] = value;
    state.events.push(`default ${name}=${value}`);
  },
  setIntPref: (name, value) => {
    state.values[name] = value;
    state.events.push(`default ${name}=${value}`);
  },
};

globalThis.Services = {
  env: { get: name => state.env[name] ?? "" },
  prefs: {
    getDefaultBranch: () => defaults,
    getBoolPref: (name, fallback) => state.values[name] ?? fallback ?? true,
    getIntPref: (name, fallback) => state.values[name] ?? fallback ?? 0,
    prefIsLocked: name => name in state.locked,
    prefHasUserValue: () => false,
    lockPref: name => state.events.push(`lock ${name}`),
  },
  obs: { addObserver: () => {} },
  wm: {
    *getEnumerator() {
      yield {
        gBrowser: {
          tabs: state.tabs.map(spec => ({
            linkedBrowser: { currentURI: { spec }, reload: () => state.events.push(`reload ${spec}`) },
          })),
        },
      };
    },
  },
  appinfo: { processID: 1 },
};
globalThis.IOUtils = { writeUTF8: async path => state.events.push(`write ${path}`) };
globalThis.PathUtils = { join: (...parts) => parts.join("/"), profileDir: "/profile" };
globalThis.ChromeUtils = {
  defineESModuleGetters(lazy, modules) {
    for (const [name, url] of Object.entries(modules)) {
      if (name !== "blockAboutPage" || url !== "resource://gre/modules/PoliciesHelpers.sys.mjs") {
        throw new Error(`no stand-in for ${name} from ${url}`);
      }
      // The engine's PoliciesHelpers.blockAboutPage(manager, page): the policy engine's content policy then refuses
      // the page and its chrome document in this process.
      lazy.blockAboutPage = (_manager, page) => state.events.push(`block ${page}`);
    }
  },
};

/** arm() in a fresh copy of the module, in the given conditions. */
async function arm({ driven = false, locked = {}, tabs = [] } = {}) {
  Object.assign(state, { env: {}, locked, values: { ...locked }, events: [], tabs });
  if (driven) {
    state.env.NULAVIO_AI_WORKSPACE = "ag-test";
  }
  const { NulavioAgentNetwork } = await import(`${pathToFileURL(process.argv[2]).href}?${Math.random()}`);
  let armed;
  try {
    armed = await NulavioAgentNetwork.arm();
  } catch (e) {
    armed = `error: ${e.message}`;
  }
  return { armed, events: state.events, values: state.values };
}

const tabs = ["about:profiles", "chrome://global/content/aboutProfiles.xhtml", "https://example.org/", "about:blank"];
const cases = {
  person: () => arm({ tabs }),
  agent: () => arm({ driven: true, tabs }),
  agent_restore_locked_on: () => arm({ driven: true, locked: { "browser.backup.restore.enabled": true } }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
