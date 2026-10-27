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
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
  vaultHelper: "resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs",
  SelectableProfileService: "resource:///modules/profiles/SelectableProfileService.sys.mjs",
});

/** Identity colour per profile id, shared by every profile of the group (JSON). */
export const PREF_COLORS = "nulavio.profiles.colors";

/** Colour keys; the values are design tokens (--nv-color-identity-<key>). */
export const COLORS = Object.freeze(["mint", "sky", "violet", "rose", "sand", "slate"]);

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
  Object.freeze({ id: "personal", avatar: "heart", color: "mint" }),
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

  // -- colours (shared across the group) ---------------------------------

  colors() {
    try {
      const map = JSON.parse(Services.prefs.getStringPref(PREF_COLORS, "{}"));
      return map && typeof map === "object" && !Array.isArray(map) ? map : {};
    } catch {
      return {};
    }
  }

  async #setColor(id, color) {
    const map = this.colors();
    if (color === null) {
      delete map[id];
    } else {
      map[id] = checkColor(color);
    }
    Services.prefs.setStringPref(PREF_COLORS, JSON.stringify(map));
    // The engine copies tracked prefs to the group store, so every profile sees them.
    await this.#service.trackPref(PREF_COLORS);
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

  async #describe(profile, map, currentId) {
    const lock = await lazy.profileLockState(profile.path).catch(() => "plain");
    return {
      kind: lock === "locked" ? null : await this.#kind(profile.path),
      id: profile.id,
      name: profile.name,
      avatar: profile.avatar,
      color: this.#colorFor(profile, map),
      isCurrent: profile.id === currentId,
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
    if (!service.initialized) {
      // Idempotent; the Shell can start before the engine has opened the group store.
      await service.init().catch(e => console.error("Nulavio Profiles: profile service", e));
    }
    const current = service.currentProfile;
    if (!current) {
      const name = service.groupToolkitProfile?.name ?? "";
      return { ...availability, profiles: [{ id: null, name, avatar: "default-favicon", color: COLORS[0], isCurrent: true }] };
    }
    const map = this.colors();
    const profiles = await Promise.all((await service.getAllProfiles()).map(p => this.#describe(p, map, current.id)));
    profiles.sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent));
    return { ...availability, profiles };
  }

  async current() {
    const { profiles } = await this.list();
    return profiles.find(p => p.isCurrent) ?? null;
  }

  async #profile(id) {
    this.#requireAvailable();
    await this.#service.maybeSetupDataStore();
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
    await service.maybeSetupDataStore();
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
    await this.#service.maybeSetupDataStore();
    this.#window().toOpenWindowByType("about:profilemanager", "about:profilemanager", "chrome,resizable,toolbar,centerscreen");
  }

  async openCurrentPage(page) {
    this.#requireAvailable();
    if (page !== "edit" && page !== "delete") {
      fail("unknown-page");
    }
    await this.#service.maybeSetupDataStore();
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
  }

  observe() {
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
