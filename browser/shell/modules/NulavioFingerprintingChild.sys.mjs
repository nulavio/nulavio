/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The screen size a page reads, decided where the page is made (#79, ADR 0016). This runs in the page's own
   process, at the moment its window is created: after the page before it is gone and before any of its own
   scripts. So a page never reads a size meant for another: a protected page keeps the constant until it is
   replaced, and an exempted site reads the display's size from its first script.

   It reads the engine's own answer for "this site is exempted with the shield" (the document's cookie jar
   settings, which the engine's other fingerprinting protections go by), so the screen is exempted exactly when
   they are, in ordinary and in private windows. It sends no message and takes none. */

export const SCREEN = Object.freeze({ width: 1920, height: 1080 });

const FPP = "privacy.fingerprintingProtection";
const FPP_PRIVATE = "privacy.fingerprintingProtection.pbmode";

/** Whether the engine's fingerprinting protection is on for this kind of window (nsRFPService::IsFPPEnabled). */
export function protectionOn(isPrivate) {
  return Services.prefs.getBoolPref(FPP, false) || (isPrivate && Services.prefs.getBoolPref(FPP_PRIVATE, false));
}

/** Give a tab the constant screen, or the display's. `context` is the tab's top browsing context. */
export function setScreen(context, constant) {
  try {
    if (constant) {
      context.setScreenAreaOverride(SCREEN.width, SCREEN.height);
    } else {
      context.resetScreenAreaOverride();
    }
  } catch (e) {
    console.error("Nulavio fingerprinting", e); // the tab keeps what it had
  }
}

export class NulavioFingerprintingChild extends JSWindowActorChild {
  handleEvent(event) {
    // A page shown again from the engine's cache (back, forward) creates no window: it passes here only.
    if (event.type === "pageshow" && !event.persisted) {
      return;
    }
    const context = this.browsingContext;
    if (!context || context.top !== context) {
      return;
    }
    let exempted = false;
    try {
      exempted = Boolean(this.document.cookieJarSettings?.isOnContentBlockingAllowList);
    } catch {
      // No answer from the engine: the page is treated as any other.
    }
    setScreen(context, protectionOn(context.usePrivateBrowsing) && !exempted);
  }
}
