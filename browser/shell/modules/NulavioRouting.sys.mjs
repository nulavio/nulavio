/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Smart Profile Routing: links from other applications (M4a), addresses
   typed in the address bar (M4b) and, when the user turns it on, links clicked
   in pages (M5) (docs/adr/0003-nulavio-profiles-and-routing.md,
   docs/security/routing-m5-review.md).

   A link clicked in another application reaches Nulavio as a command line,
   either when it starts or through the engine's remote service. Nulavio's
   command-line handler (browser/branding/nulavio/NulavioCommandLine.sys.mjs)
   runs before the browser's own and calls handleCommandLine(), so a link is
   decided BEFORE any request is made for it:

   - stay: the browser opens it as usual;
   - open-in: it is removed from this command line and sent to the target
     profile (its running instance through the remote service, or a new
     instance through an argument list; never a shell);
   - ask: a local Nulavio page asks, without loading the site;
   - target missing or failing: a local Nulavio page says so, and opening
     here is an explicit choice. A link never silently opens in the wrong
     profile, and no cookie or session ever moves between profiles.

   When this instance has just started, the group's rules may be newer in the
   group store than in this profile's prefs, so web links are held until the
   engine's profile service has loaded them. */

import {
  ENABLED_PREF,
  IN_PAGE_PREF,
  MAX_RULES,
  ROUTED_FLAG,
  RULES_PREF,
  RoutingError,
  decide,
  normalizeHost,
  pageNavigationRefusal,
  parseCommandLine,
  parseRules,
  siteOf,
  validateRule,
} from "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs";

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
  SelectableProfileService: "resource:///modules/profiles/SelectableProfileService.sys.mjs",
});

const SHELL_ID = "shell@nulavio.net";
const GROUPED_PREF = "browser.profiles.created";
const GESTURE_PREF = "dom.user_activation.transient.timeout";

function fail(code, message) {
  throw new RoutingError(code, message);
}

function sleep(ms) {
  return new Promise(resolve => {
    const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    timer.initWithCallback(resolve, ms, Ci.nsITimer.TYPE_ONE_SHOT);
  });
}

function webUrl(url) {
  let uri;
  try {
    uri = Services.io.newURI(String(url));
  } catch {
    fail("invalid-url");
  }
  if (uri.scheme !== "http" && uri.scheme !== "https") {
    fail("invalid-url");
  }
  return uri.spec;
}

class NulavioRoutingClass {
  #listeners = new Set();
  #observing = false;
  #pageWatch = false; // M5: preference observers installed
  #pageObserving = false; // M5: the request observer is installed
  #pageRoutes = new Map(); // M5: inner window id of a page -> when it last had a navigation routed

  // -- rules (shared by every profile of the group) -------------------------

  enabled() {
    return Services.prefs.getBoolPref(ENABLED_PREF, true);
  }

  inPage() {
    return Services.prefs.getBoolPref(IN_PAGE_PREF, false);
  }

  rules() {
    return parseRules(Services.prefs.getStringPref(RULES_PREF, "[]"));
  }

