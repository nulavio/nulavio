/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* What Nulavio adds to the engine's fingerprinting protection from the Shell (#79; ADR 0016, ADR 0017, ADR 0018).

   The screen is not here: pages read one size, 1920 by 1080, from the engine itself, which answers each
   document (Nulavio's patch 0012, the ScreenSizeConstant target in the build's default set). Until 160.0.1-0.1
   this module also set a per-tab size, for an engine without the target or a set without it; that went with
   #468, so the engine's set is the one thing that decides. The tab's own screen size
   (browsingContext.setScreenAreaOverride) is automation's, and nothing here sets or clears it.

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
   preference on, a bar offers the setting once. Nulavio's own pages and window follow the system either way. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioGuard: "resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs",
});

/** The permission of a site whose pages read the system's time zone. Kept for the site's registrable domain. */
export const TIME_ZONE = "nulavio-timezone";

const SHELL = "shell@nulavio.net";
const TOPICS = ["browser-delayed-startup-finished", "perm-changed"];
const FPP = "privacy.fingerprintingProtection"; // the engine's protection, in ordinary windows
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

/** Whether the engine's fingerprinting protection is on in ordinary windows (nsRFPService::IsFPPEnabled). */
function protectionOn() {
  return Services.prefs.getBoolPref(FPP, false);
}

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
  return { site, on, offered: Boolean(site) && !context?.usePrivateBrowsing && protectionOn() && !exempted };
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
    ownValue(next, user);
  } else {
    Services.prefs.clearUserPref(WRITTEN);
    ownValue(null);
  }
}

/** Tell the Guard which set is this module's own now (`value`, made from the build's default; null: none), and the
    set it found before it wrote that one (`from`; null: none). The Guard keeps `value` in its record, and at the next
    start leaves out only a change from exactly that set to exactly the one this module then holds as its own, when
    this module wrote it over exactly the set the record kept: with a build whose default changed, Nulavio's own
    rewrite (#654). What this module takes for its own here goes by its memory in the profile, which a program can
    change while the browser is closed; the Guard goes by its record and by what this module found and wrote instead,
    so a set it did not hold as Nulavio's (the person's, or one put in the closed profile, this build's own set
    included) is still reported, also when this module then writes the build's set over it. A failure costs a finding
    in the Guard, never the set. */
function ownValue(value, from = null) {
  try {
    lazy.NulavioGuard.ownPrefValue(OVERRIDES, value, from);
  } catch (e) {
    console.error("Nulavio fingerprinting", e);
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
  if (Services.prefs.prefIsLocked(SHARE) || Services.prefs.prefIsLocked(OVERRIDES) || !protectionOn()) {
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
  /** From the Shell's start: the engine's set and per-site list follow the person's settings, and each window
      gets the time zone's row and, once, the bar. */
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
          } else if (data === OVERRIDES && !watching.handing) {
            // The engine's set changed. After the engine's own observer of the same preference has the new
            // general set, and once however many changes come before that.
            watching.handing = true;
            Services.tm.dispatchToMainThread(() => {
              if (watching) {
                watching.handing = false;
                handListAgain();
              }
            });
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
    Services.prefs.addObserver(OVERRIDES, watching);
    Services.prefs.addObserver(SHARE, watching);
    applyAccessibility(false);
    sync();
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      attach(win);
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
    Services.prefs.removeObserver(OVERRIDES, watching);
    Services.prefs.removeObserver(SHARE, watching);
    for (const win of watching.windows) {
      win.removeEventListener("popupshowing", watching.panelShowing, true);
      win.document.getElementById(ROW)?.remove();
      win.gNotificationBox?.getNotificationWithValue(BAR)?.close();
    }
    watching = null;
  },
};
