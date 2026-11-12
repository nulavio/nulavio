/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Site exceptions in one place (docs/brand/ux-flows.md, flow C).

   The per-site panel is the engine's own trust panel (address bar): it shows
   the connection, what tracking protection blocked on the page (the engine's
   content-blocking log), a per-site switch and "clear cookies and site data".
   What the engine scatters over several dialogs is listed here: every site
   where a protection is off or relaxed, read from the engine's permission
   store, each removable. uBlock Origin keeps its own list of trusted sites;
   Nulavio opens uBlock Origin's own page for it and never edits its data. Of
   that data it reads one thing, which of its lists are switched on, to say
   in Settings whether cookie notices are hidden (the maintainer's decision
   of 2026-11-12: reading, never writing). */

/* Permission types listed, in the order shown. Each relaxes a protection for one site. */
export const TYPES = Object.freeze([
  "trackingprotection", // tracking protection off (normal windows)
  "trackingprotection-pb", // tracking protection off (private windows, this session)
  "https-only-load-insecure", // HTTPS-Only off
  "cookie", // cookies always allowed, blocked or kept for the session
  "install", // may offer to install add-ons
  "popup", // pop-ups allowed
]);

const UBLOCK = "uBlock0@raymondhill.net";
/* uBlock Origin's own lists that hide cookie notices (its registry's group "cookies"); any one of them does. */
export const COOKIE_NOTICE_LISTS = Object.freeze(["fanboy-cookiemonster", "ublock-cookies-easylist", "adguard-cookies", "ublock-cookies-adguard"]);

/** Set once a profile has received Nulavio's privacy defaults that only work as user values. */
export const PREF_SEEDED = "nulavio.privacy.seeded";

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  ExtensionStorageIDB: "resource://gre/modules/ExtensionStorageIDB.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
  NulavioGuard: "resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs",
  NulavioLayout: "resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs",
});

/* The engine's own default permissions (permissions.manager.defaultsUrl): shown as built into the browser. */
function readDefaults() {
  const url = Services.prefs.getStringPref("permissions.manager.defaultsUrl", "");
  if (!url.startsWith("resource://")) {
    return Promise.resolve(new Set());
  }
  return new Promise(resolve => {
    lazy.NetUtil.asyncFetch({ uri: url, loadUsingSystemPrincipal: true }, (stream, status) => {
      if (!Components.isSuccessCode(status)) {
        resolve(new Set());
        return;
      }
      const text = lazy.NetUtil.readInputStreamToString(stream, stream.available(), { charset: "UTF-8" });
      const keys = new Set();
      for (const line of text.split("\n")) {
        const [kind, type, , origin] = line.trim().split(/\s+/);
        if (kind === "origin" && type && origin) {
          keys.add(`${type} ${origin}`);
        }
      }
      resolve(keys);
    });
  });
}

export class PrivacyError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "PrivacyError";
    this.code = code;
  }
}

function capabilityName(capability) {
  switch (capability) {
    case Ci.nsIPermissionManager.ALLOW_ACTION:
      return "allow";
    case Ci.nsIPermissionManager.DENY_ACTION:
      return "deny";
    case Ci.nsICookiePermission.ACCESS_SESSION:
      return "session";
    case Ci.nsIPermissionManager.PROMPT_ACTION:
      return "prompt";
    default:
      return String(capability);
  }
}

function describe(permission, defaults) {
  const principal = permission.principal;
  return {
    builtIn: defaults.has(`${permission.type} ${principal.originNoSuffix}`),
    type: permission.type,
    origin: principal.origin,
    site: principal.host || principal.origin,
    capability: capabilityName(permission.capability),
    // Session-only exceptions disappear when the browser closes.
    session: permission.expireType === Ci.nsIPermissionManager.EXPIRE_SESSION,
    expires: permission.expireType === Ci.nsIPermissionManager.EXPIRE_TIME ? permission.expireTime : null,
    private: Boolean(principal.privateBrowsingId),
  };
}

