/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* What's new in this version (#198, the maintainer's decision of 2026-11-14).

   The notes are the reviewed record of the installed version, packed by the release
   build next to the engine (distribution/whats-new.json, make_distribution.py): read
   from disk, never fetched, so they work offline and never show another version's
   notes. A development build has none, and says so.

   After a real update (this profile last saw an older version), one discreet bar in
   one ordinary window, once per version and profile: no tab, no focus taken. A new
   profile's first run is not an update. Private windows, temporary profiles and an
   agent's browser never show it and never change the state; a protected profile runs
   only once unlocked. "Show what's new after updating" in Settings turns the bar off;
   the notes stay in the Help menu and in Settings. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioAI: "resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs",
  NulavioPrivacy: "resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs",
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
  SessionStore: "resource:///modules/sessionstore/SessionStore.sys.mjs",
});

export const RECORD_FILE = "whats-new.json";
/* The newest version this profile was told about (or saw first): the bar shows only for a newer one. */
export const PREF_SEEN = "nulavio.whatsnew.seen";
export const PREF_NOTICE = "nulavio.whatsnew.notice";
const BAR = "nulavio-whatsnew";
const MENU_ITEM = "nulavio-whatsnew-menu";
const READER = "whatsnew/whatsnew.html";
const LOCALES = ["pt-BR", "en-US"];
const LISTS = ["new", "fixed", "action", "breaking"];
const VERSION = /^([0-9]+(?:\.[0-9]+)+)-([0-9]+(?:\.[0-9]+)*)$/;
const GHSA = /^GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** [[firefox parts], [release parts]] of "160.0-0.4", or null. */
export function versionKey(version) {
  const match = typeof version === "string" ? VERSION.exec(version) : null;
  return match ? [match[1].split(".").map(Number), match[2].split(".").map(Number)] : null;
}

function compareParts(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    if (d) {
      return Math.sign(d);
    }
  }
  return 0;
}

/** -1, 0 or 1, as versions sort (the engine first, then Nulavio's revision). */
export function compareVersions(a, b) {
  const [ka, kb] = [versionKey(a), versionKey(b)];
  return compareParts(ka[0], kb[0]) || compareParts(ka[1], kb[1]);
}

const isText = (value, max) => typeof value === "string" && value.trim() !== "" && value.length <= max;

/**
 * The record, checked again here (the build checked it with scripts/release/whats_new.py): a file
 * that is not one is reported as unreadable, never shown in part. Its text is only ever put in
 * textContent by the reader.
 */
export function checkRecord(data) {
  if (!data || typeof data !== "object" || Array.isArray(data) || !versionKey(data.version)) {
    return null;
  }
  if (!DATE.test(data.date ?? "") || !isText(data.channel, 16) || data.firefox !== VERSION.exec(data.version)[1]) {
    return null;
  }
  for (const locale of LOCALES) {
    const entry = data[locale];
    if (!entry || typeof entry !== "object" || !isText(entry.summary, 500)) {
      return null;
    }
    for (const key of LISTS) {
      const items = entry[key] ?? [];
      if (!Array.isArray(items) || items.length > 20 || !items.every(item => isText(item, 300))) {
        return null;
      }
    }
  }
  const security = data.security ?? [];
  if (!Array.isArray(security) || !security.every(id => typeof id === "string" && GHSA.test(id))) {
    return null;
  }
  return data;
}

class WhatsNew {
  #record = undefined; // undefined: not read yet; null: none in this build; false: unreadable
  #texts = null;
  #waiting = []; // what each new ordinary window still has to get: the menu entry, the bar
  #observing = false;
  #menus = false;
  #shown = false;

  /** The packed record of the installed version: { state: "ok", record } | { state: "none" } | { state: "unreadable" }. */
  async read() {
    if (this.#record === undefined) {
      const path = PathUtils.join(Services.dirsvc.get("XREAppDist", Ci.nsIFile).path, RECORD_FILE);
      if (!(await IOUtils.exists(path).catch(() => false))) {
        this.#record = null;
      } else {
        this.#record = checkRecord(await IOUtils.readJSON(path).catch(() => null)) ?? false;
      }
    }
    if (this.#record === null) {
      return { state: "none" };
    }
    return this.#record === false ? { state: "unreadable" } : { state: "ok", record: this.#record };
  }

  /** For the tests: the record as if packed (undefined reads the file again). */
  useRecordForTest(data) {
    this.#record = data === undefined ? undefined : checkRecord(data) ?? false;
    this.#shown = false;
  }

  /** What the reader shows: one language of the record, and the version this profile came from. */
  async notes(language) {
    const read = await this.read();
    if (read.state !== "ok") {
      return { state: read.state };
    }
    const { record } = read;
    const locale = String(language).toLowerCase().startsWith("pt") ? "pt-BR" : "en-US";
    const entry = record[locale];
    return {
      state: "ok",
      locale,
      version: record.version,
      date: record.date,
      channel: record.channel,
      firefox: record.firefox,
      summary: entry.summary,
      ...Object.fromEntries(LISTS.map(key => [key, [...(entry[key] ?? [])]])),
      security: [...(record.security ?? [])],
    };
  }

  setting() {
    return { notice: Services.prefs.getBoolPref(PREF_NOTICE, true) };
  }

  setNotice(on) {
    Services.prefs.setBoolPref(PREF_NOTICE, Boolean(on));
    if (!on) {
      this.#closeBars();
    }
  }

