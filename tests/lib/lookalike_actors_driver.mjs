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
    this.scheme = url.protocol.slice(0, -1);
    this.host = url.hostname;
    this.hostPort = url.host;
    // nsIURI: a host-based address's scheme://host:port; about:, data: and blob: have none of their own.
    this.prePath = url.host ? `${url.protocol}//${url.host}` : url.protocol;
  }
  schemeIs(scheme) {
    return this.scheme === scheme;
  }
}

/**
 * The engine's principals, by kind: "content <address>" (a site's, or an extension's moz-extension://),
 * "null" (an opaque origin: a sandboxed frame, a data: address), "system" or "expanded".
 */
function principal(kind) {
  const [type, address] = kind.split(" ");
  const uri = address ? new URI(address) : null;
  return {
    isContentPrincipal: type === "content",
    isNullPrincipal: type === "null",
    isSystemPrincipal: type === "system",
    isExpandedPrincipal: type === "expanded",
    schemeIs: scheme => type === "content" && uri.schemeIs(scheme),
    // A content principal's address is its document's; exposablePrePath is scheme://host:port without user:pass.
    URI: uri,
    exposablePrePath: uri?.prePath ?? "",
  };
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

const LOOKALIKES = new Map([
  ["paypa1.example", "paypal.example"],
  ["paypa1-login.example", "paypal.example"],
]);

/**
 * A document of the tab: its address and its principal (by default the content principal of its own address;
 * about:blank and about:srcdoc take one from the document that made them, and a sandboxed one has a null one).
 */
function doc(address, kind = /^https?:|^moz-extension:/.test(address) ? `content ${address}` : "null") {
  return { address, kind };
}

/**
 * The engine's browsing contexts of one tab, from its page (`docs[0]`) down to the frame that holds the
 * field (the last). As in the parent process: each context's window global (WindowGlobalParent) has the
 * document's address and principal; only the tab's page has an embedder element (the tab's browser); a
 * frame's embedder is in the page's process.
 */
function tab(docs, loads) {
  const contexts = [];
  for (const [i, { address, kind }] of docs.entries()) {
    const context = { parent: contexts[i - 1] ?? null, embedderElement: null };
    context.top = contexts[0] ?? context;
    context.parentWindowContext = context.parent?.currentWindowGlobal ?? null;
    context.currentWindowGlobal = {
      documentURI: new URI(address),
      documentPrincipal: principal(kind),
      isCurrentGlobal: true,
      browsingContext: context,
    };
    contexts.push(context);
  }
  const browser = { browsingContext: contexts[0], loadURI: uri => loads.push(uri.spec) };
  contexts[0].embedderElement = browser;
  return { contexts, browser };
}

/** The tab's page now shows another document, in the same browsing context (as without the back-forward cache). */
function navigateTop(contexts, address) {
  for (const context of contexts) {
    context.currentWindowGlobal.isCurrentGlobal = false;
  }
  contexts[0].currentWindowGlobal = {
    documentURI: new URI(address),
    documentPrincipal: principal(`content ${address}`),
    isCurrentGlobal: true,
    browsingContext: contexts[0],
  };
}

/**
 * One check for a password field in the last of `docs` (by default a top document at the look-alike address).
 * `during(state)` runs while the check of the `duringAt`-th address waits, and may change what the engine
 * reports afterwards (a document's address, the tab's current document, the actor). The module finds the
 * hosts in LOOKALIKES suspicious (none with `suspicious: false`), or compares nothing with `locked`.
 */
async function parent({
  address = "https://paypa1.example/login",
  docs = [doc(address)],
  suspicious = true,
  locked = false,
  during = () => {},
  duringAt = 0,
} = {}) {
  const loads = [];
  const { contexts, browser } = tab(docs, loads);
  const field = contexts.at(-1);
  const actor = new NulavioLookalikeParent();
  actor.globalState = field.currentWindowGlobal;
  const asked = [];
  passwords = {
    checkLogin: async url => {
      const n = asked.push(url) - 1;
      await flush();
      if (n === duringAt) {
        during({ actor, browser, context: field, contexts });
      }
      await flush();
      const similar = suspicious && LOOKALIKES.get(new URL(url).hostname);
      if (locked) {
        return { suspicious: false, locked: true };
      }
      return similar ? { suspicious: true, site: new URL(url).hostname, similar } : { suspicious: false };
    },
  };
  let decided;
  try {
    decided = await actor.receiveMessage({ name: "PasswordFieldFocused" });
  } catch (e) {
    decided = `threw ${e.message}`;
  }
  const warning = loads[0] ?? null;
  const query = warning ? new URLSearchParams(warning.split("?")[1]) : null;
  return {
    checked: asked[0] ?? null,
    asked,
    warned: loads.length === 1,
    warning,
    url: query?.get("url") ?? null,
    in: query?.get("in") ?? null,
    decided: decided ?? null,
  };
}

const REAL = "https://paypal.example/account";
const FAKE = "https://paypa1.example/login";

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
        browser.browsingContext = { parent: null };
      },
    }),
  // The tab shows another browsing context, even if this global still says it is current.
  parent_tab_shows_another_context: () => parent({ during: ({ browser }) => (browser.browsingContext = { parent: null }) }),
  // The document's actor is gone (the page was unloaded).
  parent_actor_gone: () => parent({ during: ({ actor }) => (actor.globalState = null) }),
  // Never the case for a change inside one document; checked all the same.
  parent_other_origin: () =>
    parent({ during: ({ actor }) => (actor.globalState.documentURI = new URI("https://paypal.example/login")) }),

  // Fields in frames: the field's own document is checked first, then each document around it up to the tab's page.
  // A frame on the look-alike site inside a page of another site.
  frame_lookalike_in_a_real_page: () => parent({ docs: [doc(REAL), doc(FAKE)] }),
  // about:blank and about:srcdoc have no address of their own: the site of their principal is checked.
  frame_blank_with_a_lookalike_principal: () =>
    parent({ docs: [doc("https://news.example/"), doc("about:blank", `content ${FAKE}`)] }),
  frame_srcdoc_inside_a_lookalike_frame: () =>
    parent({ docs: [doc(REAL), doc(FAKE), doc("about:srcdoc", `content ${FAKE}`)] }),
  // A blob: document has the site of the page that made it.
  frame_blob_with_a_lookalike_principal: () =>
    parent({ docs: [doc(REAL), doc("blob:https://paypa1.example/6a0e", `content ${FAKE}`)] }),
  // A sandboxed frame: its own address counts, whatever its principal.
  frame_sandboxed_on_the_lookalike_site: () => parent({ docs: [doc(REAL), doc(FAKE, "null")] }),
  // A sandboxed srcdoc or a data: frame has no site of its own: the documents around it decide.
  frame_sandboxed_srcdoc_in_a_real_page: () => parent({ docs: [doc(REAL), doc("about:srcdoc", "null")] }),
  frame_data_in_a_lookalike_page: () => parent({ docs: [doc(FAKE), doc("data:text/html,x", "null")] }),
  frame_data_in_a_lookalike_frame: () =>
    parent({ docs: [doc(REAL), doc(FAKE), doc("data:text/html,x", "null")] }),
  // A look-alike in the middle: a frame of another site inside it holds the field.
  frame_nested_lookalike_in_the_middle: () =>
    parent({ docs: [doc(REAL), doc(FAKE), doc("https://widgets.example/login")] }),
  // Two look-alike sites: the one nearest the field decides.
  frame_nearest_lookalike_decides: () =>
    parent({ docs: [doc(FAKE), doc("https://paypa1-login.example/form")] }),
  // A frame of another site on a real page: nothing to warn.
  frame_real_in_a_real_page: () => parent({ docs: [doc(REAL), doc("https://widgets.example/login")] }),
  // Addresses the engine does not give as a site: the system's, an expanded principal's, an extension's.
  frame_no_site_anywhere: () =>
    parent({
      docs: [
        doc("about:blank", "system"),
        doc("about:blank", "expanded"),
        doc("moz-extension://4b1d/unlock.html"),
        doc("about:srcdoc", "content moz-extension://4b1d/unlock.html"),
      ],
    }),
  // A Primary Password not yet entered decides nothing, however many sites there were to check.
  frame_primary_password_locked: () => parent({ docs: [doc(REAL), doc(FAKE)], locked: true }),
  // While the check waits, the tab's page goes to another document: the frame is not the tab's any more.
  frame_tab_page_navigated: () =>
    parent({ docs: [doc(REAL), doc(FAKE)], during: ({ contexts }) => navigateTop(contexts, "https://news.example/") }),
  // The same, while the second check (of the page around the field) waits.
  frame_tab_page_navigated_during_a_later_check: () =>
    parent({
      docs: [doc(FAKE), doc("https://widgets.example/login")],
      duringAt: 1,
      during: ({ contexts }) => navigateTop(contexts, "https://news.example/"),
    }),
  // The tab's page is another document while this frame's global still says it is current.
  frame_tab_page_changed_only_at_the_top: () =>
    parent({
      docs: [doc(REAL), doc(FAKE)],
      during: ({ contexts }) => {
        contexts[0].currentWindowGlobal = { ...contexts[0].currentWindowGlobal, documentURI: new URI(REAL) };
      },
    }),
  // The tab shows another browsing context.
  frame_tab_shows_another_context: () =>
    parent({ docs: [doc(REAL), doc(FAKE)], during: ({ browser }) => (browser.browsingContext = { parent: null }) }),
  // The frame's actor is gone (the frame was removed or went elsewhere).
  frame_actor_gone: () => parent({ docs: [doc(REAL), doc(FAKE)], during: ({ actor }) => (actor.globalState = null) }),
  // The about:blank frame was given another site's principal while the check waited.
  frame_blank_other_site: () =>
    parent({
      docs: [doc(REAL), doc("about:blank", `content ${FAKE}`)],
      during: ({ context }) => (context.currentWindowGlobal.documentPrincipal = principal(`content ${REAL}`)),
    }),
  // The tab's page has no site's address (a sandboxed about:blank page).
  frame_tab_page_without_a_site: () => parent({ docs: [doc("about:blank", "null"), doc(FAKE)] }),
  // A field in a frame finds the tab's page a look-alike, and the page changes its address inside the document while
  // the check waits: the page's address as checked, and "continue" goes back (to where the page is now).
  frame_finds_the_tab_page_after_replace_state: () =>
    parent({
      docs: [doc(FAKE), doc("https://widgets.example/login")],
      duringAt: 1,
      during: ({ contexts }) => (contexts[0].currentWindowGlobal.documentURI = new URI(`${FAKE}?step=2#top`)),
    }),
  // A frame's address with a port, a query and a fragment: only its origin goes in the warning's address.
  frame_address_with_a_query: () =>
    parent({ docs: [doc(REAL), doc("https://paypa1.example:8443/login?token=s3cret&state=x#frag")] }),
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