/* DNS over HTTPS (S15). Nulavio has no resolver of its own: the user picks a third party, or the
   system's resolver. Cloudflare is the engine's default (Mozilla's resolver program); Quad9 and Mullvad
   publish these endpoints themselves (docs/security/hardening.md, DNS). */
export const DNS_PROVIDERS = Object.freeze([
  Object.freeze({ id: "cloudflare", uri: "https://mozilla.cloudflare-dns.com/dns-query" }),
  Object.freeze({ id: "quad9", uri: "https://dns.quad9.net/dns-query" }),
  Object.freeze({ id: "mullvad", uri: "https://dns.mullvad.net/dns-query" }),
]);
export const PREF_DNS_CHOSEN = "nulavio.dns.chosen";
/* The new tab's first run (audit 2026-11 FR-01): the steps answered or skipped, comma-separated. */
export const PREF_FIRSTRUN = "nulavio.firstrun.done";
export const FIRSTRUN_STEPS = Object.freeze(["welcome", "layout", "dns", "passwords", "default-browser", "profile", "finished"]);
// NulavioLayout.PREF_SHELL_START: set once, for a genuinely new profile (the layout adoption's rule).
const PREF_NEW_PROFILE = "nulavio.startpage.shellFirstTab";
const MODE = { system: Ci.nsIDNSService.MODE_TRROFF, fallback: Ci.nsIDNSService.MODE_TRRFIRST, strict: Ci.nsIDNSService.MODE_TRRONLY };
// The two settings a DNS choice writes; a policy that locks one of them leaves nothing to choose here.
const DNS_PREFS = ["network.trr.mode", "network.trr.uri"];

/** An https:// resolver address without credentials; returns it normalised or throws. */
export function checkResolverUri(raw) {
  let url;
  try {
    url = new URL(String(raw ?? "").trim());
  } catch {
    throw new PrivacyError("invalid-url");
  }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password || url.hash) {
    throw new PrivacyError("resolver-needs-https");
  }
  return url.href;
}

class Privacy {
  #listeners = new Set();
  #observing = false;

  // -- DNS --------------------------------------------------------------------

  /** How this profile looks up site names now (read from the engine's own prefs). */
  dns() {
    const mode = Services.prefs.getIntPref("network.trr.mode", 0);
    const choice = mode === MODE.system ? "system" : mode === MODE.fallback ? "fallback" : mode === MODE.strict ? "strict" : "default";
    const uri = Services.prefs.getStringPref("network.trr.uri", "") || Services.prefs.getStringPref("network.trr.default_provider_uri", "");
    const provider = DNS_PROVIDERS.find(p => p.uri === uri)?.id ?? (uri ? "custom" : null);
    // What the resolver does right now (the engine's regional roll-out can turn DoH on under "default").
    const effective = Services.dns.currentTrrMode;
    const encryptedNow = effective === MODE.fallback || effective === MODE.strict;
    // ...and which resolver that is: the engine's word for the one it is using, which under "default" can be
    // another than the address in the settings.
    let resolverUri = "";
    try {
      resolverUri = encryptedNow ? Services.dns.currentTrrURI : "";
    } catch (e) {
      console.error("Nulavio privacy: the resolver in use", e);
    }
    const resolver = resolverUri ? (DNS_PROVIDERS.find(p => p.uri === resolverUri)?.id ?? "custom") : null;
    const locked = DNS_PREFS.some(name => Services.prefs.prefIsLocked(name));
    return { choice, provider, uri, encryptedNow, resolver, resolverUri, locked, chosen: Services.prefs.getBoolPref(PREF_DNS_CHOSEN, false), providers: DNS_PROVIDERS };
  }

