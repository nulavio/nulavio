/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* What Nulavio adds to the engine's fingerprinting protection from the Shell (#79; ADR 0016, ADR 0017).

   The screen: pages read one size, the same on every computer, instead of the display's. The engine has a
   per-tab screen size for automation (browsingContext.setScreenAreaOverride); with it set, screen.width and
   height, the available area (at 0,0) and the device-width and device-height media queries all say that size.
   The window is left alone: its own size is still what the page lays out in.

   It follows the engine's protection: on while fingerprinting protection is on (the Strict category), and off
   for a site the person exempts with the shield in the address bar, which gets the display's size like the
   other plain values.

   The time zone: pages read UTC (the engine's JSDateTimeUTC, in the default set). A site that needs the real
   one, a calendar or a bank, gets it from a switch in the engine's trust panel, "use my time zone on this
   site". The choice is a permission of that site, so Settings lists it with the other site exceptions, where
   it can be removed. From those permissions this module writes the engine's own per-site list
   (privacy.fingerprintingProtection.granularOverrides), which is what the engine reads (ADR 0017).

   The screen is set in two places. Here, every new tab gets the constant when its browsing context is made,
   before it has any page. And in the page's own process, NulavioFingerprintingChild decides for each page as
   its window is created: the one moment that is after the page before it and before the new page's first
   script. */

import { SCREEN, protectionOn, setScreen } from "resource://builtin-addons/nulavio-shell/modules/NulavioFingerprintingChild.sys.mjs";

export { SCREEN };

/** The permission of a site whose pages read the system's time zone. Kept for the site's registrable domain. */
export const TIME_ZONE = "nulavio-timezone";

const SHELL = "shell@nulavio.net";
const ACTOR = "NulavioFingerprinting";
const TOPICS = ["browsing-context-attached", "browser-delayed-startup-finished", "perm-changed"];
const GRANULAR = "privacy.fingerprintingProtection.granularOverrides"; // the engine's per-site list (JSON)
const SHOW_TIME_ZONE = "-JSDateTimeUTC";
const ROW = "nulavio-trustpanel-timezone";

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
      }
    };
    watching = {
      windows,
      panelShowing,
      observe(subject, topic, data) {
        if (topic === "perm-changed") {
          // A site's choice added or removed, here or in Settings' list, or every permission cleared.
          if (data === "cleared" || subject?.QueryInterface?.(Ci.nsIPermission).type === TIME_ZONE) {
            sync();
          }
        } else if (topic === "browser-delayed-startup-finished") {
          attach(subject);
        } else if (subject.top === subject && subject.isContent && !subject.isDiscarded) {
          // A new tab, or the tab's new context when a page changes process. Its first page decides for itself.
          setScreen(subject, protectionOn(subject.usePrivateBrowsing));
        }
      },
    };
    for (const topic of TOPICS) {
      Services.obs.addObserver(watching, topic);
    }
    try {
      ChromeUtils.registerWindowActor(ACTOR, {
        child: {
          esModuleURI: "resource://builtin-addons/nulavio-shell/modules/NulavioFingerprintingChild.sys.mjs",
          events: { DOMWindowCreated: {}, pageshow: {} },
        },
        allFrames: false,
        messageManagerGroups: ["browsers"],
        // Runs in web content processes, with nothing to trust: it sends no message and takes none.
        safeForUntrustedWebProcess: true,
      });
    } catch (e) {
      console.error("Nulavio fingerprinting", e); // tabs keep the constant; an exempted site does not get the display's
    }
    sync();
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      attach(win);
      for (const browser of win.gBrowser?.browsers ?? []) {
        const context = browser.browsingContext;
        if (context && !context.isDiscarded) {
          setScreen(context, protectionOn(context.usePrivateBrowsing));
        }
      }
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

  unwatch() {
    if (!watching) {
      return;
    }
    for (const topic of TOPICS) {
      Services.obs.removeObserver(watching, topic);
    }
    for (const win of watching.windows) {
      win.removeEventListener("popupshowing", watching.panelShowing, true);
      win.document.getElementById(ROW)?.remove();
    }
    try {
      ChromeUtils.unregisterWindowActor(ACTOR);
    } catch {
      // It was never registered.
    }
    watching = null;
  },
};
