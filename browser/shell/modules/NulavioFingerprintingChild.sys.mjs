/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The screen size a page reads, decided where the page is made (#79, ADR 0016). This runs in the page's own
   process, at the moment its window is created: after the page before it is gone and before any of its own
   scripts. So a page never reads a size meant for another: a protected page keeps the constant until it is
   replaced, and an exempted site reads the display's size from its first script.

   It reads the engine's own answer for "this site is exempted with the shield" (the document's cookie jar
   settings, which the engine's other fingerprinting protections go by), so the screen is exempted exactly when
   they are, in ordinary and in private windows. It sends no message and takes none.

   Only tabs get it (the actor is for the "browsers" group): an extension's popup, its background page and a
   sidebar are never given the constant. */

export const SCREEN = Object.freeze({ width: 1920, height: 1080 });

const FPP = "privacy.fingerprintingProtection";
const FPP_PRIVATE = "privacy.fingerprintingProtection.pbmode";

/** Whether the engine's fingerprinting protection is on for this kind of window (nsRFPService::IsFPPEnabled). */
export function protectionOn(isPrivate) {
  return Services.prefs.getBoolPref(FPP, false) || (isPrivate && Services.prefs.getBoolPref(FPP_PRIVATE, false));
}

const OVERRIDES = "privacy.fingerprintingProtection.overrides";
const TARGET = "ScreenSizeConstant"; // Nulavio's engine patch 0012
let known = null;

/** Whether the set of protections in `overrides` turns `target` on, read exactly as the engine reads the list
    (nsRFPService::CreateOverridesFromText): entries between commas with no space skipped, the first character
    + or -, the rest the name; the last entry that names the target, or every target at once, decides. An entry
    the engine would skip (a space before the sign, another first character) is skipped here too: taking it for
    on would leave the screen to an engine that is not giving it. Pure. */
export function turnsOn(overrides, target) {
  let on = false;
  for (const item of String(overrides ?? "").split(",")) {
    const name = item.slice(1);
    if ((item[0] === "+" || item[0] === "-") && (name === target || name === "AllTargets")) {
      on = item[0] === "+";
    }
  }
  return on;
}

/** Whether the engine gives each document the constant screen itself (ADR 0016): it has the target, which
    Nulavio's patch 0012 adds, and the set of protections turns it on. The engine then asks every document, a
    frame and a pop-up too, and the per-tab size below is left unset. On an engine from before the patch, or
    with a set that leaves the target out, the tab's size is what gives pages the constant. */
export function engineDecides() {
  if (known === null) {
    try {
      known = TARGET in ChromeUtils.importESModule("resource://gre/modules/RFPTargetConstants.sys.mjs").Targets;
    } catch {
      known = false;
    }
  }
  return known && turnsOn(Services.prefs.getStringPref(OVERRIDES, ""), TARGET);
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

/** Whether a page is due the constant: the protection is on for its kind of window, the person did not exempt
    its site with the shield (the engine's own record, in the page's cookie jar settings), and it is a page of
    the web. The browser's own pages and an extension's are not: the engine keeps its fingerprinting protection
    away from them too, and an extension may place its windows by the screen's size. */
export function wantsConstant(principal, cookieJarSettings, isPrivate) {
  if (!protectionOn(isPrivate) || engineDecides()) {
    return false; // nothing to protect, or the engine answers each document itself
  }
  if (principal?.isSystemPrincipal || principal?.addonPolicy || principal?.schemeIs?.("moz-extension")) {
    return false;
  }
  try {
    return !cookieJarSettings?.isOnContentBlockingAllowList;
  } catch {
    return true; // no answer from the engine: the page is treated as any other
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
    // The engine answers each document itself: the tab's size is not this module's to set or to clear. It is
    // also what WebDriver BiDi's screen emulation sets, which a clear at every page load would undo. (Where the
    // set of protections changes while pages are open, the parent clears what this module had set.)
    if (engineDecides()) {
      return;
    }
    const doc = this.document;
    setScreen(context, wantsConstant(doc.nodePrincipal, doc.cookieJarSettings, context.usePrivateBrowsing));
  }
}
