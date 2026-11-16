/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* What Nulavio adds to the engine's fingerprinting protection from the Shell (#79; ADR 0016, ADR 0017, ADR 0018).

   The screen: pages read one size, the same on every computer, instead of the display's. The engine has a
   per-tab screen size for automation (browsingContext.setScreenAreaOverride); with it set, screen.width and
   height, the available area (at 0,0) and the device-width and device-height media queries all say that size.
   The window is left alone: its own size is still what the page lays out in.

   It follows the engine's protection: on while fingerprinting protection is on (the Strict category), and off
   for a site the person exempts with the shield in the address bar, which gets the display's size like the
   other plain values.

   An engine with Nulavio's patch 0012 gives each document that size itself (the ScreenSizeConstant target, in
   the default set), a frame and a pop-up too. This module then leaves the per-tab size unset. The per-tab
   path stays for an engine from before the patch, and for a set a person wrote without the target.

   The time zone: pages read UTC (the engine's JSDateTimeUTC, in the default set). A site that needs the real
   one, a calendar or a bank, gets it from a switch in the engine's trust panel, "use my time zone on this
   site". The choice is a permission of that site, so Settings lists it with the other site exceptions, where
   it can be removed. From those permissions this module writes the engine's own per-site list
   (privacy.fingerprintingProtection.granularOverrides), which is what the engine reads (ADR 0017).

   Motion and contrast: pages are not told that the system asks for less motion or more contrast (the engine's
   CSSPrefersReducedMotion, CSSPrefersContrast and CSSPrefersReducedTransparency, in the default set; ADR 0018).
   One setting, "let sites see my motion and contrast preferences", takes those three out again (and nothing
   else: a set the person wrote themselves keeps its other entries). It rewrites the set itself, not the
   per-site list: with the motion one in the set the engine also scrolls smoothly whatever
   the system asks, so that pages cannot tell, and only the set itself undoes that. When the system has either
   preference on, a bar offers the setting once. Nulavio's own pages and window follow the system either way.

   The screen is decided by each page as its window is created, in the page's own process
   (NulavioFingerprintingChild): the one moment that is after the page before it and before the new page's
   first script. This module only starts that, and decides again for the pages already open when the Shell
   starts or when the engine's protection is switched on or off. */

import {
  SCREEN,
  engineDecides,
  protectionOn,
  setScreen,
  wantsConstant,
} from "resource://builtin-addons/nulavio-shell/modules/NulavioFingerprintingChild.sys.mjs";

export { SCREEN };

/** The permission of a site whose pages read the system's time zone. Kept for the site's registrable domain. */
export const TIME_ZONE = "nulavio-timezone";

const SHELL = "shell@nulavio.net";
const ACTOR = "NulavioFingerprinting";
const TOPICS = ["browser-delayed-startup-finished", "perm-changed"];
// What decides a tab's screen size: the engine's protection on or off, and its set, which says whether the
// engine gives documents the constant itself (NulavioFingerprintingChild.engineDecides).
const SWITCHES = [
  "privacy.fingerprintingProtection",
  "privacy.fingerprintingProtection.pbmode",
  "privacy.fingerprintingProtection.overrides",
];
const FALLBACK_TOPIC = "browsing-context-attached"; // only if the actor cannot be registered
const GRANULAR = "privacy.fingerprintingProtection.granularOverrides"; // the engine's per-site list (JSON)
const SHOW_TIME_ZONE = "-JSDateTimeUTC";
const ROW = "nulavio-trustpanel-timezone";

/** The setting: sites see the system's motion and contrast preferences. It relaxes a protection, so it is not
    one of the personalisation options (shared/options.json): this module reads and writes it for Settings. */
export const SHARE = "nulavio.fingerprinting.shareAccessibility";
/** Set once the bar that offers the setting was answered or closed. */
export const OFFERED = "nulavio.fingerprinting.accessibilityOffered";
const OVERRIDES = "privacy.fingerprintingProtection.overrides"; // the engine's set, a default of the build
/** The set this module last wrote there from the build's default: how it tells its own value from a set the
    person wrote themselves, which it must not replace. */
const WRITTEN = "nulavio.fingerprinting.overridesWritten";
const ACCESSIBILITY = Object.freeze(["CSSPrefersReducedMotion", "CSSPrefersContrast", "CSSPrefersReducedTransparency"]);
const BAR = "nulavio-accessibility-offer";

function t(key) {
  return WebExtensionPolicy.getByID(SHELL)?.extension?.localizeMessage(key) || key;
}

/** The site a per-site choice is kept for: the registrable domain, which is what the engine's per-site list goes
    by. Null for an address that has none (an IP address, localhost, a page of the browser itself). */
export function siteOf(uri) {
  if (!uri?.schemeIs("http") && !uri?.schemeIs("https")) {
    return null;
  }
  try {
    return Services.eTLD.getBaseDomain(uri);
  } catch {
    return null;
  }
}

function sitePrincipal(site) {
  return Services.scriptSecurityManager.createContentPrincipal(Services.io.newURI(`https://${site}`), {});
}

function timeZoneSites() {
  const sites = Services.perms
    .getAllByTypes([TIME_ZONE])
    .filter(permission => permission.capability === Services.perms.ALLOW_ACTION)
    .map(permission => permission.principal.host);
  return [...new Set(sites)].sort();
}

/** The engine's per-site list with this module's entries replaced by the ones for `sites`. An entry is this
    module's when it has the shape written here; anything else a person put in the list stays. Pure. */
export function withTimeZoneSites(list, sites) {
  const ours = entry => entry?.thirdPartyDomain === "*" && entry?.overrides === SHOW_TIME_ZONE;
  const kept = (Array.isArray(list) ? list : []).filter(entry => !ours(entry));
  // Every page under the site, its frames from other sites included: a calendar's widget shows the same hours.
  return [...kept, ...sites.map(site => ({ firstPartyDomain: site, thirdPartyDomain: "*", overrides: SHOW_TIME_ZONE }))];
}

/** Write the engine's per-site list from the sites' permissions. */
function sync() {
  const current = Services.prefs.getStringPref(GRANULAR, "");
  let list = [];
  try {
    list = JSON.parse(current || "[]");
  } catch {
    // Not a list the engine could read either: it is replaced.
  }
  const next = withTimeZoneSites(list, timeZoneSites());
  const text = next.length ? JSON.stringify(next) : "";
  if (text === current || Services.prefs.prefIsLocked(GRANULAR)) {
    return;
  }
  if (text) {
    Services.prefs.setStringPref(GRANULAR, text);
  } else {
    Services.prefs.clearUserPref(GRANULAR);
  }
}

/** Hand the per-site list to the engine again after the general set changed. The engine works out each site's own
    set from the general one at the moment the list is set, and not again when the general set changes
    (nsRFPService::SetFingerprintingOverrides): a site with "use my time zone" on, or one on Mozilla's own list,
    would keep the earlier set until the browser restarts (#405). The same value is no change to a preference, so
    the list is taken away and put back; with no list of ours, an empty one is set and cleared. */
function handListAgain() {
  if (Services.prefs.prefIsLocked(GRANULAR)) {
    return;
  }
  const current = Services.prefs.getStringPref(GRANULAR, "");
  if (current) {
    Services.prefs.clearUserPref(GRANULAR);
    Services.prefs.setStringPref(GRANULAR, current);
  } else {
    Services.prefs.setStringPref(GRANULAR, "[]");
    Services.prefs.clearUserPref(GRANULAR);
  }
}

/** For the page a tab shows: its site, whether the switch is offered there, and whether it is on. It is offered
    where pages read UTC: a site with a registrable domain, with the protection on and the site not exempted
    with the shield (the engine's own record for the page; such a site reads the real time zone already). Not
    in a private window, which leaves no record. */
function timeZoneState(browser) {
  const site = siteOf(browser.currentURI);
  const on = Boolean(site) && Services.perms.testExactPermissionFromPrincipal(sitePrincipal(site), TIME_ZONE) === Services.perms.ALLOW_ACTION;
  const context = browser.browsingContext;
  const exempted = Boolean(context?.currentWindowGlobal?.cookieJarSettings?.isOnContentBlockingAllowList);
  return { site, on, offered: Boolean(site) && !context?.usePrivateBrowsing && protectionOn(false) && !exempted };
}

function setTimeZone(uri, on) {
  const site = siteOf(uri);
  if (!site) {
    return;
  }
  if (on) {
    Services.perms.addFromPrincipal(sitePrincipal(site), TIME_ZONE, Services.perms.ALLOW_ACTION);
  } else {
    Services.perms.removeFromPrincipal(sitePrincipal(site), TIME_ZONE);
  }
  sync(); // the permission's own notification does it too; the page reloads right after, so not later
}

/* The switch in the engine's trust panel (the shield in the address bar), under its own tracking-protection
   switch and shaped as it. The panel is the engine's and is made when first opened, so the row is added then. */
function showTimeZoneRow(panel) {
  const doc = panel.ownerDocument;
  const win = doc.defaultView;
  const browser = win.gBrowser.selectedBrowser;
  const state = timeZoneState(browser);
  let row = doc.getElementById(ROW);
  if (!row) {
    const anchor = panel.querySelector("#trustpanel-toggle-section");
    if (!anchor) {
      return;
    }
    row = doc.createXULElement("vbox");
    row.id = ROW;
    const line = doc.createXULElement("hbox");
    const label = doc.createXULElement("label");
    label.id = `${ROW}-label`;
    label.className = "trustpanel-header";
    label.textContent = t("timeZoneSwitch");
    const toggle = doc.createElementNS("http://www.w3.org/1999/xhtml", "moz-toggle");
    toggle.id = `${ROW}-toggle`;
    toggle.setAttribute("aria-label", t("timeZoneSwitch"));
    toggle.addEventListener("toggle", () => {
      const tab = win.gBrowser.selectedBrowser;
      // Only for the site the panel was opened on: a page that sent the tab elsewhere while the panel was open
      // does not get the choice put on another site.
      const now = timeZoneState(tab);
      panel.hidePopup();
      if (now.offered && now.site === row.dataset.site) {
        setTimeZone(tab.currentURI, toggle.pressed);
        tab.reload(); // a page reads its time zone when it loads
      }
    });
    const description = doc.createXULElement("label");
    description.id = `${ROW}-description`;
    line.append(label, toggle);
    row.append(line, description);
    anchor.after(row);
  }
  row.hidden = !state.offered;
  row.dataset.site = state.offered ? state.site : "";
  row.querySelector("moz-toggle").pressed = state.on;
  row.querySelector(`#${ROW}-description`).textContent = t(state.on ? "timeZoneSwitchOn" : "timeZoneSwitchOff");
}

/** Decide again for every page open in a tab: at the Shell's start, and when the engine's protection is
    switched on or off (the category changed in Settings), so an open page does not keep what it had. */
function decideOpenPages() {
  for (const win of Services.wm.getEnumerator("navigator:browser")) {
    for (const browser of win.gBrowser?.browsers ?? []) {
      const context = browser.browsingContext;
      const page = context?.currentWindowGlobal;
      if (context && !context.isDiscarded && page) {
        setScreen(context, wantsConstant(page.documentPrincipal, page.cookieJarSettings, context.usePrivateBrowsing));
      }
    }
  }
}

/** A set without the three accessibility entries. Pure. */
export function withoutAccessibility(overrides) {
  return String(overrides ?? "")
    .split(",")
    .map(item => item.trim())
    .filter(item => item && !ACCESSIBILITY.includes(item.replace(/^[+-]/, "")))
    .join(",");
}

/** A set with the three accessibility entries turned on again, and whatever else it had. Pure. */
export function withAccessibility(overrides) {
  return [withoutAccessibility(overrides), ...ACCESSIBILITY.map(name => `+${name}`)].filter(Boolean).join(",");
}

/** Make the engine's set follow the setting, and leave alone what else a person put in it.

    On: the three entries are taken out. Of the build's default when the value there is the build's or this
    module's own (and again at each start, so a later build's default is taken in); of the person's own set
    when they wrote one, which keeps everything else they chose.

    Off, at the moment the setting is turned off and never at a start: this module's own value is cleared, and
    a person's own set gets the three entries back. */
function applyAccessibility(changed) {
  if (Services.prefs.prefIsLocked(OVERRIDES)) {
    return; // a policy decides
  }
  const user = Services.prefs.prefHasUserValue(OVERRIDES) ? Services.prefs.getStringPref(OVERRIDES, "") : null;
  const own = user !== null && user !== Services.prefs.getStringPref(WRITTEN, "");
  let next = user;
  if (Services.prefs.getBoolPref(SHARE, false)) {
    next = withoutAccessibility(own ? user : Services.prefs.getDefaultBranch("").getStringPref(OVERRIDES, ""));
  } else if (!changed) {
    return;
  } else {
    next = own ? withAccessibility(user) : null;
  }
  if (next === null) {
    Services.prefs.clearUserPref(OVERRIDES);
  } else if (next !== user) {
    Services.prefs.setStringPref(OVERRIDES, next);
  }
  // Remembered only for a value made from the build's default.
  if (next !== null && !own) {
    Services.prefs.setStringPref(WRITTEN, next);
  } else {
    Services.prefs.clearUserPref(WRITTEN);
  }
}

/** What the system asks for, read in the browser's own window, which pages' protection does not reach. */
function systemAsks(win) {
  return {
    reducedMotion: Boolean(win?.matchMedia("(prefers-reduced-motion: reduce)").matches),
    moreContrast: Boolean(win?.matchMedia("(prefers-contrast: more)").matches || win?.matchMedia("(forced-colors: active)").matches),
  };
}

/** The bar, once: only when the system has one of the two preferences on, the setting is off and it can change. */
async function offerAccessibility(win) {
  if (Services.prefs.getBoolPref(OFFERED, false) || Services.prefs.getBoolPref(SHARE, false)) {
    return false;
  }
  if (Services.prefs.prefIsLocked(SHARE) || Services.prefs.prefIsLocked(OVERRIDES) || !protectionOn(false)) {
    return false;
  }
  const asks = systemAsks(win);
  const box = win?.gNotificationBox;
  if (!(asks.reducedMotion || asks.moreContrast) || !box || box.getNotificationWithValue(BAR)) {
    return false;
  }
  const answered = share => () => {
    Services.prefs.setBoolPref(OFFERED, true);
    if (share) {
      Services.prefs.setBoolPref(SHARE, true);
    }
    return false; // the bar closes
  };
  await box.appendNotification(
    BAR,
    {
      label: t("accessibilityOffer"),
      priority: box.PRIORITY_INFO_MEDIUM,
      eventCallback: event => event === "dismissed" && Services.prefs.setBoolPref(OFFERED, true),
    },
    [
      { label: t("accessibilityOfferShare"), callback: answered(true) },
      { label: t("accessibilityOfferKeep"), callback: answered(false) },
    ]
  );
  return true;
}

let watching = null;

export const NulavioFingerprinting = {
  /** From the Shell's start: every tab has the constant before its first page, and each page gets what it is due. */
  watch() {
    if (watching) {
      return;
    }
    const windows = new Set();
    const panelShowing = event => {
      if (event.target.id === "trustpanel-popup") {
        try {
          showTimeZoneRow(event.target);
        } catch (e) {
          console.error("Nulavio fingerprinting", e); // the engine's panel opens as it is
        }
      }
    };
    const attach = win => {
      if (win?.gBrowser && !windows.has(win)) {
        windows.add(win);
        win.addEventListener("popupshowing", panelShowing, true);
        win.addEventListener("unload", () => windows.delete(win), { once: true });
        if (!win.gBrowser.selectedBrowser.browsingContext?.usePrivateBrowsing) {
          offerAccessibility(win).catch(e => console.error("Nulavio fingerprinting", e));
        }
      }
    };
    watching = {
      windows,
      panelShowing,
      observe(subject, topic, data) {
        if (topic === "nsPref:changed") {
          if (data === SHARE) {
            applyAccessibility(true); // the person's setting, turned on or off
          } else {
            // The engine's protection switched on or off, or its set changed. On the engine's way the tab's
            // size is not this module's: it is left as it is (it may be automation's, WebDriver BiDi's screen
            // emulation), except once, on the change from the per-tab way, to clear what this module had set.
            const engine = engineDecides();
            if (!(engine && watching.engine)) {
              decideOpenPages();
            }
            watching.engine = engine;
            if (data === OVERRIDES && !watching.handing) {
              // After the engine's own observer of the same preference has the new general set. Once per
              // change: a preference observer is told of everything under its name, so this one hears the
              // set twice (as itself, and under "privacy.fingerprintingProtection").
              watching.handing = true;
              Services.tm.dispatchToMainThread(() => {
                if (watching) {
                  watching.handing = false;
                  handListAgain();
                }
              });
            }
          }
        } else if (topic === "perm-changed") {
          // A site's choice added or removed, here or in Settings' list, or every permission cleared.
          if (data === "cleared" || subject?.QueryInterface?.(Ci.nsIPermission).type === TIME_ZONE) {
            sync();
          }
        } else if (topic === "browser-delayed-startup-finished") {
          attach(subject);
        }
      },
    };
    for (const topic of TOPICS) {
      Services.obs.addObserver(watching, topic);
    }
    for (const pref of SWITCHES) {
      Services.prefs.addObserver(pref, watching);
    }
    Services.prefs.addObserver(SHARE, watching);
    applyAccessibility(false);
    try {
      ChromeUtils.registerWindowActor(ACTOR, {
        child: {
          esModuleURI: "resource://builtin-addons/nulavio-shell/modules/NulavioFingerprintingChild.sys.mjs",
          // Capturing: before the page's own pageshow listeners, for a page taken back from the engine's cache.
          events: { DOMWindowCreated: {}, pageshow: { capture: true } },
        },
        allFrames: false,
        messageManagerGroups: ["browsers"],
        // Runs in web content processes, with nothing to trust: it sends no message and takes none.
        safeForUntrustedWebProcess: true,
      });
    } catch (e) {
      // Without the actor no page would decide for itself, and new tabs would read the display's size. So every
      // new top-level content context gets the constant when it is made, as the first version of this did: an
      // exempted site and an extension's pages then read it too, which is the lesser failure.
      console.error("Nulavio fingerprinting: pages cannot decide their screen size, every new context gets the constant", e);
      watching.fallback = {
        observe(subject) {
          if (subject.top === subject && subject.isContent && !subject.isDiscarded && !engineDecides()) {
            setScreen(subject, protectionOn(subject.usePrivateBrowsing));
          }
        },
      };
      Services.obs.addObserver(watching.fallback, FALLBACK_TOPIC);
    }
    sync();
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      attach(win);
    }
    watching.engine = engineDecides();
    if (!watching.engine) {
      decideOpenPages();
    }
  },

  /** The switch for the page a tab shows: { site, offered, on }. */
  timeZone(browser) {
    return timeZoneState(browser);
  },

  /** Turn the switch on or off for the site of `uri`. The page reads it at its next load. */
  setTimeZone(uri, on) {
    setTimeZone(uri, Boolean(on));
  },

  /** For Settings: whether sites are told, whether a policy fixed that, and what the system asks for. */
  accessibility() {
    return {
      shared: Services.prefs.getBoolPref(SHARE, false),
      locked: Services.prefs.prefIsLocked(SHARE) || Services.prefs.prefIsLocked(OVERRIDES),
      system: systemAsks(Services.wm.getMostRecentWindow("navigator:browser")),
    };
  },

  /** Tell sites the system's motion and contrast preferences, or stop telling them. */
  setShareAccessibility(on) {
    if (Services.prefs.prefIsLocked(SHARE) || Services.prefs.prefIsLocked(OVERRIDES)) {
      return;
    }
    if (on) {
      Services.prefs.setBoolPref(SHARE, true);
    } else {
      Services.prefs.clearUserPref(SHARE);
    }
  },

  unwatch() {
    if (!watching) {
      return;
    }
    for (const topic of TOPICS) {
      Services.obs.removeObserver(watching, topic);
    }
    for (const pref of SWITCHES) {
      Services.prefs.removeObserver(pref, watching);
    }
    if (watching.fallback) {
      Services.obs.removeObserver(watching.fallback, FALLBACK_TOPIC);
    }
    Services.prefs.removeObserver(SHARE, watching);
    for (const win of watching.windows) {
      win.removeEventListener("popupshowing", watching.panelShowing, true);
      win.document.getElementById(ROW)?.remove();
      win.gNotificationBox?.getNotificationWithValue(BAR)?.close();
    }
    try {
      ChromeUtils.unregisterWindowActor(ACTOR);
    } catch {
      // It was never registered.
    }
    watching = null;
  },
};