  /**
   * Apply the user's choice. "system": the computer's resolver (no encrypted DNS). "fallback":
   * encrypted DNS, the system's resolver if it fails. "strict": encrypted DNS only; sites do not
   * load while the resolver cannot be reached.
   */
  setDns({ choice, provider, uri } = {}) {
    if (!Object.hasOwn(MODE, choice)) {
      throw new PrivacyError("invalid-choice");
    }
    // A policy that locks the resolver decides. The engine takes a write to a locked setting without an error
    // and without effect: "saved" would then be said of a choice that changed nothing.
    if (DNS_PREFS.some(name => Services.prefs.prefIsLocked(name))) {
      throw new PrivacyError("pref-locked");
    }
    if (choice !== "system") {
      const known = DNS_PROVIDERS.find(p => p.id === provider);
      const address = known ? known.uri : provider === "custom" ? checkResolverUri(uri) : null;
      if (!address) {
        throw new PrivacyError("invalid-provider");
      }
      Services.prefs.setStringPref("network.trr.uri", address);
      if (!known) {
        Services.prefs.setStringPref("network.trr.custom_uri", address);
      }
    }
    // The system resolver is mode 5, "off by choice": the engine's regional roll-out never turns DoH on then.
    Services.prefs.setIntPref("network.trr.mode", MODE[choice]);
    Services.prefs.setBoolPref(PREF_DNS_CHOSEN, true);
    return this.dns();
  }

  /**
   * The first-run sequence: only in a genuinely new profile, never in an AI Workspace or a temporary
   * profile (the page itself skips private windows); `done` lists the steps answered or skipped.
   */
  firstRun() {
    const done = Services.prefs.getStringPref(PREF_FIRSTRUN, "").split(",").filter(step => FIRSTRUN_STEPS.includes(step));
    const nonInteractive = Boolean(Services.prefs.getStringPref("nulavio.ai.workspace", ""))
      || Services.prefs.getBoolPref("nulavio.profile.temporary", false);
    const active = Services.prefs.getBoolPref(PREF_NEW_PROFILE, false) && !nonInteractive && !done.includes("finished");
    return { active, done };
  }

  /** Record first-run steps as answered (or skipped): a step answered is never asked again. */
  firstRunDone(steps) {
    const list = [steps].flat();
    if (!list.length || !list.every(step => FIRSTRUN_STEPS.includes(step))) {
      throw new PrivacyError("invalid-step");
    }
    const done = new Set(this.firstRun().done);
    list.forEach(step => done.add(step));
    Services.prefs.setStringPref(PREF_FIRSTRUN, FIRSTRUN_STEPS.filter(step => done.has(step)).join(","));
    return this.firstRun();
  }

  /** "Decide later" on the new tab: nothing changes, the question is not asked again. */
  dismissDnsChoice() {
    Services.prefs.setBoolPref(PREF_DNS_CHOSEN, true);
  }

  /**
   * Strict tracking protection for this profile, once. The engine applies a
   * tracking-protection category only when it is the user's own value: as a
   * default (the build's distribution.ini) it is recomputed to "standard" at
   * start-up. So, like the launcher's seed prefs, Nulavio sets it once as a
   * user value; the user's later choice in Settings sticks. A profile whose
   * category was changed from the automatic "standard" is left as it is.
   * Returns what was done.
   */
  seedDefaults() {
    // Evaluate initial layout adoption before PREF_SEEDED is recorded on first boot.
    try {
      lazy.NulavioLayout.adoptInitialLayout();
    } catch (e) {
      console.error("Nulavio layout startup", e);
    }
    if (Services.prefs.getIntPref(PREF_SEEDED, 0) >= 1) {
      return "already";
    }
    Services.prefs.setIntPref(PREF_SEEDED, 1);
    const name = "browser.contentblocking.category";
    // No user value yet (the engine may not have recomputed it), or the automatic "standard".
    if (Services.prefs.prefHasUserValue(name) && Services.prefs.getStringPref(name) !== "standard") {
      return "kept";
    }
    // Guard must not report Nulavio's own change as one made outside the browser.
    lazy.NulavioGuard.ownPrefChanges(["browser.contentblocking.category", "privacy.trackingprotection.", "network.cookie.cookieBehavior"]);
    Services.prefs.setStringPref("browser.contentblocking.category", "strict");
    return "strict";
  }

