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
   other plain values.

   Two places set it. Here, every new tab gets the constant when its browsing context is made, before it has
   any page. And in the page's own process, NulavioFingerprintingChild decides for each page as its window is
   created: that is the one moment that is after the page before it and before the new page's first script. */

import { SCREEN, protectionOn, setScreen } from "resource://builtin-addons/nulavio-shell/modules/NulavioFingerprintingChild.sys.mjs";

export { SCREEN };

const ACTOR = "NulavioFingerprinting";
const TOPICS = ["browsing-context-attached"];

let watching = null;

export const NulavioFingerprinting = {
  /** From the Shell's start: every tab has the constant before its first page, and each page gets what it is due. */
  watch() {
    if (watching) {
      return;
    }
    watching = {
      observe(subject) {
        // A new tab, or the tab's new context when a page changes process. Its first page decides for itself.
        if (subject.top === subject && subject.isContent && !subject.isDiscarded) {
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
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      for (const browser of win.gBrowser?.browsers ?? []) {
        const context = browser.browsingContext;
        if (context && !context.isDiscarded) {
          setScreen(context, protectionOn(context.usePrivateBrowsing));
        }
      }
    }
  },

  unwatch() {
    if (!watching) {
      return;
    }
    for (const topic of TOPICS) {
      Services.obs.removeObserver(watching, topic);
    }
    try {
      ChromeUtils.unregisterWindowActor(ACTOR);
    } catch {
      // It was never registered.
    }
    watching = null;
  },
};
