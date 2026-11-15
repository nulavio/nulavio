/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Meeting links, per profile (#221): "open in the app" (the default: the engine asks before handing a meeting
   app's link to its app, as always) or "join in the browser". In the browser, the meeting apps' link schemes
   are not handed to any app, so the engine asks nothing and the service's own page stays, with its own way to
   join from the browser (Zoom's "Join from your browser", Teams' "Continue on this browser"). No address is
   rewritten: the services document no per-meeting browser address (maintainer's decision, 2026-11-15).

   It is the engine's own switch, network.protocol-handler.external.<scheme> = false: a link, a script or a
   frame that asks for the scheme then does nothing, and the page is left as it was (measured on the 160 build
   with an app registered for zoommtg:). */

export const PREF = "nulavio.meetings.join"; // shared/options.json: "app" (cleared) or "browser"
export const SCHEMES = Object.freeze(["zoommtg", "zoomus", "msteams"]);

const external = scheme => `network.protocol-handler.external.${scheme}`;

/** Make the engine's switches match the profile's choice. A switch is cleared only when the choice has just
    changed to "app", never at a start: a false set by the person (about:config, user.js) stays. */
function apply(changed) {
  const browser = Services.prefs.getStringPref(PREF, "") === "browser";
  for (const scheme of SCHEMES) {
    const pref = external(scheme);
    if (Services.prefs.prefIsLocked(pref)) {
      continue; // a policy decides
    }
    if (browser) {
      Services.prefs.setBoolPref(pref, false);
    } else if (changed && Services.prefs.prefHasUserValue(pref) && !Services.prefs.getBoolPref(pref, true)) {
      Services.prefs.clearUserPref(pref);
    }
  }
}

let observer = null;

export const NulavioMeetings = {
  /** From the Shell's start: the switches follow the choice, now and whenever it changes. */
  watch() {
    if (observer) {
      return;
    }
    observer = { observe: () => apply(true) };
    Services.prefs.addObserver(PREF, observer);
    apply(false);
  },

  unwatch() {
    if (observer) {
      Services.prefs.removeObserver(PREF, observer);
      observer = null;
    }
  },
};