  async #share(pref) {
    // The engine copies tracked prefs to the group store; every profile sees them.
    await lazy.SelectableProfileService.maybeSetupDataStore();
    await lazy.SelectableProfileService.trackPref(pref);
  }

  async #writeRules(rules) {
    Services.prefs.setStringPref(RULES_PREF, JSON.stringify(rules));
    await this.#share(RULES_PREF);
  }

  #requireProfiles() {
    const { available, reason } = lazy.NulavioProfiles.availability();
    if (!available) {
      fail(reason);
    }
  }

  async state() {
    const availability = lazy.NulavioProfiles.availability();
    const { profiles } = availability.available ? await lazy.NulavioProfiles.list() : { profiles: [] };
    const byId = new Map(profiles.map(p => [p.id, p]));
    return {
      ...availability,
      enabled: this.enabled(),
      inPage: this.inPage(),
      rules: this.rules().map(rule => {
        const target = byId.get(rule.profileId);
        let display = rule.value;
        try {
          display = normalizeHost(rule.value).display;
        } catch {}
        return { ...rule, display, profileName: target?.name ?? null, profileColor: target?.color ?? null, missing: rule.action !== "stay" && !target };
      }),
    };
  }

  async setEnabled(enabled) {
    this.#requireProfiles();
    Services.prefs.setBoolPref(ENABLED_PREF, Boolean(enabled));
    await this.#share(ENABLED_PREF);
  }

  /** M5 opt-in: rules also apply to links clicked in pages. */
  async setInPage(enabled) {
    this.#requireProfiles();
    Services.prefs.setBoolPref(IN_PAGE_PREF, Boolean(enabled));
    await this.#share(IN_PAGE_PREF);
  }

  /** Add (or replace) the user's rule for a site. Returns its id. */
  async addRule(input) {
    this.#requireProfiles();
    const rule = validateRule(input);
    if (rule.profileId !== null && !(await lazy.SelectableProfileService.getProfile(rule.profileId))) {
      fail("invalid-profile");
    }
    const rules = this.rules().filter(r => !(r.match === rule.match && r.value === rule.value));
    if (rules.length >= MAX_RULES) {
      fail("too-many-rules");
    }
    const id = Services.uuid.generateUUID().toString().slice(1, -1);
    rules.push({ id, ...rule });
    await this.#writeRules(rules);
    return id;
  }

  async removeRule(id) {
    this.#requireProfiles();
    const rules = this.rules();
    if (!rules.some(r => r.id === id)) {
      fail("not-found");
    }
    await this.#writeRules(rules.filter(r => r.id !== id));
  }

  async setRuleAction(id, action) {
    this.#requireProfiles();
    const rules = this.rules();
    const rule = rules.find(r => r.id === id);
    if (!rule) {
      fail("not-found");
    }
    const updated = validateRule({ site: rule.value, match: rule.match, action, profileId: rule.profileId });
    Object.assign(rule, updated);
    await this.#writeRules(rules);
  }

  /** What routing would do with this URL here (for the toolbar selector). */
  ruleFor(url) {
    const spec = webUrl(url);
    const target = normalizeHost(spec);
    const rules = this.rules();
    const rule =
      rules.find(r => r.match === "host" && r.value === target.host) ??
      (target.registrable ? rules.find(r => r.match === "domain" && r.value === target.registrable) : null) ??
      null;
    return { ...target, rule };
  }

  // -- explicit choices (from Nulavio pages) ----------------------------------

  /** Open a web URL in a profile because the user chose it. Never routed again there. */
  async openIn(profileId, url) {
    const spec = webUrl(url);
    const service = lazy.SelectableProfileService;
    await service.init();
    if (profileId === service.currentProfile?.id) {
      return { action: "current" };
    }
    const profile = await service.getProfile(profileId);
    if (!profile) {
      fail("invalid-profile");
    }
    if ((await lazy.profileLockState(profile.path)) === "locked") {
      fail("locked");
    }
    return { action: this.#launchRouted(profile, spec) };
  }

  #launchRouted(profile, url) {
    const service = lazy.SelectableProfileService;
    const args = [`--${ROUTED_FLAG}`, "-new-tab", url];
    try {
      service.sendCommandLine(profile.path, args, true);
      return "delivered";
    } catch {
      // No running instance of that profile: start one (argument list, no shell).
    }
    service.execProcess(["--profile", profile.path, ...args]);
    return "started";
  }

  // -- command lines ----------------------------------------------------------

  /**
   * Called by Nulavio's command-line handler before the browser's own.
   * Synchronous: it only removes the arguments it takes over; the rest of the
   * work (and any I/O) happens afterwards.
   */
  handleCommandLine(cmdLine) {
    if (cmdLine.handleFlag(ROUTED_FLAG, false)) {
      return; // sent by routing or by an explicit choice: open here
    }
    if (!this.enabled() || !Services.prefs.getBoolPref(GROUPED_PREF, false)) {
      return; // routing off, or a single profile: nothing to route to
    }
    const args = Array.from({ length: cmdLine.length }, (_, i) => cmdLine.getArgument(i));
    const plan = parseCommandLine(args);
    if (!plan.supported) {
      return; // private windows, search, kiosk... are never moved
    }
    const candidates = [];
    for (const item of plan.items) {
      const url = this.#resolve(cmdLine, item.value);
      if (url) {
        candidates.push({ ...item, url });
      }
    }
    if (!candidates.length) {
      return;
    }

    const initial = cmdLine.state === Ci.nsICommandLine.STATE_INITIAL_LAUNCH;
    const service = lazy.SelectableProfileService;
    let take = candidates;
    if (!initial && service.initialized && service.currentProfile) {
      // A running instance has the group's current rules: decide now.
      try {
        const rules = this.rules();
        const current = service.currentProfile.id;
        take = candidates.filter(c => decide({ url: c.url, rules, currentProfileId: current }).action !== "stay");
      } catch (e) {
        console.error("Nulavio routing: decision failed; holding the links", e);
      }
    }
    if (!take.length) {
      return;
    }
    for (const c of [...take].sort((a, b) => b.start - a.start)) {
      cmdLine.removeArguments(c.start, c.end);
    }
    if (!initial && cmdLine.length === 0) {
      cmdLine.preventDefault = true; // no extra empty window in this instance
    }
    this.#dispatch(take.map(c => c.url), { initial }).catch(e => console.error("Nulavio routing: dispatch failed", e));
  }

  /**
   * A navigation the user started in this window (address bar). Synchronous:
   * true means routing took it over and nothing must load here.
   * POST loads, downloads and private windows are never routed.
   */
  routeNavigation({ url, postData = null, where = "current", isPrivate = false, source = "typed" }) {
    if (postData || !["current", "tab", "tabshifted", "window"].includes(where)) {
      return false;
    }
    if (!this.enabled() || !Services.prefs.getBoolPref(GROUPED_PREF, false)) {
      return false;
    }
    const service = lazy.SelectableProfileService;
    if (!service.initialized || !service.currentProfile) {
      return false; // no profile group loaded in this instance yet
    }
    let decision;
    try {
      decision = decide({ url, rules: this.rules(), currentProfileId: service.currentProfile.id, isPrivate });
    } catch (e) {
      console.error("Nulavio routing: decision failed; holding the navigation", e);
      this.#openPage("routing/blocked.html", { u: url, why: "error", src: source }).catch(console.error);
      return true;
    }
    if (decision.action === "stay") {
      return false;
    }
    this.#handOff(url, decision, source).catch(e => {
      console.error("Nulavio routing: could not route a navigation", e);
      this.#openPage("routing/blocked.html", { u: url, why: "error", src: source }).catch(console.error);
    });
    return true;
  }

  // -- links clicked in pages (M5) ------------------------------------------------

  /**
   * Called when the Shell starts. The request observer is installed only while
   * the opt-in, routing and a profile group are all on, so nothing runs per
   * request otherwise. Idempotent (the Shell may restart within one session).
   */
  watchPages() {
    if (!this.#pageWatch) {
      this.#pageWatch = true;
      for (const pref of [IN_PAGE_PREF, ENABLED_PREF, GROUPED_PREF]) {
        Services.prefs.addObserver(pref, this.#pagePrefObserver);
      }
    }
    this.#syncPageObserver();
  }

  unwatchPages() {
    if (this.#pageWatch) {
      this.#pageWatch = false;
      for (const pref of [IN_PAGE_PREF, ENABLED_PREF, GROUPED_PREF]) {
        Services.prefs.removeObserver(pref, this.#pagePrefObserver);
      }
    }
    this.#syncPageObserver();
  }

  #pagePrefObserver = { observe: () => this.#syncPageObserver() };

  #requestObserver = {
    observe: subject => {
      try {
        this.#onOpeningRequest(subject);
      } catch (e) {
        console.error("Nulavio routing: in-page check failed; the page loads here", e);
      }
    },
  };

  #syncPageObserver() {
    const wanted =
      this.#pageWatch && this.inPage() && this.enabled() && Services.prefs.getBoolPref(GROUPED_PREF, false);
    if (wanted && !this.#pageObserving) {
      Services.obs.addObserver(this.#requestObserver, "http-on-opening-request");
    } else if (!wanted && this.#pageObserving) {
      Services.obs.removeObserver(this.#requestObserver, "http-on-opening-request");
      this.#pageRoutes.clear();
    }
    this.#pageObserving = wanted;
  }

  /**
   * The engine announces each new request here, in the parent process, before
   * it is sent; never for redirects. Only top-level document loads that a web
   * page started are considered; everything else returns at once.
   */
  #onOpeningRequest(subject) {
    const channel = subject.QueryInterface(Ci.nsIHttpChannel);
    const loadInfo = channel.loadInfo;
    if (loadInfo.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) {
      return;
    }
    const principal = loadInfo.triggeringPrincipal;
    if (!principal?.isContentPrincipal || !(principal.schemeIs("http") || principal.schemeIs("https"))) {
      return; // the browser, extensions, local files: not a page navigation (M4a/M4b or explicit)
    }
    const service = lazy.SelectableProfileService;
    if (!service.initialized || !service.currentProfile) {
      return;
    }
    const target = loadInfo.browsingContext;
    const source = WindowGlobalParent.getByInnerWindowId(loadInfo.triggeringWindowId);
    const url = channel.URI.spec;
    let sameSite = true;
    try {
      sameSite = siteOf(url) === siteOf(principal.originNoSuffix);
    } catch {}
    const refusal = pageNavigationRefusal({
      isPrivate: loadInfo.originAttributes.privateBrowsingId > 0,
      method: channel.requestMethod,
      isFormSubmission: loadInfo.isFormSubmission,
      isMetaRefresh: loadInfo.isMetaRefresh,
      userGesture: loadInfo.hasValidUserGestureActivation,
      topLevel: Boolean(target) && !target.parent,
      fromTopPage: Boolean(source) && !source.browsingContext.parent && source.documentPrincipal.equals(principal),
      hasOpener: Boolean(target?.opener),
      sameSite,
    });
    if (refusal) {
      return;
    }
    const decision = decide({ url, rules: this.rules(), currentProfileId: service.currentProfile.id });
    if (decision.action === "stay") {
      return;
    }
    // One routed navigation per page and gesture: a page that navigates again
    // within the same gesture window loads here.
    const now = ChromeUtils.now();
    const windowMs = Services.prefs.getIntPref(GESTURE_PREF, 5000);
    for (const [id, at] of this.#pageRoutes) {
      if (now - at >= windowMs) {
        this.#pageRoutes.delete(id);
      }
    }
    if (this.#pageRoutes.has(source.innerWindowId)) {
      return;
    }
    this.#pageRoutes.set(source.innerWindowId, now);

    channel.cancel(Cr.NS_BINDING_ABORTED); // nothing is requested here
    const emptyTab = target !== source.browsingContext && this.#isEmptyTab(target);
    Services.tm.dispatchToMainThread(() => {
      if (emptyTab) {
        this.#closeEmptyTab(target);
      }
      this.#handOff(url, decision, "page").catch(e => {
        console.error("Nulavio routing: could not route a link", e);
        this.#openPage("routing/blocked.html", { u: url, why: "error", src: "page" }).catch(console.error);
      });
    });
  }

  /** A tab that has shown nothing yet: no document but the initial blank one, no history. */
  #isEmptyTab(browsingContext) {
    const page = browsingContext.currentWindowGlobal;
    return (!page || page.isInitialDocument) && !(browsingContext.sessionHistory?.count > 0);
  }

  /** A link that opened a new tab and was routed leaves an empty tab behind: close it. */
  #closeEmptyTab(browsingContext) {
    const browser = browsingContext.embedderElement;
    const windows = [...Services.wm.getEnumerator("navigator:browser")];
    const win = windows.find(w => w.gBrowser?.getTabForBrowser(browser));
    const tab = win?.gBrowser.getTabForBrowser(browser);
    if (!tab || !this.#isEmptyTab(browsingContext) || browser.currentURI?.spec !== "about:blank") {
      return;
    }
    if (win.gBrowser.tabs.length > 1) {
      win.gBrowser.removeTab(tab);
    } else if (windows.length > 1) {
      win.close();
    }
  }

  #resolve(cmdLine, value) {
    try {
      const resolved = cmdLine.resolveURI(value);
      if (resolved instanceof Ci.nsIFileURL) {
        return null; // local files are opened where they were asked for
      }
      const uri = Services.uriFixup.getFixupURIInfo(value, Services.uriFixup.FIXUP_FLAG_FIX_SCHEME_TYPOS).preferredURI;
      return uri && (uri.scheme === "http" || uri.scheme === "https") ? uri.spec : null;
    } catch {
      return null;
    }
  }

  async #dispatch(urls, { initial }) {
    const service = lazy.SelectableProfileService;
    let rules = [];
    let current = null;
    let enabled = true;
    let failed = false;
    try {
      await service.init(); // loads the group's shared prefs, so the rules are current
      rules = this.rules();
      enabled = this.enabled();
      current = service.currentProfile?.id ?? null;
    } catch (e) {
      console.error("Nulavio routing: profile service unavailable", e);
      failed = true;
    }
    for (const url of urls) {
      try {
        await this.#dispatchOne(url, { failed, rules, enabled, current });
      } catch (e) {
        console.error("Nulavio routing: could not route a link", e);
        await this.#openPage("routing/blocked.html", { u: url, why: "error", src: "app" }).catch(console.error);
      }
    }
    if (initial) {
      this.#notify();
    }
  }

  async #dispatchOne(url, { failed, rules, enabled, current }) {
    if (failed) {
      await this.#openPage("routing/blocked.html", { u: url, why: "error", src: "app" });
      return;
    }
    const decision = decide({ url, rules, enabled, currentProfileId: current });
    if (decision.action === "stay") {
      await this.#openHere(url); // held at start-up; it belongs here after all
      return;
    }
    await this.#handOff(url, decision, "app");
  }

  /** Send a navigation where a rule says: ask first, or the target profile; never here by default. */
  async #handOff(url, decision, source) {
    if (decision.action === "ask") {
      await this.#openPage("routing/ask.html", { u: url, r: decision.ruleId, src: source });
      return;
    }
    const profile = await lazy.SelectableProfileService.getProfile(decision.profileId).catch(() => null);
    if (!profile) {
      await this.#openPage("routing/blocked.html", { u: url, r: decision.ruleId, why: "missing", src: source });
      return;
    }
    if ((await lazy.profileLockState(profile.path)) === "locked") {
      // Never start an engine on a locked profile: offer to unlock it here, without loading the site.
      await this.#openPage("vault/unlock.html", { p: String(profile.id), u: url, src: source });
      return;
    }
    try {
      this.#launchRouted(profile, url);
    } catch (e) {
      console.error("Nulavio routing: could not open the target profile", e);
      await this.#openPage("routing/blocked.html", { u: url, r: decision.ruleId, why: "launch", src: source });
    }
  }

  async #browserWindow() {
    let win = Services.wm.getMostRecentBrowserWindow();
    for (let i = 0; !win && i < 300; i++) {
      await sleep(100);
      win = Services.wm.getMostRecentBrowserWindow();
    }
    if (!win) {
      throw new Error("no browser window");
    }
    await win.delayedStartupPromise;
    return win;
  }

  async #openHere(url) {
    (await this.#browserWindow()).openTrustedLinkIn(url, "tab");
  }

  /** A local Nulavio page (never the site itself). */
  async #openPage(page, params) {
    const win = await this.#browserWindow();
    let policy = WebExtensionPolicy.getByID(SHELL_ID);
    for (let i = 0; !policy && i < 300; i++) {
      await sleep(100);
      policy = WebExtensionPolicy.getByID(SHELL_ID);
    }
    if (!policy) {
      throw new Error("the Nulavio Shell is not running");
    }
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined));
    win.openTrustedLinkIn(`${policy.getURL(page)}?${query}`, "tab");
  }

  // -- change notifications ---------------------------------------------------

  #observe() {
    if (this.#observing) {
      return;
    }
    this.#observing = true;
    Services.prefs.addObserver(RULES_PREF, this);
    Services.prefs.addObserver(ENABLED_PREF, this);
    Services.obs.addObserver(this, "sps-profiles-updated");
  }

  observe() {
    this.#notify();
  }

  #notify() {
    for (const listener of this.#listeners) {
      try {
        listener();
      } catch (e) {
        console.error(e);
      }
    }
  }

  subscribe(listener) {
    this.#observe();
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]);
}

export const NulavioRouting = new NulavioRoutingClass();
