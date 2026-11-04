/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio's appearance options (UX6): window density, the accent, "Mais contraste", and the new
   tab's optional ambience with "Reduzir transparência" (D-UX10: solid everywhere else).
   shared/options.json declares each option once, with the one pref it writes and the pref value
   of each choice; this module writes nothing else, and tests/unit/test_personalisation.py proves
   that no declared pref is a protection. The colours themselves come from the token variants
   (docs/brand/tokens.json): the window and about: pages follow the pref through -moz-pref(), and
   Shell pages through the attributes lib/appearance.js sets from state().

   Never written here: the system's LookAndFeel prefs (ui.useAccessibilityTheme,
   ui.prefersReducedTransparency, browser.display.document_color_use). Those change what every
   website can see; "Mais contraste" only restyles Nulavio's own surfaces. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
});

const OPTIONS_URL = "resource://builtin-addons/nulavio-shell/shared/options.json";
/** The options this module writes (the others in the list have their own writers). */
export const APPEARANCE = Object.freeze(["density", "accent", "moreContrast", "newtabAmbience", "reduceTransparency"]);
const SYSTEM_QUERIES = Object.freeze({
  moreContrast: "(prefers-contrast: more)",
  forcedColors: "(forced-colors: active)",
  reducedTransparency: "(prefers-reduced-transparency: reduce)",
});

export class PersonaliseError extends Error {
  constructor(code) {
    super(code);
    this.name = "PersonaliseError";
    this.code = code;
  }
}

let options = null;

async function load() {
  if (!options) {
    const text = await new Promise((resolve, reject) => {
      lazy.NetUtil.asyncFetch({ uri: OPTIONS_URL, loadUsingSystemPrincipal: true }, (stream, status) => {
        if (!Components.isSuccessCode(status)) {
          reject(new PersonaliseError("options-missing"));
          return;
        }
        resolve(lazy.NetUtil.readInputStreamToString(stream, stream.available(), { charset: "UTF-8" }));
      });
    });
    const list = JSON.parse(text).options.filter(o => APPEARANCE.includes(o.id));
    options = new Map(list.map(o => [o.id, Object.freeze(o)]));
  }
  return options;
}

async function option(id) {
  const found = (await load()).get(id);
  if (!found || found.writer !== "NulavioPersonalise" || found.prefs.length !== 1) {
    throw new PersonaliseError("unknown-option");
  }
  return found;
}

function read(entry) {
  const [pref] = entry.prefs;
  if (!Services.prefs.prefHasUserValue(pref)) {
    return entry.values[entry.prefValues.indexOf(null)];
  }
  let current;
  switch (Services.prefs.getPrefType(pref)) {
    case Services.prefs.PREF_INT:
      current = Services.prefs.getIntPref(pref);
      break;
    case Services.prefs.PREF_BOOL:
      current = Services.prefs.getBoolPref(pref);
      break;
    default:
      current = Services.prefs.getStringPref(pref);
  }
  const index = entry.prefValues.indexOf(current);
  // A value Nulavio does not offer (set elsewhere, e.g. about:config) reads as the default.
  return index === -1 ? entry.default : entry.values[index];
}

function systemWindow() {
  for (const win of Services.wm.getEnumerator("navigator:browser")) {
    if (!win.closed) {
      return win;
    }
  }
  return Services.appShell.hiddenDOMWindow;
}

export const NulavioPersonalise = {
  /** Every appearance option's current choice, which ones an administrator locked, and what the
      system already asks for (global LookAndFeel: the same in every window). */
  async state() {
    const list = await load();
    const out = { locked: {}, system: {} };
    for (const [id, entry] of list) {
      out[id] = read(entry);
      out.locked[id] = Services.prefs.prefIsLocked(entry.prefs[0]);
    }
    const win = systemWindow();
    for (const [name, query] of Object.entries(SYSTEM_QUERIES)) {
      out.system[name] = Boolean(win?.matchMedia(query).matches);
    }
    return out;
  },

  /** Set one option to one of its declared values; the default clears the pref. */
  async set(id, value) {
    const entry = await option(id);
    const index = entry.values.indexOf(value);
    if (index === -1) {
      throw new PersonaliseError("invalid-value");
    }
    const [pref] = entry.prefs;
    if (Services.prefs.prefIsLocked(pref)) {
      throw new PersonaliseError("personalise-locked");
    }
    const prefValue = entry.prefValues[index];
    if (prefValue === null) {
      Services.prefs.clearUserPref(pref);
    } else if (entry.prefType === "int") {
      Services.prefs.setIntPref(pref, prefValue);
    } else if (entry.prefType === "bool") {
      Services.prefs.setBoolPref(pref, prefValue);
    } else {
      Services.prefs.setStringPref(pref, prefValue);
    }
    return this.state();
  },

  /** Settings > Atalhos: the engine's list of every browser shortcut, in the caller's window. */
  openKeyboardShortcuts(win) {
    if (!win || win.closed || typeof win.openTrustedLinkIn !== "function") {
      throw new PersonaliseError("no-window");
    }
    win.openTrustedLinkIn("about:keyboard", "tab");
  },

  /** Calls `listener` when an option's pref or the system's appearance changes. Returns unsubscribe. */
  subscribe(listener) {
    const changed = () => listener();
    let prefs = null;
    let gone = false;
    Services.obs.addObserver(changed, "look-and-feel-changed");
    load().then(list => {
      if (gone) {
        return;
      }
      prefs = [...list.values()].map(entry => entry.prefs[0]);
      for (const pref of prefs) {
        Services.prefs.addObserver(pref, changed);
      }
      changed(); // whatever changed before the observers were in place is read again
    }, console.error);
    return () => {
      gone = true;
      for (const pref of prefs ?? []) {
        Services.prefs.removeObserver(pref, changed);
      }
      Services.obs.removeObserver(changed, "look-and-feel-changed");
    };
  },
};
