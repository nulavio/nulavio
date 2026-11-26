// Runs the look-alike login check of browser/shell/modules/NulavioPasswords.sys.mjs against a stand-in for
// the engine's login manager, and prints, as JSON, what each case answered and how often the saved logins
// were read. A read of the logins decrypts them: with a Primary Password set and not yet entered, the
// stand-in counts that as the Primary Password prompt and cancels it, as the person would (#708).
// Used by tests/unit/test_lookalike_logins.py; the real engine runs the check in tests/integration/test_passwords.py.
//
//     node tests/lib/lookalike_logins_driver.mjs <NulavioPasswords module>

import { pathToFileURL } from "node:url";

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

/** The login manager: `primaryPassword` set and not `entered` is a locked token; `ready` is the store's start. */
function loginManager({ origins = ["https://paypal.example"], primaryPassword = false, ready = true } = {}) {
  const store = { origins, primaryPassword, entered: false, reads: 0, prompts: 0 };
  let start;
  const started = ready ? Promise.resolve() : new Promise(resolve => (start = resolve));
  store.start = () => {
    store.ready = true;
    start?.();
  };
  store.ready = ready;
  store.logins = {
    initializationPromise: started,
    // nsILoginManager: false until the store has started (LoginManager.sys.mjs), then whether a read asks nothing.
    get isLoggedIn() {
      return store.ready && (!store.primaryPassword || store.entered);
    },
    async getAllLogins() {
      store.reads++;
      if (!store.origins.length) {
        return []; // the engine decrypts nothing when there is no login
      }
      if (store.primaryPassword && !store.entered) {
        store.prompts++;
        throw new Error("Primary password locked"); // the prompt, cancelled
      }
      const logins = store.origins.map(origin => ({ origin, username: "secret", password: "secret" }));
      store.onRead?.(); // what happens elsewhere while the read is on its way back
      await flush();
      return logins;
    },
  };
  return store;
}

const observers = new Map();
const prefs = new Map();
let current = null;
globalThis.ChromeUtils = { defineESModuleGetters() {} };
globalThis.Services = {
  get logins() {
    return current.logins;
  },
  eTLD: {
    getBaseDomainFromHost: host => host.split(".").slice(-2).join("."),
    getPublicSuffixFromHost: host => host.split(".").at(-1),
  },
  obs: {
    addObserver(fn, topic) {
      observers.set(topic, [...(observers.get(topic) ?? []), fn]);
    },
  },
  prefs: {
    getIntPref: (name, fallback) => (prefs.has(name) ? prefs.get(name) : fallback),
    getStringPref: (name, fallback) => (prefs.has(name) ? prefs.get(name) : fallback),
    setStringPref: (name, value) => prefs.set(name, value),
    clearUserPref: name => prefs.delete(name),
  },
};

let instance = 0;
/** A fresh copy of the module (its saved-site list starts empty) on the login manager `store`. */
async function module(store) {
  current = store;
  observers.clear();
  prefs.clear();
  const url = `${pathToFileURL(process.argv[2]).href}?case=${++instance}`;
  return (await import(url)).NulavioPasswords;
}

const LOOKALIKE = "https://paypa1.example/login";
const WARNING = "moz-extension://shell/passwords/lookalike.html?url=https%3A%2F%2Fpaypa1.example%2F&in=frame";

/** A tab's browser at entry `index` of its session history, showing `address`. */
function tab(index, address) {
  return at({ browsingContext: { sessionHistory: { index } } }, index, address);
}

function at(browser, index, address) {
  browser.browsingContext.sessionHistory.index = index;
  browser.currentURI = { spec: address, specIgnoringRef: address.split("#")[0] };
  return browser;
}

async function check(passwords) {
  try {
    return await passwords.checkLogin(LOOKALIKE);
  } catch (e) {
    return { threw: e.message };
  }
}

const result = (store, extra) => ({ ...extra, reads: store.reads, prompts: store.prompts });

