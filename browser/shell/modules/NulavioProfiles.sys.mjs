/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio Profiles (docs/adr/0003-nulavio-profiles-and-routing.md).

   A thin layer over the engine's own profile management
   (SelectableProfileService). Each profile is a separate engine instance with
   its own directory: cookies, storage, history, extensions, saved passwords
   and search settings never mix. Nulavio adds templates, an identity colour
   and the toolbar selector; creating, switching and deleting are the
   engine's operations, including its profile lock (a running profile cannot
   be deleted). Switching starts or activates the other profile through the
   engine's local remote service or an argument list; never a shell. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AsyncShutdown: "resource://gre/modules/AsyncShutdown.sys.mjs",
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
  setTimeout: "resource://gre/modules/Timer.sys.mjs",
  vaultHelper: "resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs",
  SelectableProfileService: "resource:///modules/profiles/SelectableProfileService.sys.mjs",
  ENABLED_PREF: "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs",
  RULES_PREF: "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs",
  normalizeHost: "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs",
  parseRules: "resource://builtin-addons/nulavio-shell/modules/NulavioRouter.sys.mjs",
});

/** Identity colour per profile id, shared by every profile of the group (JSON). */
export const PREF_COLORS = "nulavio.profiles.colors";
/* The engine turns its own start-up profile chooser on when a profile group is made. That page knows
   nothing of the Vault: a protected profile is listed there like any other, and choosing it ends the
   start in an error (its folder is empty until the Vault opens it). Profiles are switched and unlocked
   from the band's menu instead, so Nulavio turns the chooser off once per group; this shared pref
   records it, and a later choice of the person (the engine's own checkbox) stays. */
export const PREF_START_CHOOSER = "nulavio.profiles.startChooserAdopted";
/* The profile a plain start opens. The engine makes it the profile used last: it rewrites the group's entry in
   profiles.ini as a profile starts and whenever one of its windows is activated. A protected profile is locked
   again when its last window closes, and its folder is then empty: started there, the engine makes a new, empty
   profile outside the group instead (seen on 160.0: the first run again, and no way back to the person's
   profiles from that window). So a protected profile is never left as the start-up profile: the engine's own
   function is given the unprotected profile used last, which this shared pref names (its id in the group). */
export const PREF_START_PROFILE = "nulavio.profiles.startProfile";
// The band's profile summary is rebuilt at least this often, even without a change notice.
const BAND_CACHE_MS = 30000;
const PREF_COLOR_MIGRATION = "nulavio.profiles.colors.farol";
const LEGACY_COLORS = ["mint", "sky", "violet", "rose", "sand", "slate"];

/** Colour keys; the values are design tokens (--nv-color-identity-<key>). */
export const COLORS = Object.freeze(["lima", "sky", "violet", "coral", "sand", "slate"]);

/** Icons the engine ships (SelectableProfile STANDARD_AVATARS) offered by Nulavio. */
export const AVATARS = Object.freeze([
  "heart", "briefcase", "diamond", "book", "leaf", "star", "folder", "lightbulb",
  "palette", "plane", "shopping", "message", "history", "sparkle-single",
]);

/** File the launcher writes into a temporary profile (launcher/nulavio_launcher/temporary.py). */
export const TEMPORARY_MARKER = "nulavio-temporary.json";

/* Templates are starting points (name, icon, colour), never mandatory
   profiles. A temporary profile is not a template: it is opened with
   openTemporary() and deleted by the Nulavio tools when it closes.

   "Sensitive sites" also writes settings into the new profile's user.js
   (docs/security/phase5-spikes.md): its cookies, site data, history and cache
   are deleted every time it closes, and web pages cannot install extensions in
   it. Being its own profile, it has its own extensions: those of the user's
   other profiles never see its pages. */
export const TEMPLATES = Object.freeze([
  Object.freeze({ id: "personal", avatar: "heart", color: "lima" }),
  Object.freeze({ id: "work", avatar: "briefcase", color: "sky" }),
  Object.freeze({ id: "banking", avatar: "diamond", color: "sand" }),
  Object.freeze({ id: "research", avatar: "book", color: "violet" }),
  Object.freeze({ id: "sensitive", avatar: "history", color: "slate" }),
]);

