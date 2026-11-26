// Runs NulavioRouting.openIn (browser/shell/modules/NulavioRouting.sys.mjs: the link menu's "Open link in profile",
// the ask and blocked pages' choices, the held-back address after an unlock) against stand-ins for the engine's
// profile service, the lock state and the agent's environment, and prints, as JSON, what each case did: the
// command lines it sent to a running instance or started a new engine with, and its answer or error code. Then the
// command line it sent is handed to the receiving side (NulavioRouting.handleCommandLine), to show whether that
// profile tracks the tab as a routed arrival (the band's "Aberto pela sua regra" notice, D-UX19) or not. Used by
// tests/unit/test_routing_open_in.py; the real engine is exercised by tests/integration/test_routing.py.
//
//     node tests/lib/routing_open_in_driver.mjs <NulavioRouting module> <NulavioRouter module>

import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// -- stand-ins for what the engine and the other Shell modules give the module ------------------------

const state = { driven: false, lock: "plain", running: true };

const profiles = new Map([
  [1, { id: 1, path: "/profiles/current" }],
  [2, { id: 2, path: "/profiles/other" }],
]);

const service = {
  currentProfile: profiles.get(1),
  initialized: true,
  async init() {},
  async getProfile(id) {
    return profiles.get(id) ?? null;
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
  profileLockState: async () => state.lock,
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

// What the receiving engine shows of its windows: one open window whose tab strip the arrival tracking listens to.
const tabStrip = {
  addEventListener(type) {
    state.listened.push(type);
  },
  removeEventListener() {},
};
const windows = [{ closed: false, gBrowser: { tabContainer: tabStrip } }];

const uri = spec => {
  const url = new URL(spec);
  return { scheme: url.protocol.slice(0, -1), spec: url.href };
};

class FileURL {}

globalThis.Ci = {
  nsIFileURL: FileURL,
  nsITimer: { TYPE_ONE_SHOT: 0 },
  nsICommandLine: { STATE_INITIAL_LAUNCH: 0, STATE_REMOTE_AUTO: 1 },
};
globalThis.Cc = { "@mozilla.org/timer;1": { createInstance: () => ({ initWithCallback() {} }) } };
globalThis.Services = {
  io: { newURI: uri },
  uriFixup: { FIXUP_FLAG_FIX_SCHEME_TYPOS: 0, getFixupURIInfo: value => ({ preferredURI: uri(value) }) },
  prefs: {
    getBoolPref: (_name, fallback) => fallback,
    getIntPref: (_name, fallback) => fallback,
    getStringPref: (_name, fallback) => fallback,
  },
  wm: {
    getEnumerator(type) {
      state.enumerated.push(type);
      return windows;
    },
  },
  obs: {
    addObserver(_observer, topic) {
      state.observed.push(topic);
    },
    removeObserver() {},
  },
};

/** The engine's nsICommandLine for a command line the remote service delivered, as far as the module uses it. */
function commandLine(args) {
  const list = [...args];
  const at = name => list.findIndex(a => a === `-${name}` || a === `--${name}`);
  return {
    state: Ci.nsICommandLine.STATE_REMOTE_AUTO,
    get length() {
      return list.length;
    },
    getArgument: i => list[i],
    handleFlag(name) {
      const i = at(name);
      if (i < 0) {
        return false;
      }
      list.splice(i, 1);
      return true;
    },
    handleFlagWithParam(name) {
      const i = at(name);
      if (i < 0) {
        return null;
      }
      if (i + 1 >= list.length || list[i + 1].startsWith("-")) {
        throw new Error("missing parameter");
      }
      const [, value] = list.splice(i, 2);
      return value;
    },
    removeArguments(start, end) {
      list.splice(start, end - start + 1);
    },
    resolveURI: value => uri(value),
    left: list,
  };
}

// The module imports NulavioRouter by its resource:// address, which only the engine resolves: point that one
// import at the file and load the module from memory.
const source = readFileSync(process.argv[2], "utf-8");
const routerImport = 'from "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs"';
if (source.split(routerImport).length !== 2) {
  throw new Error("NulavioRouting no longer imports NulavioRouter once by its resource:// address");
}
const routerUrl = pathToFileURL(process.argv[3]).href;
const loaded = source.replace(routerImport, `from ${JSON.stringify(routerUrl)}`);
const { ROUTED_FLAG, ROUTE_BY_FLAG } = await import(routerUrl);
let NulavioRouting;
try {
  ({ NulavioRouting } = await import(`data:text/javascript;base64,${Buffer.from(loaded).toString("base64")}`));
} catch (e) {
  // A stack here would print the whole module as its address.
  process.stderr.write(`NulavioRouting did not load: ${e?.name}: ${e?.message}\n`);
  process.exit(1);
}

function reset(conditions = {}) {
  Object.assign(state, { driven: false, lock: "plain", running: true }, conditions, {
    sent: [],
    started: [],
    enumerated: [],
    observed: [],
    listened: [],
  });
}

/** openIn in the given conditions: what it sent or started, and what it answered. */
async function openIn(profileId, url, conditions = {}) {
  reset(conditions);
  let answer = null;
  let error = null;
  try {
    answer = await NulavioRouting.openIn(profileId, url);
  } catch (e) {
    error = e?.code ?? String(e);
  }
  return { answer, error, sent: state.sent, started: state.started };
}

/** The receiving profile's handler for a command line: what it left for the browser, and whether it tracks arrivals. */
function receive(args) {
  reset();
  const cmdLine = commandLine(args);
  NulavioRouting.handleCommandLine(cmdLine);
  return {
    left: cmdLine.left,
    tracked: state.enumerated.length > 0 || state.observed.length > 0,
    listened: state.listened,
  };
}

const results = {
  running: await openIn(2, "https://bank.example/page"),
  cold: await openIn(2, "https://bank.example/page", { running: false }),
  unlocked: await openIn(2, "https://bank.example/page", { lock: "unlocked" }),
  current: await openIn(1, "https://bank.example/page"),
  locked: await openIn(2, "https://bank.example/page", { lock: "locked" }),
  agent: await openIn(2, "https://bank.example/page", { driven: true }),
  not_web: await openIn(2, "file:///etc/passwd"),
};
const link = ["-new-tab", "https://bank.example/page"];
results.received = {
  // What openIn sent, as the other profile's engine receives it.
  open_in: receive(results.running.sent[0]?.args ?? []),
  // What a rule (no marker) and the default destination ("default") send: both are tracked, for their notices.
  rule: receive([`--${ROUTED_FLAG}`, ...link]),
  default: receive([`--${ROUTED_FLAG}`, `--${ROUTE_BY_FLAG}`, "default", ...link]),
};
process.stdout.write(JSON.stringify(results));