const cases = {
  // No Primary Password: the look-alike of a saved site is found, and the logins are read once.
  no_primary_password: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const first = await check(passwords);
    const again = await check(passwords);
    return result(store, { first, again });
  },
  // A Primary Password not yet entered: nothing is read, so nothing asks for it, and nothing is decided.
  locked: async () => {
    const store = loginManager({ primaryPassword: true });
    const passwords = await module(store);
    const first = await check(passwords);
    const again = await check(passwords);
    return result(store, { first, again });
  },
  // Entered later in the session: the next check reads the logins and finds the look-alike.
  locked_then_entered: async () => {
    const store = loginManager({ primaryPassword: true });
    const passwords = await module(store);
    const locked = await check(passwords);
    store.entered = true;
    const entered = await check(passwords);
    return result(store, { locked, entered });
  },
  // "Continue" that goes back to the tab's page: only from the warning the engine's actor opened in that tab, while
  // the tab still shows that entry of its history (the index it got, and its address without a fragment).
  dismiss_back: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const remembered = () => passwords.listConfirmed().length;
    const dismiss = browser =>
      passwords
        .dismissFor(LOOKALIKE, { back: true, browser })
        .then(answer => ({ ...answer, remembered: remembered() }))
        .catch(e => ({ threw: e.code, remembered: remembered() }));
    const answers = {};
    answers.unbound = await dismiss(tab(1, WARNING)); // a warning another extension opened
    answers.none = await dismiss(null);
    const bound = tab(3, WARNING);
    passwords.bindWarning(bound, { index: 3, url: WARNING });
    const can = {
      bound: passwords.canGoBack(bound),
      fragment: passwords.canGoBack(at(bound, 4, `${WARNING}#x`)), // a same-document entry after the warning
      other_entry: passwords.canGoBack(at(bound, 2, WARNING)),
      other_page: passwords.canGoBack(at(bound, 3, "https://paypal.example/")),
      unbound: passwords.canGoBack(tab(3, WARNING)),
      no_history: passwords.canGoBack({}),
    };
    answers.can = can;
    answers.bound = await dismiss(at(bound, 3, WARNING)); // back at the warning's own entry
    return result(store, answers);
  },
  // The tab leaves the warning while the saved logins are read: nothing is remembered.
  dismiss_back_left_during_the_read: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const browser = tab(3, WARNING);
    passwords.bindWarning(browser, { index: 3, url: WARNING });
    store.onRead = () => at(browser, 4, "https://elsewhere.example/");
    const answer = await passwords.dismissFor(LOOKALIKE, { back: true, browser }).catch(e => ({ threw: e.code }));
    return result(store, { answer, remembered: passwords.listConfirmed().length });
  },
  // Two checks at once (two frames of one tab) share one read of the saved logins.
  concurrent_checks: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const [first, second] = await Promise.all([check(passwords), check(passwords)]);
    return result(store, { first, second });
  },
  // The saved logins change during every read (a burst of changes): a check reads them at most 3 times and answers.
  storage_changed_during_every_read: async () => {
    const store = loginManager();
    const passwords = await module(store);
    let changes = 0;
    store.onRead = () => {
      if (changes++ < 5) {
        for (const fn of observers.get("passwordmgr-storage-changed") ?? []) {
          fn();
        }
      }
    };
    const first = await check(passwords);
    return result(store, { first });
  },
  // A change to the saved logins while they are read: the next check reads them again.
  storage_changed_during_the_read: async () => {
    const store = loginManager();
    const passwords = await module(store);
    store.onRead = () => {
      store.onRead = null;
      store.origins = [];
      for (const fn of observers.get("passwordmgr-storage-changed") ?? []) {
        fn();
      }
    };
    const first = await check(passwords);
    const after = await check(passwords);
    return result(store, { first, after });
  },
  // "Continue anyway" while locked remembers nothing and asks nothing.
  locked_dismiss: async () => {
    const store = loginManager({ primaryPassword: true });
    const passwords = await module(store);
    const answer = await passwords.dismissFor(LOOKALIKE).catch(e => ({ threw: e.message }));
    return result(store, { answer, remembered: prefs.size });
  },
  // A Primary Password set, but no saved login: still nothing read.
  locked_no_logins: async () => {
    const store = loginManager({ primaryPassword: true, origins: [] });
    const passwords = await module(store);
    return result(store, { first: await check(passwords) });
  },
  // The store still starting (isLoggedIn false meanwhile): the check waits for it and then compares.
  store_starting: async () => {
    const store = loginManager({ ready: false });
    const passwords = await module(store);
    const pending = check(passwords);
    await flush();
    store.start();
    return result(store, { first: await pending });
  },
  // A change to the saved logins is read again.
  storage_changed: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const first = await check(passwords);
    store.origins = [];
    for (const fn of observers.get("passwordmgr-storage-changed") ?? []) {
      fn();
    }
    const after = await check(passwords);
    return result(store, { first, after });
  },
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  results[name] = await run();
}
process.stdout.write(JSON.stringify(results));
