// Runs the Shell's check in front of the engine's own profile launches (NulavioProfiles.guardLaunches, in
// browser/shell/modules/NulavioProfiles.sys.mjs) against stand-ins for the engine's profile service, the lock
// state and the agent's environment, and prints, as JSON, what each case did: whether the engine's own
// launchInstance ran, which command lines went to a running instance or started a new one, whether the unlock
// page opened, and which error code was logged. Used by
// tests/unit/test_profiles_launch.py; the real engine is exercised by tests/integration/test_vault_profiles.py
// and tests/integration/test_routing.py.
//
//     node tests/lib/profiles_launch_driver.mjs <NulavioProfiles module> <routed flag> <route-by flag>

import { pathToFileURL } from "node:url";

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

// -- stand-ins for what the engine and the other Shell modules give the module ------------------------

const state = { driven: false, lock: "plain", running: true };

const service = {
  currentProfile: { id: "current" },
  // The engine's own SelectableProfileService.launchInstance.
  launchInstance(profile, urls) {
    state.launched.push({ id: profile.id, urls });
  },
  // nsIRemoteService.sendCommandLine: throws when no instance runs with that profile.
  sendCommandLine(path, args, activate) {
    if (!state.running) {
      throw new Error("no running instance");
    }
    state.sent.push({ path, args, activate });
  },
  execProcess(args) {
    state.started.push(args);
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
  ROUTED_FLAG: process.argv[3],
  ROUTE_BY_FLAG: process.argv[4],
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
async function launch({ driven = false, lock = "plain", running = true, urls = [] } = {}) {
  Object.assign(state, { driven, lock, running, launched: [], sent: [], started: [], unlockPages: [], logged: [] });
  service.launchInstance({ id: "other", path: "/profiles/other" }, urls);
  for (let i = 0; i < 5; i++) {
    await flush();
  }
  return {
    launched: state.launched.length,
    sent: state.sent,
    started: state.started,
    unlockPages: state.unlockPages.length,
    logged: state.logged,
  };
}

const cases = {
  plain: () => launch(),
  // "Move tab to profile" (the engine's openTabsInProfile): the person chose that profile for these addresses.
  moved_running: () => launch({ urls: ["https://example.org/a", "https://example.org/b"] }),
  moved_cold: () => launch({ running: false, urls: ["https://example.org/moved"] }),
  moved_unlocked: () => launch({ lock: "unlocked", urls: ["https://example.org/moved"] }),
  locked: () => launch({ lock: "locked", urls: ["https://example.org/moved"] }),
  unreadable: () => launch({ lock: "unreadable" }),
  agent_plain: () => launch({ driven: true }),
  agent_unlocked: () => launch({ driven: true, lock: "unlocked", urls: ["https://example.org/moved"] }),
  agent_locked: () => launch({ driven: true, lock: "locked", urls: ["https://example.org/moved"] }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
