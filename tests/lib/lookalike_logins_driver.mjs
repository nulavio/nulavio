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
const SHOWN = { site: "paypa1.example", similar: "paypal.example" }; // the pair checkLogin() gives the warning page
const OTHER = "https://examp1e.example/login"; // imitates example.example
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

/** The engine's notice that the saved logins changed. */
function changed() {
  for (const fn of observers.get("passwordmgr-storage-changed") ?? []) {
    fn();
  }
}

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
        .dismissFor(LOOKALIKE, { ...SHOWN, back: true, browser })
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
    const answer = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, back: true, browser }).catch(e => ({ threw: e.code }));
    return result(store, { answer, remembered: passwords.listConfirmed().length });
  },
  // "Continue" remembers the pair the warning showed, as checkLogin() gave it to the page.
  dismiss_shown_pair: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const shown = await check(passwords);
    const answer = await passwords.dismissFor(LOOKALIKE, { site: shown.site, similar: shown.similar });
    return result(store, { answer, confirmed: passwords.listConfirmed(), after: await check(passwords) });
  },
  // The saved logins change while the warning is open, so the address now imitates another saved site: the pair the
  // warning showed is not remembered, and neither is the pair found now.
  dismiss_pair_changed: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const shown = await check(passwords);
    store.origins = ["https://paypa.example"];
    changed();
    const now = await check(passwords);
    const answer = await passwords.dismissFor(LOOKALIKE, { site: shown.site, similar: shown.similar });
    return result(store, { shown, now, answer, confirmed: passwords.listConfirmed() });
  },
  // The saved login is removed while the warning is open: no pair is left, nothing is remembered.
  dismiss_no_pair_left: async () => {
    const store = loginManager();
    const passwords = await module(store);
    await check(passwords);
    store.origins = [];
    changed();
    const answer = await passwords.dismissFor(LOOKALIKE, SHOWN);
    return result(store, { answer, confirmed: passwords.listConfirmed() });
  },
  // A pair the warning never showed (a caller naming its own, or none) is never remembered.
  dismiss_other_pair: async () => {
    const store = loginManager({ origins: ["https://paypal.example", "https://example.example"] });
    const passwords = await module(store);
    const answers = {
      other_similar: await passwords.dismissFor(LOOKALIKE, { site: SHOWN.site, similar: "example.example" }),
      other_site: await passwords.dismissFor(LOOKALIKE, { site: "evil.example", similar: SHOWN.similar }),
      no_pair: await passwords.dismissFor(LOOKALIKE),
      not_strings: await passwords.dismissFor(LOOKALIKE, { site: ["paypa1.example"], similar: { x: 1 } }),
    };
    return result(store, { ...answers, confirmed: passwords.listConfirmed() });
  },
  // The same pair already confirmed (the same warning open in another tab): still the pair shown, kept once.
  dismiss_already_confirmed: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const first = await passwords.dismissFor(LOOKALIKE, SHOWN);
    const again = await passwords.dismissFor(LOOKALIKE, SHOWN);
    return result(store, { first, again, confirmed: passwords.listConfirmed() });
  },
  // Continue on a pair already confirmed (the same warning open in another tab) after another pair was confirmed: the
  // list keeps its order (Settings shows the newest first).
  dismiss_already_confirmed_keeps_order: async () => {
    const store = loginManager({ origins: ["https://paypal.example", "https://example.example"] });
    const passwords = await module(store);
    const first = await passwords.dismissFor(LOOKALIKE, SHOWN);
    const other = await passwords.dismissFor(OTHER, { site: "examp1e.example", similar: "example.example" });
    const again = await passwords.dismissFor(LOOKALIKE, SHOWN);
    return result(store, { first, other, again, confirmed: passwords.listConfirmed() });
  },
  // The saved logins change during every read of a Continue, and the last change removes the login: the read it
  // answers with still has that login, but the saved logins no longer give the pair, so nothing is remembered.
  dismiss_after_a_burst_of_changes: async () => {
    const store = loginManager();
    const passwords = await module(store);
    let reads = 0;
    store.onRead = () => {
      if (++reads === 3) {
        store.origins = [];
      }
      changed();
    };
    const answer = await passwords.dismissFor(LOOKALIKE, SHOWN);
    store.onRead = null;
    return result(store, { answer, confirmed: passwords.listConfirmed(), after: await check(passwords) });
  },
  // The saved logins change (the login is removed) `hops` microtasks after a Continue starts, from a list read before:
  // for each `hops`, whether Continue answered dismissed and whether the pair was already saved when they changed. It
  // may remember the pair only if it saved it before the change.
  dismiss_while_the_logins_change: async () => {
    const runs = [];
    for (let hops = 0; hops < 8; hops++) {
      const store = loginManager();
      const passwords = await module(store);
      await check(passwords); // the saved logins are read and kept
      let savedBeforeChange = null;
      let wait = Promise.resolve();
      for (let i = 0; i < hops; i++) {
        wait = wait.then(() => {});
      }
      const pending = passwords.dismissFor(LOOKALIKE, SHOWN);
      wait.then(() => {
        savedBeforeChange = prefs.size > 0;
        store.origins = [];
        changed();
      });
      const answer = await pending;
      await flush();
      runs.push({ dismissed: answer.dismissed, savedBeforeChange, confirmed: passwords.listConfirmed().length });
    }
    return { runs };
  },
  // While the saved logins are read for a Continue that goes back, the tab moves to another entry of its history (a
  // fragment) and the saved logins change so the address imitates another site: the tab has left the warning, which
  // says so first (no way back), not that the pair changed.
  dismiss_back_left_and_pair_changed: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const browser = tab(3, WARNING);
    passwords.bindWarning(browser, { index: 3, url: WARNING });
    store.onRead = () => {
      store.onRead = null;
      at(browser, 4, `${WARNING}#x`);
      store.origins = ["https://paypa.example"];
      changed();
    };
    const answer = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, back: true, browser }).catch(e => ({ threw: e.code }));
    return result(store, { answer, remembered: passwords.listConfirmed().length });
  },
  // #652: "Continue" in a private window. Nothing is written to the profile (prefs.js) or listed in Settings; the pair
  // is not warned again in private windows only, until the engine says the last private window closed.
  dismiss_in_private: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const inPrivate = () => passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    const shown = await inPrivate();
    const answer = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true });
    const saved = { prefs: [...prefs.keys()], confirmed: passwords.listConfirmed() };
    const after = { private: await inPrivate(), normal: await check(passwords) };
    const again = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true }); // the same warning in another tab
    for (const fn of observers.get("last-pb-context-exited") ?? []) {
      fn();
    }
    const closed = await inPrivate();
    return result(store, { shown, answer, again, saved, after, closed, prefs: [...prefs.keys()] });
  },
  // In a private window, "Continue" that goes back keeps the binding of the warning to its tab, and keeps nothing in
  // the profile.
  dismiss_in_private_back: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const unbound = await passwords
      .dismissFor(LOOKALIKE, { ...SHOWN, back: true, browser: tab(1, WARNING), inPrivate: true })
      .catch(e => ({ threw: e.code }));
    const unboundAfter = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    const browser = tab(3, WARNING);
    passwords.bindWarning(browser, { index: 3, url: WARNING });
    const bound = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, back: true, browser, inPrivate: true });
    const after = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    return result(store, { unbound, unboundAfter, bound, after, prefs: [...prefs.keys()], confirmed: passwords.listConfirmed() });
  },
  // In a private window, the pair shown is still checked: another pair, or none left, keeps nothing.
  dismiss_in_private_other_pair: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const other = await passwords.dismissFor(LOOKALIKE, { site: SHOWN.site, similar: "example.example", inPrivate: true });
    store.origins = [];
    changed();
    const none = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true });
    store.origins = ["https://paypal.example"];
    changed();
    const after = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    return result(store, { other, none, after, prefs: [...prefs.keys()] });
  },
  // The last private window closes while a private "Continue" reads the saved logins: nothing is kept, so the next
  // private window is warned again. First with nothing kept before, then after a pair was kept and the logins changed.
  dismiss_in_private_ended_during_read: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const ended = () => {
      for (const fn of observers.get("last-pb-context-exited") ?? []) {
        fn();
      }
    };
    store.onRead = ended;
    const first = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true });
    store.onRead = null;
    const firstAfter = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    const kept = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true });
    changed();
    store.onRead = ended;
    const second = await passwords.dismissFor(LOOKALIKE, { ...SHOWN, inPrivate: true });
    store.onRead = null;
    const secondAfter = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    return result(store, { first, firstAfter, kept, second, secondAfter, prefs: [...prefs.keys()] });
  },
  // Many pairs confirmed in one private session (more than the profile's 200): none is dropped before the last private
  // window closes, as the page says, so the first one is still not warned.
  dismiss_in_private_many: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const dismissed = [];
    for (let n = 0; n <= 200; n++) {
      const answer = await passwords.dismissFor(`https://paypal-login.p${n}.example/`, {
        site: `p${n}.example`,
        similar: "paypal.example",
        inPrivate: true,
      });
      dismissed.push(answer.dismissed);
    }
    const first = await passwords.checkLogin("https://paypal-login.p0.example/", { inPrivate: true });
    const last = await passwords.checkLogin("https://paypal-login.p200.example/", { inPrivate: true });
    return result(store, { kept: dismissed.filter(Boolean).length, first, last, prefs: [...prefs.keys()] });
  },
  // A pair confirmed in a normal window (kept in the profile) is not warned in a private window either.
  dismiss_in_normal_counts_in_private: async () => {
    const store = loginManager();
    const passwords = await module(store);
    const answer = await passwords.dismissFor(LOOKALIKE, SHOWN);
    const inPrivate = await passwords.checkLogin(LOOKALIKE, { inPrivate: true });
    return result(store, { answer, inPrivate, confirmed: passwords.listConfirmed() });
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
    const answer = await passwords.dismissFor(LOOKALIKE, SHOWN).catch(e => ({ threw: e.message }));
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
