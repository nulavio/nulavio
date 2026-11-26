// Runs the look-alike login check's window actors (browser/shell/modules/NulavioLookalike{Child,Parent}.sys.mjs)
// against stand-ins for the engine's actor classes, and prints, as JSON, what each case did: how many
// times the child asked the parent, and whether the parent opened the warning page. Used by
// tests/unit/test_lookalike_actors.py; the real engine is exercised by tests/integration/test_passwords.py.
//
//     node tests/lib/lookalike_actors_driver.mjs <child module> <parent module>

import { pathToFileURL } from "node:url";

// -- stand-ins for what the engine gives the actors -----------------------------------------------

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

globalThis.JSWindowActorChild = class {
  constructor(document, reply) {
    this.document = document;
    this.sent = [];
    this.reply = reply;
  }
  sendQuery(name) {
    this.sent.push(name);
    return this.reply(name);
  }
  sendAsyncMessage(name) {
    this.sent.push(name); // no answer: such a child is never told that the parent did not decide
  }
};

class URI {
  constructor(spec) {
    const url = new URL(spec);
    this.spec = url.href;
    this.prePath = `${url.protocol}//${url.host}`;
  }
}

// The engine's JSWindowActorParent: browsingContext throws once the actor's window global is gone.
globalThis.JSWindowActorParent = class {
  get manager() {
    return this.globalState;
  }
  get browsingContext() {
    if (!this.globalState) {
      throw new Error("InvalidStateError");
    }
    return this.globalState.browsingContext;
  }
};

let passwords = null;
globalThis.ChromeUtils = {
  defineESModuleGetters(lazy) {
    Object.defineProperty(lazy, "NulavioPasswords", { get: () => passwords });
  },
};
globalThis.WebExtensionPolicy = { getByID: () => ({ getURL: path => `moz-extension://shell/${path}` }) };
globalThis.Services = {
  io: { newURI: spec => new URI(spec) },
  scriptSecurityManager: { getSystemPrincipal: () => ({ system: true }) },
};

const { NulavioLookalikeChild } = await import(pathToFileURL(process.argv[2]).href);
const { NulavioLookalikeParent } = await import(pathToFileURL(process.argv[3]).href);

// -- the child ---------------------------------------------------------------------------------------

const password = { localName: "input", type: "password" };
const text = { localName: "input", type: "text" };

/** Events in order: [type, target, the document's transient activation, isTrusted, a held key's repeat]. */
async function child(events, reply = async () => true) {
  const doc = { hasValidTransientUserGestureActivation: false };
  const actor = new NulavioLookalikeChild(doc, reply);
  for (const [type, target, activated, trusted = true, repeat = false] of events) {
    doc.hasValidTransientUserGestureActivation = activated;
    actor.handleEvent({ type, target, isTrusted: trusted, repeat });
    await flush();
  }
  return { asked: actor.sent.length };
}

// -- the parent --------------------------------------------------------------------------------------

function topContext() {
  const context = { parent: null };
  context.top = context;
  return context;
}

/**
 * One check for a document at `address`. `during(state)` runs while checkLogin waits, and may change
 * what the engine reports afterwards (the document's address, the tab's current document, the actor).
 */
async function parent({ address = "https://paypa1.example/login", suspicious = true, locked = false, during = () => {} } = {}) {
  const loads = [];
  const context = topContext();
  const browser = { browsingContext: context, loadURI: uri => loads.push(uri.spec) };
  context.embedderElement = browser;
  const actor = new NulavioLookalikeParent();
  actor.globalState = { documentURI: new URI(address), isCurrentGlobal: true, browsingContext: context };
  let release;
  passwords = {
    checkLogin: url => {
      passwords.asked = url;
      const verdict = suspicious
        ? { suspicious: true, site: "paypa1.example", similar: "paypal.example" }
        : { suspicious: false, ...(locked ? { locked: true } : {}) };
      return new Promise(resolve => (release = () => resolve(verdict)));
    },
  };
  const answer = actor.receiveMessage({ name: "PasswordFieldFocused" });
  await flush();
  during({ actor, browser, context });
  release();
  let decided;
  try {
    decided = await answer;
  } catch (e) {
    decided = `threw ${e.message}`;
  }
  return { checked: passwords.asked, warned: loads.length === 1, warning: loads[0] ?? null, decided: decided ?? null };
}

const cases = {
  // A focus the page gives itself asks nothing; the person's click or key does.
  child_script_focus: () => child([["focusin", password, false]]),
  child_focus_after_input: () => child([["focusin", password, true]]),
  child_script_focus_then_key: () => child([["focusin", password, false], ["keydown", password, true]]),
  child_script_focus_then_click: () => child([["focusin", password, false], ["mousedown", password, true]]),
  // A click or a key is the person's input even when the page has used up the activation.
  child_key_without_activation: () => child([["focusin", password, false], ["keydown", password, false]]),
  child_click_without_activation: () => child([["mousedown", password, false]]),
  // A held key's repeated keydowns in the field ask nothing, with or without the activation.
  child_held_key_repeats: () => child([["focusin", password, false], ["keydown", password, true, true, true], ["keydown", password, false, true, true]]),
  child_untrusted: () => child([["focusin", password, true, false], ["keydown", password, true, false]]),
  child_not_a_password_field: () => child([["focusin", text, true], ["keydown", text, true]]),
  child_other_event: () => child([["input", password, true], ["focus", password, true]]),
  child_once_per_document: () => child([["focusin", password, true], ["keydown", password, true], ["mousedown", password, true]]),
  child_asks_again_when_not_decided: () => {
    let n = 0;
    return child([["focusin", password, true], ["focusin", password, true]], async () => ++n > 1);
  },
  child_not_again_when_the_query_fails: () =>
    child([["focusin", password, true], ["focusin", password, true]], async () => {
      throw new Error("actor destroyed");
    }),

  // The parent.
  parent_warns: () => parent(),
  parent_nothing_to_warn: () => parent({ suspicious: false }),
  // A Primary Password not yet entered: the module compared nothing, so nothing was decided (#708).
  parent_primary_password_locked: () => parent({ suspicious: false, locked: true }),
  // The page changes its address inside the document while the check waits.
  parent_replace_state: () =>
    parent({ during: ({ actor }) => (actor.globalState.documentURI = new URI("https://paypa1.example/elsewhere#x")) }),
  // The tab moved to another page; this one is kept in the back-forward cache.
  parent_tab_moved_on_cached: () =>
    parent({
      during: ({ actor, browser }) => {
        actor.globalState.isCurrentGlobal = false;
        browser.browsingContext = topContext();
      },
    }),
  // The tab shows another browsing context, even if this global still says it is current.
  parent_tab_shows_another_context: () => parent({ during: ({ browser }) => (browser.browsingContext = topContext()) }),
  // The document's actor is gone (the page was unloaded).
  parent_actor_gone: () => parent({ during: ({ actor }) => (actor.globalState = null) }),
  // Never the case for a change inside one document; checked all the same.
  parent_other_origin: () =>
    parent({ during: ({ actor }) => (actor.globalState.documentURI = new URI("https://paypal.example/login")) }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