const KIND_PREF = "nulavio.profile.kind";
/** What the "Sensitive sites" template writes into the profile (engine prefs only). */
export const SENSITIVE_PREFS = Object.freeze({
  [KIND_PREF]: "sensitive",
  "privacy.sanitize.sanitizeOnShutdown": true,
  "privacy.clearOnShutdown_v2.cookiesAndStorage": true,
  "privacy.clearOnShutdown_v2.cache": true,
  "privacy.clearOnShutdown_v2.browsingHistoryAndDownloads": true,
  "privacy.clearOnShutdown_v2.formdata": true,
  "browser.formfill.enable": false,
  "xpinstall.enabled": false, // no installs started by web pages (addons.mozilla.org included)
});

function userJs(prefs, title) {
  const lines = Object.entries(prefs).map(([k, v]) => `user_pref(${JSON.stringify(k)}, ${JSON.stringify(v)});`);
  return `// ${title}\n// Written by Nulavio when this profile was created. Deleting this file turns these settings off.\n${lines.join("\n")}\n`;
}

export class ProfilesError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "ProfilesError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new ProfilesError(code, message);
}

export function normalizeProfileName(raw) {
  const name = String(raw ?? "").trim().replace(/\s+/g, " ");
  if (!name || name.length > 60 || /[\u0000-\u001f\u007f/\\]/.test(name)) {
    fail("invalid-name");
  }
  return name;
}

// A new install's profiles come with the engine's own names ("default-release", "default"), and
// the engine names the first profile it puts in a group "Original profile". Neither is a name the
// person chose. The profile they started with keeps its name, or is "Personal" (the first template).
const ENGINE_PROFILE_NAME = /^default(-[a-z]+)?$/;

/** The name the profile the person started with shows, before and after the group exists. */
export function startingProfileName(toolkitName) {
  if (toolkitName && !ENGINE_PROFILE_NAME.test(toolkitName)) {
    try {
      return normalizeProfileName(toolkitName);
    } catch {
      // Not a usable name: fall through to the template's.
    }
  }
  return WebExtensionPolicy.getByID("shell@nulavio.net")?.extension?.localizeMessage("templatePersonal") || "Personal";
}

function checkColor(color) {
  if (!COLORS.includes(color)) {
    fail("invalid-color");
  }
  return color;
}

function checkAvatar(avatar) {
  if (!AVATARS.includes(avatar)) {
    fail("invalid-avatar");
  }
  return avatar;
}

class NulavioProfilesClass {
  #listeners = new Set();
  #observing = false;
  #avatarCache = new Map();
  #temporary = null;
  #migratingColors = null;
  // The band's view of the current profile (name, colour, avatar), rebuilt only
  // when the group store or the colours change, or after BAND_CACHE_MS at most.
  #band = null;
  #bandAt = 0;
  #storeSetup = null;
  #startKept = false;