  /**
   * Whether this start is an update this profile should hear about, and records what it saw.
   * "show" (with the version it came from, or "" when unknown), or why not.
   */
  async decide() {
    const read = await this.read();
    if (read.state !== "ok") {
      return { decision: read.state };
    }
    const version = read.record.version;
    const temporary = Services.prefs.getBoolPref("nulavio.profile.temporary", false)
      || (await lazy.NulavioProfiles.temporaryState()).temporary;
    if (temporary || (await lazy.NulavioAI.workspaceAgent())) {
      return { decision: "not-here", version }; // nothing is shown and nothing is recorded
    }
    const seen = Services.prefs.getStringPref(PREF_SEEN, "");
    if (!versionKey(seen)) {
      // Never recorded: a new profile on its first run (not an update), or a profile from a build
      // before this one existed (an update, from a version it cannot know).
      if (lazy.NulavioPrivacy.firstRun().active) {
        Services.prefs.setStringPref(PREF_SEEN, version);
        return { decision: "first-run", version };
      }
    } else if (compareVersions(version, seen) <= 0) {
      return { decision: compareVersions(version, seen) ? "older" : "seen", version, from: seen };
    }
    const from = versionKey(seen) ? seen : "";
    if (!Services.prefs.getBoolPref(PREF_NOTICE, true)) {
      Services.prefs.setStringPref(PREF_SEEN, version);
      return { decision: "off", version, from };
    }
    return { decision: "show", version, from };
  }

  /**
   * When the Shell starts with the browser (the experiment's onStartup, with the words in the
   * user's language): the Help menu entry in every window, then the bar if this is an update.
   */
  atStartup(texts) {
    this.#texts = texts;
    lazy.SessionStore.promiseAllWindowsRestored.then(() => this.start())
      .catch(e => console.error("Nulavio what's new", e));
  }

  async start() {
    const read = await this.read();
    if (!this.#menus) {
      this.#menus = true;
      this.#eachWindow(win => this.#addMenuItem(win));
    }
    if (read.state !== "ok") {
      return { decision: read.state };
    }
    const outcome = await this.decide();
    if (outcome.decision === "show") {
      this.#showOnce(outcome);
    }
    return outcome;
  }

  /** The reader in a new tab of `win` (the Help menu, the bar, Settings). */
  openReader(win) {
    const url = WebExtensionPolicy.getByID("shell@nulavio.net")?.getURL(READER);
    if (url && win && !win.closed) {
      win.openTrustedLinkIn(url, "tab", { inBackground: false }); // asked for: it comes to the front
    }
  }

  // -- the bar and the menu ---------------------------------------------------------

  #eligible(win) {
    // An ordinary window: not private, and not a pop-up that hides its toolbars.
    const hidden = win?.document?.documentElement.getAttribute("chromehidden") ?? "";
    return win && !win.closed && win.gNotificationBox && !lazy.PrivateBrowsingUtils.isWindowPrivate(win) && !hidden.includes("toolbar");
  }

  /** One bar, in the first ordinary window; with only private windows open, the next ordinary one. */
  #showOnce(outcome) {
    const show = win => {
      if (this.#shown || !this.#eligible(win) || !this.#texts) {
        return false;
      }
      this.#shown = true;
      // Recorded when shown: closing it, or restarting without reading, never brings it back for this version.
      Services.prefs.setStringPref(PREF_SEEN, outcome.version);
      if (!Services.prefs.getBoolPref(PREF_NOTICE, true)) {
        return true; // turned off while it waited for an ordinary window
      }
      const box = win.gNotificationBox;
      const label = outcome.from ? this.#texts.barFrom(outcome.from, outcome.version) : this.#texts.bar(outcome.version);
      const button = {
        label: String(this.#texts.button),
        callback: () => {
          this.openReader(win);
          return false;
        },
      };
      box.appendNotification(BAR, { label: String(label), priority: box.PRIORITY_INFO_LOW }, [button]);
      return true;
    };
    const top = Services.wm.getMostRecentWindow("navigator:browser");
    if (show(top)) {
      return;
    }
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (show(win)) {
        return;
      }
    }
    this.#watchWindows(win => show(win));
  }

  #addMenuItem(win) {
    const doc = win?.document;
    const popup = doc?.getElementById("menu_HelpPopup");
    if (!popup || !this.#texts || doc.getElementById(MENU_ITEM)) {
      return;
    }
    const item = doc.createXULElement("menuitem");
    item.id = MENU_ITEM;
    item.setAttribute("label", String(this.#texts.menu));
    // The app menu's Help view copies these items and runs them through doCommand(): a command listener serves both.
    item.addEventListener("command", () => this.openReader(win));
    const about = doc.getElementById("aboutName");
    popup.insertBefore(item, about?.parentNode === popup ? about : null);
  }

  #eachWindow(fn) {
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      fn(win);
    }
    this.#watchWindows(win => (fn(win), false));
  }

  /** `fn` runs for every window opened from now on, until it returns true. */
  #watchWindows(fn) {
    this.#waiting.push(fn);
    if (!this.#observing) {
      this.#observing = true;
      Services.obs.addObserver(win => {
        this.#waiting = this.#waiting.filter(waiting => !waiting(win));
      }, "browser-delayed-startup-finished");
    }
  }

  #closeBars() {
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      win.gNotificationBox?.getNotificationWithValue(BAR)?.close();
    }
  }
}

export const NulavioWhatsNew = new WhatsNew();
