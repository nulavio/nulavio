/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Routing rules offered when the person signs in to an account in a profile (#220, decision 3: rules offered
   when the person adds a Google account in any profile, no template of its own). The sign-in is seen as the
   service's own sign-in cookie appearing in this profile (never a page's content, never a password). Once per
   service and profile, a bar offers to open that service's sites in this profile from the others and from
   other applications; nothing is applied without the person's click, and either answer ends the offer. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  NulavioRouting: "resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs",
});

const SHELL = "shell@nulavio.net";
export const OFFERED_PREF = "nulavio.accountRules.offered"; // the services already offered here, comma-separated
const BAR = "nulavio-account-rules";

/* The services with an offer, each with the sign-in cookies that mean "signed in here" and its own sites, by
   registrable domain. The person's country domain of the service is added when the search region names one. */
export const SERVICES = Object.freeze({
  google: Object.freeze({
    cookieDomain: "google.com",
    cookies: Object.freeze(["SID", "__Secure-1PSID"]),
    sites: Object.freeze(["google.com", "gmail.com", "youtube.com", "googleusercontent.com"]),
    countrySites: Object.freeze({ BR: "google.com.br", PT: "google.pt" }),
  }),
});

function t(key, subs = []) {
  return WebExtensionPolicy.getByID(SHELL)?.extension?.localizeMessage(key, subs) || key;
}

/** The service a cookie signs in to, or null. Pure: tested directly. */
export function serviceOfCookie(cookie) {
  const host = String(cookie?.host ?? "").replace(/^\./, "").toLowerCase();
  for (const [id, service] of Object.entries(SERVICES)) {
    const domain = service.cookieDomain;
    if ((host === domain || host.endsWith(`.${domain}`)) && service.cookies.includes(cookie?.name)) {
      return id;
    }
  }
  return null;
}

/** The sites a service's rules cover, for this region. */
export function sitesOf(id, region = Services.prefs.getStringPref("browser.search.region", "")) {
  const service = SERVICES[id];
  const country = service.countrySites[String(region).toUpperCase()];
  return country ? [...service.sites, country] : [...service.sites];
}

function offered() {
  return Services.prefs.getStringPref(OFFERED_PREF, "").split(",").filter(Boolean);
}

function markOffered(id) {
  Services.prefs.setStringPref(OFFERED_PREF, [...new Set([...offered(), id])].join(","));
}

let observer = null;

export const NulavioAccountRules = {
  /** From the Shell's start: sign-in cookies added in this (non-private) profile. */
  watch() {
    if (observer) {
      return;
    }
    observer = {
      observe: subject => {
        let note;
        try {
          note = subject.QueryInterface(Ci.nsICookieNotification);
        } catch {
          return;
        }
        if (note.action !== Ci.nsICookieNotification.COOKIE_ADDED || note.cookie?.originAttributes?.privateBrowsingId) {
          return;
        }
        const id = serviceOfCookie(note.cookie);
        if (id) {
          this.offer(id).catch(e => console.error("Nulavio account rules", e));
        }
      },
    };
    Services.obs.addObserver(observer, "cookie-changed");
  },

  unwatch() {
    if (observer) {
      Services.obs.removeObserver(observer, "cookie-changed");
      observer = null;
    }
  },

  /** Offer the service's rules in the front window, once: only in a group of profiles, and only while no rule
      of this profile's already covers the service. Resolves whether a bar was shown. */
  async offer(id) {
    if (!SERVICES[id] || offered().includes(id) || !lazy.NulavioProfiles.availability().available) {
      return false;
    }
    const here = (await lazy.NulavioProfiles.current())?.id;
    const sites = sitesOf(id);
    if (!here || lazy.NulavioRouting.rules().some(rule => sites.includes(rule.value))) {
      return false;
    }
    const win = Services.wm.getMostRecentWindow("navigator:browser");
    const box = win?.gNotificationBox;
    if (!box || box.getNotificationWithValue(BAR)) {
      return false;
    }
    const answer = add => () => {
      markOffered(id);
      if (add) {
        this.addRules(id, here).catch(e => console.error("Nulavio account rules", e));
      }
      return false; // the bar closes
    };
    await box.appendNotification(
      BAR,
      { label: t(`accountRulesOffer_${id}`), priority: box.PRIORITY_INFO_MEDIUM, eventCallback: event => event === "dismissed" && markOffered(id) },
      [
        { label: t("accountRulesAdd"), callback: answer(true) },
        { label: t("accountRulesNotNow"), callback: answer(false) },
      ]
    );
    return true;
  },

  /** The service's sites, by domain, opened in `profileId`; routing turned on, as the person asked. */
  async addRules(id, profileId) {
    for (const site of sitesOf(id)) {
      await lazy.NulavioRouting.addRule({ site, match: "domain", action: "open-in", profileId });
    }
    if (!lazy.NulavioRouting.enabled()) {
      await lazy.NulavioRouting.setEnabled(true);
    }
  },
};
