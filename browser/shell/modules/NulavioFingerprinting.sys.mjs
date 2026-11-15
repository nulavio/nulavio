/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* What Nulavio adds to the engine's fingerprinting protection from the Shell (#79; ADR 0016).

   The screen: pages read one size, the same on every computer, instead of the display's. The engine has a
   per-tab screen size for automation (browsingContext.setScreenAreaOverride); with it set, screen.width and
   height, the available area (at 0,0) and the device-width and device-height media queries all say that size.
   The window is left alone: its own size is still what the page lays out in.

   It follows the engine's protection: on while fingerprinting protection is on (the Strict category), and off
   for a site the person exempts with the shield in the address bar, which gets the display's size like the
   other plain values. */

export const SCREEN = Object.freeze({ width: 1920, height: 1080 });

const FPP = "privacy.fingerprintingProtection";
const FPP_PRIVATE = "privacy.fingerprintingProtection.pbmode";

/** Whether the engine's fingerprinting protection is on for this kind of window (nsRFPService::IsFPPEnabled). */
function protectionOn(isPrivate) {
  return Services.prefs.getBoolPref(FPP, false) || (isPrivate && Services.prefs.getBoolPref(FPP_PRIVATE, false));
}

/** Whether the person exempted this address's site with the shield. The engine keeps that by host and port,
    whatever the scheme (ContentBlockingAllowList::ComputePrincipal). */
function exempted(uri, isPrivate) {
  if (!uri?.schemeIs("http") && !uri?.schemeIs("https")) {
    return false;
  }
  try {
    const site = Services.io.newURI(`https://${uri.hostPort}`);
    const principal = Services.scriptSecurityManager.createContentPrincipal(site, {});
    const type = isPrivate ? "trackingprotection-pb" : "trackingprotection";
    return Services.perms.testExactPermissionFromPrincipal(principal, type) === Services.perms.ALLOW_ACTION;
  } catch {
    return false;
  }
}

/* Whether each tab's last page was an exempted site, by the tab's id, which stays when a page changes process
   and the tab gets a new browsing context. A new context starts with no page of its own, and must not lose the
   exemption of the site it is about to show. Only that yes or no is kept, never an address, so nothing of a
   closed tab or a private window stays here. Bounded: the oldest entries go first. */
const lastExempted = new Map();
const REMEMBERED = 512;

function remember(id, wasExempted) {
  lastExempted.delete(id);
  lastExempted.set(id, wasExempted);
  if (lastExempted.size > REMEMBERED) {
    lastExempted.delete(lastExempted.keys().next().value);
  }
}

/** Give the tab of this browsing context the constant screen, or the display's for an exempted site. `uri` is
    the address its top document has or is about to load; without one, what the tab's last page was stands. */
function apply(context, uri = null) {
  const top = context?.top;
  if (!top?.isContent || top.isDiscarded) {
    return;
  }
  let plain;
  if (uri) {
    plain = exempted(uri, top.usePrivateBrowsing);
    remember(top.browserId, plain);
  } else {
    plain = lastExempted.get(top.browserId) ?? false;
  }
  try {
    if (protectionOn(top.usePrivateBrowsing) && !plain) {
      top.setScreenAreaOverride(SCREEN.width, SCREEN.height);
    } else {
      top.resetScreenAreaOverride();
    }
  } catch (e) {
    console.error("Nulavio fingerprinting", e); // the tab keeps what it had
  }
}

let watching = null;

export const NulavioFingerprinting = {
  /** From the Shell's start: every tab gets the screen size before its first page, and again at each page. */
  watch() {
    if (watching) {
      return;
    }
    const tabs = {
      // Pages that load nothing (back and forward from the engine's cache, about: pages) pass here only.
      onLocationChange(browser, progress, request, location, flags) {
        if (progress.isTopLevel && !(flags & Ci.nsIWebProgressListener.LOCATION_CHANGE_SAME_DOCUMENT)) {
          apply(browser.browsingContext, location);
        }
      },
    };
    const windows = new Set();
    const attach = win => {
      if (win?.gBrowser && !windows.has(win)) {
        windows.add(win);
        win.gBrowser.addTabsProgressListener(tabs);
        win.addEventListener("unload", () => windows.delete(win), { once: true });
      }
    };
    watching = {
      windows,
      tabs,
      observe(subject, topic) {
        if (topic === "browsing-context-attached") {
          if (subject.top === subject) {
            apply(subject); // a new tab, or the tab's new context when a page changes process
          }
        } else if (topic === "browser-delayed-startup-finished") {
          attach(subject);
        } else {
          // A page about to be asked for: decided here, before any request leaves, so the page's first script
          // already reads the right size.
          let channel;
          try {
            channel = subject.QueryInterface(Ci.nsIHttpChannel);
          } catch {
            return;
          }
          if (channel.loadInfo?.externalContentPolicyType === Ci.nsIContentPolicy.TYPE_DOCUMENT) {
            apply(channel.loadInfo.browsingContext, channel.URI);
          }
        }
      },
    };
    for (const topic of ["browsing-context-attached", "browser-delayed-startup-finished", "http-on-modify-request"]) {
      Services.obs.addObserver(watching, topic);
    }
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      attach(win);
      for (const browser of win.gBrowser.browsers) {
        apply(browser.browsingContext, browser.currentURI);
      }
    }
  },

  unwatch() {
    if (!watching) {
      return;
    }
    for (const topic of ["browsing-context-attached", "browser-delayed-startup-finished", "http-on-modify-request"]) {
      Services.obs.removeObserver(watching, topic);
    }
    for (const win of watching.windows) {
      win.gBrowser?.removeTabsProgressListener(watching.tabs);
    }
    watching = null;
  },
};
