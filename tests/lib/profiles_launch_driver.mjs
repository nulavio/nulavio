// Runs the Shell's check in front of the engine's own profile launches (NulavioProfiles.guardLaunches, in
// browser/shell/modules/NulavioProfiles.sys.mjs) against stand-ins for the engine's profile service, the lock
// state and the agent's environment, and prints, as JSON, what each case did: whether the engine's own
// launchInstance ran, whether the unlock page opened, and which error code was logged. Used by
// tests/unit/test_profiles_launch.py; the real engine is exercised by tests/integration/test_vault_profiles.py
// and tests/integration/test_routing.py.
//
//     node tests/lib/profiles_launch_driver.mjs <NulavioProfiles module>

import { pathToFileURL } from "node:url";

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

// -- stand-ins for what the engine and the other Shell modules give the module ------------------------

const state = { driven: false, lock: "plain", launched: [], unlockPages: [], logged: [] };

const service = {
  currentProfile: { id: "current" },
  // The engine's own SelectableProfileService.launchInstance.
  launchInstance(profile, urls) {
    state.launched.push({ id: profile.id, urls });
  },
};

const stand = {
  NulavioAgentNetwork: { driven: () => state.driven },
  profileLockState: async () => {
    if (state.lock === "unreadable") {
      throw new Error("unreadable");
    }
    return state.lock;
  },
  NulavioVault: {
    openUnlockPage: async (id, url) => {
      state.unlockPages.push({ id, url });
    },
  },
  SelectableProfileService: service,
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

console.error = (...args) => {
  state.logged.push(args.map(a => a?.code ?? String(a)).join(" "));
};

const { NulavioProfiles } = await import(pathToFileURL(process.argv[2]).href);
NulavioProfiles.guardLaunches();

/** A launch through the engine's own path (its menus call service.launchInstance), in the given conditions. */
async function launch({ driven = false, lock = "plain", urls = [] } = {}) {
  Object.assign(state, { driven, lock, launched: [], unlockPages: [], logged: [] });
  service.launchInstance({ id: "other", path: "/profiles/other" }, urls);
  for (let i = 0; i < 5; i++) {
    await flush();
  }
  return { launched: state.launched.length, unlockPages: state.unlockPages.length, logged: state.logged };
}

const cases = {
  plain: () => launch(),
  locked: () => launch({ lock: "locked", urls: ["https://example.org/moved"] }),
  unreadable: () => launch({ lock: "unreadable" }),
  agent_plain: () => launch({ driven: true }),
  agent_unlocked: () => launch({ driven: true, lock: "unlocked" }),
  agent_locked: () => launch({ driven: true, lock: "locked", urls: ["https://example.org/moved"] }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