  /** Every site where a protection is off or relaxed, from the engine's permission store. */
  async exceptions() {
    this.defaults ??= await readDefaults();
    const out = Services.perms.all
      .filter(p => TYPES.includes(p.type) && !p.principal.isSystemPrincipal)
      .map(p => describe(p, this.defaults));
    out.sort((a, b) => TYPES.indexOf(a.type) - TYPES.indexOf(b.type) || a.site.localeCompare(b.site));
    return out;
  }

  /** Remove one exception: the protection applies to that site again. */
  remove(type, origin) {
    if (!TYPES.includes(type)) {
      throw new PrivacyError("invalid-type");
    }
    const found = Services.perms.all.filter(p => p.type === type && p.principal.origin === origin);
    if (!found.length) {
      throw new PrivacyError("not-found");
    }
    for (const permission of found) {
      Services.perms.removeFromPrincipal(permission.principal, type);
    }
  }

  /** uBlock Origin's own state, as the add-on manager reports it. */
  filter() {
    const policy = WebExtensionPolicy.getByID(UBLOCK);
    return { installed: Boolean(policy), active: Boolean(policy?.active) };
  }

  /**
   * Whether uBlock Origin has a list that hides cookie notices switched on: `{ cookieNotices }`, or null
   * when that cannot be read (it is off, still starting, or keeps its settings somewhere else). Its
   * selection is read from its own settings and nothing is ever written there: its page is where a list
   * is switched on or off.
   */
  async filterLists() {
    const policy = WebExtensionPolicy.getByID(UBLOCK);
    if (!policy?.active || !policy.extension) {
      return null;
    }
    let store = null;
    try {
      store = await lazy.ExtensionStorageIDB.open(lazy.ExtensionStorageIDB.getStoragePrincipal(policy.extension));
      const { selectedFilterLists } = await store.get("selectedFilterLists");
      if (!Array.isArray(selectedFilterLists)) {
        return null; // it has not chosen its lists yet (its first start is not over)
      }
      return { cookieNotices: COOKIE_NOTICE_LISTS.some(key => selectedFilterLists.includes(key)) };
    } catch (e) {
      console.error("Nulavio Privacy: uBlock Origin's lists could not be read", e);
      return null;
    } finally {
      store?.close?.();
    }
  }

  /** Open uBlock Origin's own list of trusted sites (its dashboard), in a tab. */
  openFilterList() {
    const policy = WebExtensionPolicy.getByID(UBLOCK);
    if (!policy?.active) {
      throw new PrivacyError("filter-missing");
    }
    const win = Services.wm.getMostRecentBrowserWindow();
    if (!win) {
      throw new PrivacyError("no-window");
    }
    win.openTrustedLinkIn(policy.getURL("dashboard.html#whitelist.html"), "tab");
  }

  /** Open uBlock Origin's own "Filter lists" (what it blocks: ads, trackers, cookie notices), in a tab. */
  openFilterLists() {
    const policy = WebExtensionPolicy.getByID(UBLOCK);
    if (!policy?.active) {
      throw new PrivacyError("filter-missing");
    }
    const win = Services.wm.getMostRecentBrowserWindow();
    if (!win) {
      throw new PrivacyError("no-window");
    }
    win.openTrustedLinkIn(policy.getURL("dashboard.html#3p-filters.html"), "tab");
  }

  // -- change notifications -------------------------------------------------

  observe(subject) {
    const permission = subject?.QueryInterface?.(Ci.nsIPermission);
    if (permission && !TYPES.includes(permission.type)) {
      return;
    }
    for (const listener of this.#listeners) {
      try {
        listener();
      } catch (e) {
        console.error(e);
      }
    }
  }

  subscribe(listener) {
    if (!this.#observing) {
      this.#observing = true;
      Services.obs.addObserver(this, "perm-changed", true);
    }
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]);
}

export const NulavioPrivacy = new Privacy();