  get #service() {
    return lazy.SelectableProfileService;
  }

  /**
   * Profiles need the engine's profile service, which works for profiles
   * registered in profiles.ini (the normal way to start Nulavio). A profile
   * started with --profile <dir> (Track A launcher, test harness) is not
   * registered, so switching is not offered there.
   */
  availability() {
    const service = this.#service;
    if (!Services.prefs.getBoolPref("browser.profiles.enabled", false)) {
      return { available: false, reason: "disabled" };
    }
    if (!service.isEnabled) {
      return { available: false, reason: "unregistered" };
    }
    return { available: true, reason: null };
  }

  #requireAvailable() {
    const { available, reason } = this.availability();
    if (!available) {
      fail(reason);
    }
  }

  // Gecko shares one init promise between normal reads and first-store setup.
  // A normal init in the middle of setup sees an empty database and resets it.
  // Finish earlier reads first, then hold new readers until setup completes.
  // Shared by all Shell writers, including routing preferences.
  ensureStore() {
    this.#requireAvailable();
    if (!this.#storeSetup) {
      const setup = (async () => {
        await this.#service.init();
        const joining = !this.#service.currentProfile;
        const name = startingProfileName(this.#service.groupToolkitProfile?.name);
        await this.#service.maybeSetupDataStore();
        // The engine named this profile "Original profile" as it joined the group: keep the name the
        // band showed until now (review 2026-11-09 V3).
        const current = this.#service.currentProfile;
        if (joining && current && current.name !== name) {
          await current.setNameAsync(name);
        }
        await this.#adoptStartChooser();
        await this.#keepStartProfile();
        // Setting up the store can give this profile its id and group name: the band's cached
        // summary (and the new tab's rules here) must not wait 30 s to see them.
        this.#band = null;
      })().finally(() => {
        if (this.#storeSetup === setup) {
          this.#storeSetup = null;
        }
      });
      this.#storeSetup = setup;
    }
    return this.#storeSetup;
  }

  /** Once per profile group: the engine's start-up chooser off (PREF_START_CHOOSER). */
  async #adoptStartChooser() {
    const service = this.#service;
    if (Services.prefs.getBoolPref(PREF_START_CHOOSER, false) || !service.currentProfile) {
      return;
    }
    try {
      await service.setShowProfileSelectorWindow(false);
      Services.prefs.setBoolPref(PREF_START_CHOOSER, true);
      await service.trackPref(PREF_START_CHOOSER);
    } catch (e) {
      console.error("Nulavio Profiles: start-up chooser", e);
    }
  }

  /** "plain", "locked" or "unlocked"; "unknown" when it could not be read, which is never taken for unprotected. */
  async #protection(profile) {
    return lazy.profileLockState(profile.path).catch(() => "unknown");
  }

  /** Once per instance: a protected profile is never left as the start-up profile (PREF_START_PROFILE). */
  async #keepStartProfile() {
    const service = this.#service;
    if (this.#startKept || !service.currentProfile) {
      return;
    }
    this.#startKept = true;
    const plain = async profile => (await this.#protection(profile)) === "plain";
    /** The profile to start in instead of a protected one: the unprotected one used last, else the oldest.
        Read from the group as it is now, so a profile deleted since is never chosen. */
    const instead = async wanted => {
      const here = service.currentProfile;
      const others = [];
      for (const each of await service.getAllProfiles()) {
        // Never the one asked for. And when another profile than this instance's was asked for, never this
        // instance's own either: the engine asks for another one only as it deletes or resets this one.
        if (each.id === wanted.id || (here && wanted.id !== here.id && each.id === here.id)) {
          continue;
        }
        if (await plain(each)) {
          others.push(each);
        }
      }
      const last = Services.prefs.getIntPref(PREF_START_PROFILE, 0);
      return others.find(each => each.id === last) ?? others.sort((a, b) => a.id - b.id)[0] ?? null;
    };
    const engine = service.setDefaultProfileForGroup.bind(service);
    /** The engine calls this by name as it starts, on every window activation and when a profile is deleted
        or reset. Answers the profile that was made the start-up one, or null when there was none to make. */
    service.setDefaultProfileForGroup = async (wanted = service.currentProfile) => {
      if (!wanted) {
        return null;
      }
      if (await plain(wanted)) {
        await engine(wanted);
        if (Services.prefs.getIntPref(PREF_START_PROFILE, 0) !== wanted.id) {
          Services.prefs.setIntPref(PREF_START_PROFILE, wanted.id);
          await service.trackPref(PREF_START_PROFILE);
        }
        return wanted;
      }
      // With no unprotected profile left there is nothing to start in: the entry stays as the engine wrote it.
      const start = await instead(wanted);
      if (start) {
        await engine(start);
      }
      return start;
    };
    // The engine's own pages delete the profile of their window through this.
    const remove = service.deleteCurrentProfile.bind(service);
    service.deleteCurrentProfile = async (...args) => {
      await this.#keepOneUnprotected(service.currentProfile);
      return remove(...args);
    };
    try {
      const start = await service.setDefaultProfileForGroup(); // the engine already ran its own, before any window
      if (!(await plain(service.currentProfile))) {
        // Seen on 160.0: the engine's write inside the call above does not reach profiles.ini while the write it
        // made as this profile started is still under way (a write waits up to five seconds for an instance that
        // is starting), and that one can land last. So the entry is written again now, once more when that wait
        // is over, and when this instance closes. Each time the start-up profile is worked out again from the
        // group as it is then: the one chosen before may have been deleted, or another may have been used since.
        const profiles = Cc["@mozilla.org/toolkit/profile-service;1"].getService(Ci.nsIToolkitProfileService);
        const again = async () => {
          try {
            if (await service.setDefaultProfileForGroup()) {
              await profiles.asyncFlushCurrentProfile();
            }
          } catch (e) {
            console.error("Nulavio Profiles: start-up profile", e);
          }
        };
        if (start) {
          await profiles.asyncFlushCurrentProfile(); // at once: every moment before it is one a kill leaves the entry wrong
        }
        lazy.setTimeout(again, 6000);
        lazy.AsyncShutdown.quitApplicationGranted.addBlocker("Nulavio: the start-up profile is not a protected one", again);
      }
    } catch (e) {
      console.error("Nulavio Profiles: start-up profile", e);
    }
  }

  /** A plain start needs a profile it can open without a password: while a protected profile exists, the last
      unprotected one is not deleted. Without it every start made a new, empty profile outside the group. A
      profile whose state could not be read counts as neither: it is not the spare one, and it may be the last. */
  async #keepOneUnprotected(target) {
    if (!target || ["locked", "unlocked"].includes(await this.#protection(target))) {
      return;
    }
    const others = (await this.#service.getAllProfiles()).filter(each => each.id !== target.id);
    const states = await Promise.all(others.map(each => this.#protection(each)));
    if (others.length && !states.includes("plain")) {
      fail("last-unprotected");
    }
  }

  // -- colours (shared across the group) ---------------------------------

  colors() {
    try {
      const map = JSON.parse(Services.prefs.getStringPref(PREF_COLORS, "{}"));
      return map && typeof map === "object" && !Array.isArray(map) ? map : {};
    } catch {
      return {};
    }
  }

  #colorMigration() {
    try {
      const value = JSON.parse(Services.prefs.getStringPref(PREF_COLOR_MIGRATION, "{}"));
      if (Number.isInteger(value?.version) && value.version > 2) {
        return { version: value.version, mint: [] }; // future payloads need not use this release's schema
      }
      if (Number.isInteger(value?.version) && Array.isArray(value.mint)) {
        return { version: value.version, mint: value.mint.filter(id => Number.isSafeInteger(id) && id > 0) };
      }
    } catch {
      // A missing/invalid record is retried without changing other profile data.
    }
    return { version: 0, mint: [] };
  }

  /** Upgrade legacy colour keys only. The record is shared, and later choices always win. */
  async #migrateColors(profiles) {
    if (this.#migratingColors) {
      return this.#migratingColors;
    }
    this.#migratingColors = (async () => {
      const previous = this.#colorMigration();
      if (previous.version > 2) {
        return; // a newer release owns its migration record
      }
      let map;
      try {
        map = JSON.parse(Services.prefs.getStringPref(PREF_COLORS, "{}"));
      } catch {
        return; // do not overwrite malformed or future data
      }
      if (!map || typeof map !== "object" || Array.isArray(map)) {
        return;
      }
      const mint = new Set(previous.mint);
      let changed = false;
      for (const profile of profiles) {
        const id = String(profile.id);
        // The first palette also supplied an implicit colour for profiles with no stored choice.
        const fallback = previous.version < 2 ? LEGACY_COLORS[(profile.id - 1) % LEGACY_COLORS.length] : null;
        const old = Object.hasOwn(map, id) ? map[id] : fallback;
        if (old === "mint" || old === "rose") {
          map[id] = old === "mint" ? "lima" : "coral";
          if (old === "mint") {
            mint.add(profile.id);
          }
          changed = true;
        }
      }
      if (previous.version < 2 || mint.size !== previous.mint.length) {
        // Record the notice first. If interrupted here, legacy keys are still upgraded on retry.
        Services.prefs.setStringPref(PREF_COLOR_MIGRATION, JSON.stringify({ version: 2, mint: [...mint] }));
        await this.#service.trackPref(PREF_COLOR_MIGRATION);
      }
      if (changed) {
        Services.prefs.setStringPref(PREF_COLORS, JSON.stringify(map));
        await this.#service.trackPref(PREF_COLORS);
      }
    })();
    try {
      await this.#migratingColors;
    } finally {
      this.#migratingColors = null;
    }
  }

  async #setColor(id, color) {
    await this.#migrateColors(await this.#service.getAllProfiles());
    const map = this.colors();
    if (color === null) {
      delete map[id];
    } else {
      map[id] = checkColor(color);
    }
    Services.prefs.setStringPref(PREF_COLORS, JSON.stringify(map));
    // The engine copies tracked prefs to the group store, so every profile sees them.
    await this.#service.trackPref(PREF_COLORS);
    const migration = this.#colorMigration();
    if (migration.version === 2 && migration.mint.includes(id)) {
      migration.mint = migration.mint.filter(other => other !== id);
      Services.prefs.setStringPref(PREF_COLOR_MIGRATION, JSON.stringify(migration));
      await this.#service.trackPref(PREF_COLOR_MIGRATION);
    }
  }

  #colorFor(profile, map) {
    const stored = map[String(profile.id)];
    return COLORS.includes(stored) ? stored : COLORS[(profile.id - 1 + COLORS.length) % COLORS.length];
  }

  // -- temporary profiles -------------------------------------------------

  /**
   * Whether this instance runs a temporary profile, and where it is kept.
   * Read from the launcher's marker in the profile folder; the browser never
   * deletes anything itself (the Nulavio tools do, after it exits).
   */
  async temporaryState() {
    if (!this.#temporary) {
      const marker = PathUtils.join(Services.dirsvc.get("ProfD", Ci.nsIFile).path, TEMPORARY_MARKER);
      const data = await IOUtils.readJSON(marker).catch(() => null);
      this.#temporary =
        data && typeof data === "object" && !Array.isArray(data)
          ? { temporary: true, inMemory: data.in_memory === true, swapOnDisk: data.swap_on_disk !== false }
          : { temporary: false, inMemory: false, swapOnDisk: false };
    }
    return this.#temporary;
  }

  /**
   * Open a new temporary profile in its own instance. The Nulavio tools create
   * it (in memory where the system allows) and start a watcher that deletes it
   * when that instance exits; the engine is started with an argument list.
   */
  async openTemporary() {
    const answer = await lazy.callTool(["temporary", "api"], { op: "create" });
    if (typeof answer?.path !== "string" || !answer.path.startsWith("/") || answer.path.includes("\0")) {
      fail("helper-failed");
    }
    const process = Cc["@mozilla.org/process/util;1"].createInstance(Ci.nsIProcess);
    process.init(Services.dirsvc.get("XREExeF", Ci.nsIFile));
    const args = ["--profile", answer.path];
    process.runw(false, args, args.length);
    return { inMemory: answer.inMemory === true, swapOnDisk: answer.swapOnDisk !== false };
  }

  /** In a temporary instance, a bar in every window says that its data is deleted on close. */
  async markTemporary(text) {
    if (!(await this.temporaryState()).temporary) {
      return;
    }
    const mark = win => {
      const box = win.gNotificationBox;
      if (!box || box.getNotificationWithValue("nulavio-temporary")) {
        return;
      }
      box.appendNotification("nulavio-temporary", { label: String(text), priority: box.PRIORITY_INFO_MEDIUM }, []);
    };
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      mark(win);
    }
    Services.obs.addObserver(subject => mark(subject), "browser-delayed-startup-finished");
  }

  /** What the UI may offer: templates, colours and icons. */
  options() {
    return { templates: TEMPLATES, colors: COLORS, avatars: AVATARS };
  }

  // -- reading ------------------------------------------------------------

  /** "sensitive" when the profile's own user.js still says so; null otherwise or when it cannot be read (locked). */
  async #kind(path) {
    try {
      const text = await IOUtils.readUTF8(PathUtils.join(path, "user.js"));
      return text.includes(`user_pref("${KIND_PREF}", "sensitive");`) ? "sensitive" : null;
    } catch {
      return null;
    }
  }

  /** Whether an instance has this profile open now (UX4 profile menu). The engine's lock symlink
      names its process, "<ip>:+<pid>", on Linux, as the launcher reads it (profile.py); a lock
      left by a crash names a process that is gone. Elsewhere: not known, so not shown. */
  async #running(path) {
    try {
      const lock = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
      lock.initWithPath(PathUtils.join(path, "lock"));
      if (!lock.isSymlink()) {
        return false;
      }
      const pid = /:\+(\d+)$/.exec(lock.target)?.[1];
      return Boolean(pid) && (await IOUtils.exists(`/proc/${pid}`));
    } catch {
      return false;
    }
  }

  async #describe(profile, map, currentId) {
    const lock = await lazy.profileLockState(profile.path).catch(() => "plain");
    const color = this.#colorFor(profile, map);
    const isCurrent = profile.id === currentId;
    return {
      running: isCurrent || (lock !== "locked" && (await this.#running(profile.path))),
      kind: lock === "locked" ? null : await this.#kind(profile.path),
      id: profile.id,
      name: profile.name,
      avatar: profile.avatar,
      color,
      colorMigration: color === "lima" && this.#colorMigration().mint.includes(profile.id) ? "mint-to-lima" : null,
      isCurrent,
      encrypted: lock !== "plain",
      locked: lock === "locked",
      path: profile.path,
    };
  }

  /**
   * Profiles of this group, current first. Reading never creates the group
   * store: before the first extra profile exists, only the current one is listed.
   */
  async list() {
    const temporary = await this.temporaryState();
    if (temporary.temporary) {
      // Not part of the profile group: no switching from here, and nothing to rename.
      const self = { id: null, name: "", avatar: null, color: "slate", isCurrent: true, temporary: true };
      return { available: false, reason: "temporary", temporary, profiles: [self] };
    }
    const availability = this.availability();
    if (!availability.available) {
      return { ...availability, profiles: [] };
    }
    const service = this.#service;
    if (this.#storeSetup) {
      await this.#storeSetup;
    } else if (!service.initialized) {
      // Idempotent; the Shell can start before the engine has opened the group store.
      await service.init().catch(e => console.error("Nulavio Profiles: profile service", e));
    }
    const current = service.currentProfile;
    if (!current) {
      const name = startingProfileName(service.groupToolkitProfile?.name);
      return { ...availability, profiles: [{ id: null, name, avatar: "default-favicon", color: COLORS[0], isCurrent: true }] };
    }
    const all = await service.getAllProfiles();
    await this.#migrateColors(all);
    const map = this.colors();
    const profiles = await Promise.all(all.map(p => this.#describe(p, map, current.id)));
    profiles.sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent));
    return { ...availability, profiles };
  }

  async current() {
    const { profiles } = await this.list();
    return profiles.find(p => p.isCurrent) ?? null;
  }

  /**
   * What the identity band shows for this instance: name, colour and avatar of
   * the current profile. The band asks every 1.5 s in every window; list()
   * reads every profile of the group (database, lock state, user.js) to answer
   * that, so this keeps one summary, rebuilt from the database when the engine
   * reports a change (sps-profiles-updated, from this or another instance), the
   * colours change, or BAND_CACHE_MS have passed. A failed read is not kept.
   */
  /** The new tab's "Você está em" line (UX4): the band's cached summary of this profile, its
      protection in the Vault's words ("plain", "unlocked" or "unknown") and the rules that open
      sites here. Reads no other profile, so a new tab stays cheap. */
  async here() {
    const [band, protection] = await Promise.all([
      this.currentForBand(),
      lazy.profileLockState(Services.dirsvc.get("ProfD", Ci.nsIFile).path).catch(() => "unknown"),
    ]);
    if (!band) {
      return null;
    }
    let routes = [];
    if (band.id !== null && Services.prefs.getBoolPref(lazy.ENABLED_PREF, true)) {
      routes = lazy
        .parseRules(Services.prefs.getStringPref(lazy.RULES_PREF, "[]"))
        .filter(rule => rule.profileId === band.id && rule.action === "open-in")
        .map(rule => {
          try {
            return lazy.normalizeHost(rule.value).display;
          } catch {
            return rule.value;
          }
        });
    }
    return {
      name: band.name,
      color: band.color,
      avatar: band.avatar,
      temporary: Boolean(band.temporary),
      protection: band.temporary ? "plain" : protection,
      routeCount: routes.length,
      routes: routes.slice(0, 5),
    };
  }

  currentForBand() {
    this.#observe();
    if (this.#band && Date.now() - this.#bandAt < BAND_CACHE_MS) {
      return this.#band;
    }
    const pending = this.#readBand();
    this.#band = pending;
    this.#bandAt = Date.now();
    pending.catch(() => {
      if (this.#band === pending) {
        this.#band = null;
      }
    });
    return pending;
  }

  async #readBand() {
    if ((await this.temporaryState()).temporary) {
      return { id: null, name: "", avatar: null, color: "slate", isCurrent: true, temporary: true };
    }
    if (!this.availability().available) {
      return null;
    }
    const service = this.#service;
    if (this.#storeSetup) {
      await this.#storeSetup;
    } else if (!service.initialized) {
      await service.init().catch(e => console.error("Nulavio Profiles: profile service", e));
    }
    const current = service.currentProfile;
    if (!current) {
      const name = startingProfileName(service.groupToolkitProfile?.name);
      return { id: null, name, avatar: "default-favicon", color: COLORS[0], isCurrent: true };
    }
    // A group made before Nulavio adopted the chooser (the alpha): once, on the first window after the update.
    await this.#adoptStartChooser();
    await this.#keepStartProfile();
    // currentProfile is not refreshed when another instance renames the profile; the database is.
    const profile = (await service.getProfile(current.id)) ?? current;
    return { id: profile.id, name: profile.name, avatar: profile.avatar, color: this.#colorFor(profile, this.colors()), isCurrent: true };
  }

  async #profile(id) {
    this.#requireAvailable();
    await this.ensureStore();
    const profile = await this.#service.getProfile(Number(id));
    if (!profile) {
      fail("not-found");
    }
    return profile;
  }

  async #nameTaken(name, exceptId = null) {
    const lower = name.toLocaleLowerCase();
    return (await this.#service.getAllProfiles()).some(p => p.id !== exceptId && p.name.toLocaleLowerCase() === lower);
  }

  // -- changing -----------------------------------------------------------

  /**
   * Create a profile (not launched). `name` is the template's name in the
   * user's language, as shown in the UI.
   */
  async create({ name, avatar, color, templateId = null } = {}) {
    this.#requireAvailable();
    const template = templateId === null ? null : TEMPLATES.find(t => t.id === templateId);
    if (templateId !== null && !template) {
      fail("unknown-template");
    }
    name = normalizeProfileName(name);
    avatar = checkAvatar(avatar ?? template?.avatar ?? AVATARS[0]);
    color = checkColor(color ?? template?.color ?? COLORS[0]);
    const service = this.#service;
    const newGroup = !service.currentProfile;
    await this.ensureStore();
    if (newGroup && !Services.prefs.prefHasUserValue(PREF_COLORS) && this.#colorMigration().version === 0) {
      // This group has never used the legacy palette; do not describe a migration that did not happen.
      Services.prefs.setStringPref(PREF_COLOR_MIGRATION, JSON.stringify({ version: 2, mint: [] }));
      await service.trackPref(PREF_COLOR_MIGRATION);
    }
    await this.#migrateColors(await service.getAllProfiles());
    if (await this.#nameTaken(name)) {
      fail("name-taken");
    }
    const profile = await service.createNewProfile(false, null, "nulavio-shell");
    if (template?.id === "sensitive") {
      // Before its first start, so the settings apply from the first page.
      await IOUtils.writeUTF8(PathUtils.join(profile.path, "user.js"), userJs(SENSITIVE_PREFS, "Nulavio: sensitive sites profile"));
    }
    await profile.setNameAsync(name);
    await profile.setAvatar(avatar);
    await this.#setColor(profile.id, color);
    return profile.id;
  }

  async update(id, { name, avatar, color } = {}) {
    const profile = await this.#profile(id);
    if (name !== undefined) {
      name = normalizeProfileName(name);
      if (await this.#nameTaken(name, profile.id)) {
        fail("name-taken");
      }
      await profile.setNameAsync(name);
    }
    if (avatar !== undefined) {
      await profile.setAvatar(checkAvatar(avatar));
    }
    if (color !== undefined) {
      await this.#setColor(profile.id, color);
    }
  }

  /**
   * Open (or bring to front) a profile's window. The engine first asks a
   * running instance through its local remote service, so a profile never
   * runs twice; otherwise it starts the binary with an argument list.
   */
  async switchTo(id) {
    const profile = await this.#profile(id);
    if (profile.id === this.#service.currentProfile?.id) {
      return { action: "current" };
    }
    if ((await lazy.profileLockState(profile.path)) === "locked") {
      fail("locked"); // its files are encrypted until the user unlocks it
    }
    this.#service.launchInstance(profile, []);
    return { action: "launched" };
  }

  /**
   * Delete another profile and its files. The engine refuses while that
   * profile is running (its lock), and the current profile is deleted
   * through the engine's own page, which closes this instance safely.
   */
  async remove(id) {
    const profile = await this.#profile(id);
    if (profile.id === this.#service.currentProfile?.id) {
      fail("is-current");
    }
    await this.#keepOneUnprotected(profile);
    const lock = await lazy.profileLockState(profile.path);
    if (lock === "unlocked") {
      fail("unlocked"); // lock it first: its files are open
    }
    if (lock === "locked") {
      // Drop its keys first: without them the encrypted files can never be read again.
      await lazy.vaultHelper({ op: "forget", path: profile.path });
    }
    try {
      await this.#service.deleteProfile(profile);
    } catch (e) {
      fail("in-use", String(e?.message ?? e));
    }
    await this.#setColor(profile.id, null);
  }

  // -- engine pages ---------------------------------------------------------

  #window() {
    const win = Services.wm.getMostRecentBrowserWindow();
    if (!win) {
      fail("no-window");
    }
    return win;
  }

  async openManager() {
    this.#requireAvailable();
    await this.ensureStore();
    this.#window().toOpenWindowByType("about:profilemanager", "about:profilemanager", "chrome,resizable,toolbar,centerscreen");
  }

  async openCurrentPage(page) {
    this.#requireAvailable();
    if (page !== "edit" && page !== "delete") {
      fail("unknown-page");
    }
    await this.ensureStore();
    if (page === "delete") {
      await this.#keepOneUnprotected(this.#service.currentProfile);
    }
    this.#window().openTrustedLinkIn(page === "edit" ? "about:editprofile" : "about:deleteprofile", "tab");
  }

  // -- icons ----------------------------------------------------------------

  /**
   * The engine's icon as SVG text for an extension page (which cannot load
   * chrome:// images). Its round background is dropped (the page draws the
   * profile's colour from the design tokens) and the drawing takes `ink`.
   */
  async avatarSvg(avatar, ink) {
    checkAvatar(avatar);
    if (!/^#[0-9a-fA-F]{6}$/.test(ink)) {
      fail("invalid-color");
    }
    let svg = this.#avatarCache.get(avatar);
    if (!svg) {
      svg = await new Promise((resolve, reject) => {
        lazy.NetUtil.asyncFetch(
          { uri: `chrome://browser/content/profiles/assets/16_${avatar}.svg`, loadUsingSystemPrincipal: true },
          (stream, status) => {
            if (!Components.isSuccessCode(status)) {
              reject(new ProfilesError("not-found"));
              return;
            }
            resolve(lazy.NetUtil.readInputStreamToString(stream, stream.available(), { charset: "UTF-8" }));
          }
        );
      });
      this.#avatarCache.set(avatar, svg);
    }
    return svg.replaceAll('fill="context-fill"', 'fill="none"').replaceAll("context-stroke", ink);
  }

  // -- change notifications ---------------------------------------------------

  #observe() {
    if (this.#observing) {
      return;
    }
    this.#observing = true;
    Services.obs.addObserver(this, "sps-profiles-updated");
    Services.prefs.addObserver(PREF_COLORS, this);
    Services.prefs.addObserver(PREF_COLOR_MIGRATION, this);
  }

  observe() {
    this.#band = null;
    for (const listener of this.#listeners) {
      try {
        listener();
      } catch (e) {
        console.error(e);
      }
    }
  }

  subscribe(listener) {
    this.#observe();
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]);
}

export const NulavioProfiles = new NulavioProfilesClass();
