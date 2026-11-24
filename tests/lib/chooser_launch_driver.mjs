// Runs the chooser's check before a launch (beforeLaunch, in browser/shell/chooser/chooser.mjs, which engine patch
// 0011 calls before every launch from about:profilemanager) against stand-ins for the engine, the Vault helper, the
// profile's lock state, the agent's environment and the chooser's document, and prints, as JSON, what each case did:
// what beforeLaunch answered, which dialog it showed, whether the profile's lock state was read and what the Vault
// helper was asked. Used by tests/unit/test_profiles_launch.py; the real chooser is exercised by
// tests/integration/test_profile_chooser.py.
//
//     node tests/lib/chooser_launch_driver.mjs <chooser.mjs>

import { pathToFileURL } from "node:url";

const state = { driven: false, lock: "plain", reads: 0, helper: [], dialogs: [], logged: [] };

// -- a document just large enough for the chooser's dialogs ------------------------------------------------------

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.attributes = new Map();
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.style = {};
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.parent = null;
  }
  get id() {
    return this.attributes.get("id") ?? "";
  }
  get hidden() {
    return this.attributes.has("hidden");
  }
  set hidden(on) {
    if (on) {
      this.attributes.set("hidden", "");
    } else {
      this.attributes.delete("hidden");
    }
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  append(...nodes) {
    for (const node of nodes) {
      if (node instanceof Node) {
        node.parent = this;
        this.children.push(node);
      }
    }
  }
  addEventListener(type, listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter(l => l !== listener));
  }
  click() {
    for (const listener of this.listeners.get("click") ?? []) {
      listener({ preventDefault() {} });
    }
  }
  *all() {
    for (const child of this.children) {
      yield child;
      yield* child.all();
    }
  }
  matches(selector) {
    return selector.split(",").some(one => {
      const s = one.trim();
      return s.startsWith("#") ? this.id === s.slice(1) : this.tagName === s;
    });
  }
  querySelector(selector) {
    return [...this.all()].find(node => node.matches(selector)) ?? null;
  }
  querySelectorAll(selector) {
    return [...this.all()].filter(node => node.matches(selector));
  }
  getElementById(id) {
    return this.querySelector(`#${id}`);
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
  remove() {
    if (this.parent) {
      this.parent.children = this.parent.children.filter(node => node !== this);
    }
  }
  focus() {}
}

function makeDocument() {
  const document = new Node("#document");
  document.head = new Node("head");
  document.body = new Node("body");
  document.append(document.head, document.body);
  document.createElement = tag => new Node(tag);
  // A dialog shown: recorded, then its cancel button pressed (the person goes back), so beforeLaunch can answer.
  const append = document.body.append.bind(document.body);
  document.body.append = (...nodes) => {
    append(...nodes);
    for (const dialog of nodes) {
      state.dialogs.push({
        headline: dialog.querySelector("h2")?.textContent ?? null,
        password: Boolean(dialog.querySelector("#nulavio-unlock-password")),
      });
      setTimeout(() => dialog.querySelector("#nulavio-unlock-cancel")?.click(), 0);
    }
  };
  return document;
}

// -- stand-ins for what the engine and the Shell's modules give the chooser ---------------------------------------

const modules = {
  "resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs": {
    helper: async request => {
      state.helper.push(request.op);
      if (request.op === "status") {
        return { encrypted: true, locked: true, methods: [{ method: "password" }, { method: "recovery-code" }] };
      }
      throw Object.assign(new Error("not here"), { code: "helper-failed" });
    },
  },
  "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs": {
    PLAIN: "plain",
    LOCKED: "locked",
    UNLOCKED: "unlocked",
    profileLockState: async () => {
      state.reads += 1;
      return state.lock;
    },
  },
  "resource://builtin-addons/nulavio-shell/modules/NulavioAgentNetwork.sys.mjs": {
    NulavioAgentNetwork: { driven: () => state.driven },
  },
};

globalThis.ChromeUtils = {
  importESModule(url) {
    if (!(url in modules)) {
      throw new Error(`no stand-in for ${url}`);
    }
    return modules[url];
  },
};
globalThis.L10nRegistry = { getInstance: () => ({ hasSource: () => true, registerSources() {} }) };
globalThis.L10nFileSource = class {};
globalThis.Localization = class {
  async formatValues(ids) {
    return ids.map(({ id }) => id);
  }
  async formatValue(id) {
    return id;
  }
};
globalThis.IOUtils = { exists: async () => false, readUTF8: async () => "" };
globalThis.PathUtils = {
  join: (...parts) => parts.join("/"),
  parent: path => path.split("/").slice(0, -1).join("/"),
  filename: path => path.split("/").pop(),
};
console.error = (...args) => {
  state.logged.push(args.map(a => a?.code ?? String(a)).join(" "));
};

const { beforeLaunch } = await import(pathToFileURL(process.argv[2]).href);

const profile = {
  id: "other",
  name: "Other",
  path: "/profiles/other",
  theme: {},
  getAvatarURL: async () => "chrome://avatar",
};

/** One launch from the chooser, in the given conditions. */
async function launch({ driven = false, lock = "plain" } = {}) {
  Object.assign(state, { driven, lock, reads: 0, helper: [], dialogs: [], logged: [] });
  const answer = await beforeLaunch(makeDocument(), profile);
  return { answer, reads: state.reads, helper: state.helper, dialogs: state.dialogs, logged: state.logged };
}

const cases = {
  plain: () => launch(),
  locked: () => launch({ lock: "locked" }),
  agent_plain: () => launch({ driven: true }),
  agent_locked: () => launch({ driven: true, lock: "locked" }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
