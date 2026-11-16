/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* "Permitir copiar e colar neste site" (#160). Some sites cancel copy, cut, paste or the page menu, or turn text
   selection off, so a password cannot be pasted or a number copied. The engine's switches for that are global
   (dom.event.clipboardevents.enabled, dom.event.contextmenu.enabled) and break web editors everywhere; this is
   a choice for one address only, off by default, and no pref is changed.

   - The switch is in the engine's trust panel (the shield in the address bar), under its tracking-protection
     switch, with the tip that Shift+right-click opens the browser's menu on any page. It is offered on http and
     https pages, not in a private window (which leaves no record).
   - The choice is a permission of the page's origin (scheme, host and port), kept in the profile; Settings
     lists it with the other site exceptions, where it can be removed.
   - In the page's process, NulavioAllowCopyChild reads it for each document as its window is created, and only
     a document of that origin gets the listeners and the sheet. The page is reloaded after a change. */

import { ALLOW_COPY } from "resource://builtin-addons/nulavio-shell/modules/NulavioAllowCopyChild.sys.mjs";

export { ALLOW_COPY };

const SHELL = "shell@nulavio.net";
const ACTOR = "NulavioAllowCopy";
const CHILD = "resource://builtin-addons/nulavio-shell/modules/NulavioAllowCopyChild.sys.mjs";
const ROW = "nulavio-trustpanel-allow-copy";
const AFTER = "nulavio-trustpanel-timezone"; // the time zone's row (NulavioFingerprinting), when it is there

function t(key) {
  return WebExtensionPolicy.getByID(SHELL)?.extension?.localizeMessage(key) || key;
}

/** The origin the choice is kept for: the document's own, for an http or https page; otherwise null. */
function originPrincipal(browser) {
  const principal = browser?.contentPrincipal;
  if (!principal?.isContentPrincipal || !(principal.schemeIs("http") || principal.schemeIs("https"))) {
    return null;
  }
  // The choice is not tied to a container or a private session: the plain origin, as Settings lists it.
  return Services.scriptSecurityManager.createContentPrincipal(principal.URI, {});
}

function state(browser) {
  const principal = originPrincipal(browser);
  const on = Boolean(principal) && Services.perms.testExactPermissionFromPrincipal(principal, ALLOW_COPY) === Services.perms.ALLOW_ACTION;
  return { origin: principal?.origin ?? null, on, offered: Boolean(principal) && !browser.browsingContext?.usePrivateBrowsing };
}

function setFor(browser, on) {
  const principal = originPrincipal(browser);
  if (!principal) {
    return;
  }
  if (on) {
    Services.perms.addFromPrincipal(principal, ALLOW_COPY, Services.perms.ALLOW_ACTION);
  } else {
    Services.perms.removeFromPrincipal(principal, ALLOW_COPY);
  }
}

function showRow(panel) {
  const doc = panel.ownerDocument;
  const win = doc.defaultView;
  const now = state(win.gBrowser.selectedBrowser);
  let row = doc.getElementById(ROW);
  if (!row) {
    const anchor = doc.getElementById(AFTER) ?? panel.querySelector("#trustpanel-toggle-section");
    if (!anchor) {
      return;
    }
    row = doc.createXULElement("vbox");
    row.id = ROW;
    const line = doc.createXULElement("hbox");
    const label = doc.createXULElement("label");
    label.id = `${ROW}-label`;
    label.className = "trustpanel-header";
    label.textContent = t("allowCopySwitch");
    const toggle = doc.createElementNS("http://www.w3.org/1999/xhtml", "moz-toggle");
    toggle.id = `${ROW}-toggle`;
    toggle.setAttribute("aria-label", t("allowCopySwitch"));
    toggle.addEventListener("toggle", () => {
      const tab = win.gBrowser.selectedBrowser;
      // Only for the page the panel was opened on: one that sent the tab elsewhere meanwhile gets nothing.
      const current = state(tab);
      panel.hidePopup();
      if (current.offered && current.origin === row.dataset.origin) {
        setFor(tab, toggle.pressed);
        tab.reload(); // the page's window decides when it is created
      }
    });
    const description = doc.createXULElement("label");
    description.id = `${ROW}-description`;
    // The engine's own way past a blocked page menu, which few people know (#160).
    const tip = doc.createXULElement("label");
    tip.id = `${ROW}-tip`;
    tip.textContent = t("allowCopyTip");
    line.append(label, toggle);
    row.append(line, description, tip);
    anchor.after(row);
  }
  row.hidden = !now.offered;
  row.dataset.origin = now.offered ? now.origin : "";
  row.querySelector("moz-toggle").pressed = now.on;
  row.querySelector(`#${ROW}-description`).textContent = t(now.on ? "allowCopySwitchOn" : "allowCopySwitchOff");
}

let watching = null;

export const NulavioAllowCopy = {
  /** From the Shell's start: the actor that applies the choice, and the switch in each window's trust panel. */
  watch() {
    if (watching) {
      return;
    }
    const windows = new Set();
    const panelShowing = event => {
      if (event.target.id === "trustpanel-popup") {
        try {
          showRow(event.target);
        } catch (e) {
          console.error("Nulavio allow copy", e); // the engine's panel opens as it is
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
      observe(subject, topic) {
        if (topic === "browser-delayed-startup-finished") {
          attach(subject);
        }
      },
    };
    Services.obs.addObserver(watching, "browser-delayed-startup-finished");
    try {
      ChromeUtils.registerWindowActor(ACTOR, {
        child: {
          esModuleURI: CHILD,
          events: { DOMWindowCreated: {} },
        },
        matches: ["http://*/*", "https://*/*"],
        allFrames: true,
        messageManagerGroups: ["browsers"],
        // Runs in web content processes, with nothing to trust: it sends no message and takes none.
        safeForUntrustedWebProcess: true,
      });
    } catch (e) {
      console.error("Nulavio allow copy", e); // the choice is kept, and applies once the actor is there
    }
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      attach(win);
    }
  },

  /** The switch for the page a tab shows: { origin, offered, on }. */
  state(browser) {
    return state(browser);
  },

  /** Turn the choice on or off for the origin of the page `browser` shows. It applies at the page's next load. */
  set(browser, on) {
    setFor(browser, Boolean(on));
  },

  unwatch() {
    if (!watching) {
      return;
    }
    Services.obs.removeObserver(watching, "browser-delayed-startup-finished");
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
