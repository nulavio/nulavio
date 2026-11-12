/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio Guard at run time (docs/security/hardening.md, threat model S11).

   When the browser starts, compare this profile with what Nulavio recorded
   the last time: extensions, settings that protect you, certificate
   authorities you trust, security modules, programs registered to talk to
   extensions (native messaging), managed policies, user.js, and the default
   search engine. Anything that changed outside the browser is listed for
   review; nothing is reverted without the user's click.

   Detection, not prevention: a program running as you can also edit the
   record (kept in the profile, so it is encrypted with a protected profile
   and never readable while it is locked). It catches persistence left by
   tools and generic malware that do not know Nulavio. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  SessionStore: "moz-src:///browser/components/sessionstore/SessionStore.sys.mjs",
  AddonManager: "resource://gre/modules/AddonManager.sys.mjs",
  AddonManagerPrivate: "resource://gre/modules/AddonManager.sys.mjs",
  AsyncShutdown: "resource://gre/modules/AsyncShutdown.sys.mjs",
  NulavioAI: "resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs",
});

/* Lines the AI Bridge adds to user.js while an agent drives this profile, and removes afterwards. */
const AI_TEMPORARY = "nulavio-ai-temporary";

export const RECORD = "nulavio-guard.json";
const SCHEMA = 1;

/* Settings watched for changes made outside the browser. Exact names, or a
   prefix ending in "." for a whole branch. Kept short on purpose: each one
   protects the user or redirects their traffic or searches. */
export const WATCHED_PREFS = Object.freeze([
  "network.proxy.",
  "network.trr.mode",
  "network.trr.uri",
  "network.trr.custom_uri",
  "security.enterprise_roots.enabled",
  "security.tls.version.min",
  "security.ssl.require_safe_negotiation",
  "security.cert_pinning.enforcement_level",
  "security.OCSP.enabled",
  "security.mixed_content.block_active_content",
  "security.sandbox.content.level",
  "security.sandbox.rdd.level",
  "security.sandbox.socket.process.level",
  "fission.autostart",
  "xpinstall.signatures.required",
  "extensions.autoDisableScopes",
  "extensions.enabledScopes",
  "extensions.webextensions.remote",
  "extensions.update.enabled",
  "devtools.debugger.remote-enabled",
  "devtools.chrome.enabled",
  "browser.safebrowsing.",
  "dom.security.https_only_mode",
  "browser.contentblocking.category",
  "privacy.trackingprotection.enabled",
  "privacy.fingerprintingProtection",
  "privacy.fingerprintingProtection.",
  "privacy.baselineFingerprintingProtection",
  "network.cookie.cookieBehavior",
  "browser.startup.homepage",
  "browser.newtabpage.enabled",
  "general.config.filename",
  "general.config.obscure_value",
  "signon.rememberSignons",
  "media.peerconnection.enabled",
]);

/* Kinds of findings and whether the browser can undo them. */
export const UNDOABLE = Object.freeze(new Set(["extension-added", "extension-changed", "pref-changed", "root-added", "module-added", "search-changed"]));

export class GuardError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "GuardError";
    this.code = code;
  }
}

function hex(bytes) {
  return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
}

function sha256(bytes) {
  const hash = Cc["@mozilla.org/security/hash;1"].createInstance(Ci.nsICryptoHash);
  hash.init(Ci.nsICryptoHash.SHA256);
  hash.update(bytes, bytes.length);
  return hex(Uint8Array.from(hash.finish(false), c => c.charCodeAt(0)));
}

async function fileDigest(path, maxBytes = 64 * 1024 * 1024) {
  try {
    const info = await IOUtils.stat(path);
    if (info.type !== "regular" || info.size > maxBytes) {
      return info.type === "regular" ? `size:${info.size}:mtime:${info.lastModified}` : null;
    }
    // Same lowercase hex as sha256(bytes), streamed off the main thread instead of
    // reading up to 64 MB into JS at startup.
    return await IOUtils.computeHexDigest(path, "sha256");
  } catch {
    return null;
  }
}

function prefValue(name) {
  switch (Services.prefs.getPrefType(name)) {
    case Ci.nsIPrefBranch.PREF_BOOL:
      return Services.prefs.getBoolPref(name);
    case Ci.nsIPrefBranch.PREF_INT:
      return Services.prefs.getIntPref(name);
    case Ci.nsIPrefBranch.PREF_STRING:
      return Services.prefs.getStringPref(name);
    default:
      return null;
  }
}

/* Bookkeeping the engine itself writes under a watched branch (update times of the Safe Browsing lists). */
const ENGINE_BOOKKEEPING = /\.(lastupdatetime|nextupdatetime)$/;

function watchedNames() {
  const names = new Set();
  for (const entry of WATCHED_PREFS) {
    for (const name of entry.endsWith(".") ? Services.prefs.getChildList(entry) : [entry]) {
      if (!ENGINE_BOOKKEEPING.test(name)) {
        names.add(name);
      }
    }
  }
  return [...names].sort();
}

// From the second start on, the engine fills some policies with empty defaults (SitePolicies: []):
// only policies that set something count.
function settingPolicies(policies) {
  const empty = v => v === null || v === undefined || (typeof v === "object" && !Object.keys(v).length);
  return Object.fromEntries(Object.entries(policies ?? {}).filter(([, v]) => !empty(v)));
}

/** Whether two sets of policies set the same things. A set that is not an object equals nothing. */
export function samePolicies(active, shipped) {
  const usable = v => !!v && typeof v === "object" && !Array.isArray(v);
  return usable(active) && usable(shipped) && sortedJSON(settingPolicies(active)) === sortedJSON(settingPolicies(shipped));
}

function sortedJSON(value) {
  if (Array.isArray(value)) {
    return `[${value.map(sortedJSON).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map(k => `${JSON.stringify(k)}:${sortedJSON(value[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}


class Guard {
  #state = null; // { snapshot, pending }
  #listening = false;
  #observer = null;
  #barObserver = null;
  #bar = null; // { textFor(count), button }
  #own = []; // prefs (names or "branch." prefixes) Nulavio itself changed at this start
  #timer = null;
  #checked = null;

  get #profileDir() {
    return Services.dirsvc.get("ProfD", Ci.nsIFile).path;
  }

  get #recordPath() {
    return PathUtils.join(this.#profileDir, RECORD);
  }

  // -- collecting ----------------------------------------------------------

  async #extensions() {
    // The engine registers extensions placed in the profile folder only when it scans for them
    // (after start-up, for its "added by another program" prompt); scan now, with its own function.
    await lazy.AddonManagerPrivate.getNewSideloads().catch(() => []);
    const out = {};
    for (const addon of await lazy.AddonManager.getAddonsByTypes(["extension"])) {
      if (addon.isBuiltin || addon.isSystem || addon.hidden) {
        continue; // the engine's own and Nulavio's built-in Shell
      }
      out[addon.id] = {
        name: String(addon.name ?? addon.id),
        version: String(addon.version ?? ""),
        active: Boolean(addon.isActive),
        foreign: Boolean(addon.foreignInstall),
        // Installed by a managed policy (Nulavio's own policies.json installs uBlock Origin): a change
        // of policies is reported as such, so the extension it brings is not reported again.
        policy: addon.installTelemetryInfo?.source === "enterprise-policy",
      };
    }
    return out;
  }

  #prefs() {
    const out = {};
    for (const name of watchedNames()) {
      if (Services.prefs.prefHasUserValue(name) || Services.prefs.prefIsLocked(name)) {
        out[name] = prefValue(name);
      }
    }
    return out;
  }

  async #roots() {
    const certdb = Cc["@mozilla.org/security/x509certdb;1"].getService(Ci.nsIX509CertDB);
    // Only this profile's own certificate store (cert9.db), the NSS internal module's tokens (their
    // names are localized). The built-in roots and the tokens of other modules are not in it; a new
    // module is reported as such.
    const db = Cc["@mozilla.org/security/pkcs11moduledb;1"].getService(Ci.nsIPKCS11ModuleDB);
    const internal = new Set();
    for (const module of await db.listModules()) {
      const tokens = module.slots.map(slot => slot.tokenName);
      if (!module.libName && !tokens.includes("Builtin Object Token")) {
        tokens.forEach(token => internal.add(token));
      }
    }
    const out = {};
    for (const cert of await certdb.getCerts()) {
      if (!internal.has(cert.tokenName)) {
        continue;
      }
      if (cert.certType !== Ci.nsIX509Cert.CA_CERT || !certdb.isCertTrusted(cert, Ci.nsIX509Cert.CA_CERT, Ci.nsIX509CertDB.TRUSTED_SSL)) {
        continue; // only authorities trusted to vouch for websites
      }
      out[cert.sha256Fingerprint] = { subject: cert.subjectName };
    }
    return out;
  }

  async #modules() {
    const db = Cc["@mozilla.org/security/pkcs11moduledb;1"].getService(Ci.nsIPKCS11ModuleDB);
    const gre = Services.dirsvc.get("GreD", Ci.nsIFile).path;
    const out = {};
    for (const module of await db.listModules()) {
      if (!module.libName || module.libName.startsWith(gre + "/")) {
        continue; // NSS's internal module and modules shipped with the engine
      }
      out[module.name] = { library: module.libName };
    }
    return out;
  }

  #policies() {
    if (Services.policies.status !== Ci.nsIEnterprisePolicies.ACTIVE) {
      return null;
    }
    const active = settingPolicies(Services.policies.getActivePolicies());
    return { names: Object.keys(active).sort(), digest: sha256(new TextEncoder().encode(sortedJSON(active))) };
  }

  /**
   * Whose the managed policies in effect are: "none" (no policy is active), "own" (exactly the ones this
   * build ships in distribution/policies.json) or "other" (anything else: one added, removed or changed by
   * a system file or an administrator, or a shipped file that could not be read). `count` is how many are
   * in effect. Never "own" on a doubt: the settings page drops the engine's "managed" line only for "own".
   */
  async policiesOrigin() {
    if (Services.policies.status !== Ci.nsIEnterprisePolicies.ACTIVE) {
      return { origin: "none", count: 0 };
    }
    const active = settingPolicies(Services.policies.getActivePolicies());
    let shipped = null;
    try {
      const file = Services.dirsvc.get("XREAppDist", Ci.nsIFile);
      file.append("policies.json");
      shipped = JSON.parse(await IOUtils.readUTF8(file.path)).policies;
    } catch (e) {
      console.error("Nulavio Guard: the build's policies.json could not be read", e);
    }
    return { origin: samePolicies(active, shipped) ? "own" : "other", count: Object.keys(active).length };
  }

  async #hosts() {
    const out = {};
    const dirs = ["XREUserNativeManifests", "XRESysNativeManifests"].map(key => {
      try {
        return Services.dirsvc.get(key, Ci.nsIFile).path;
      } catch {
        return null;
      }
    });
    for (const base of dirs.filter(Boolean)) {
      for (const type of ["native-messaging-hosts", "pkcs11-modules", "managed-storage"]) {
        const dir = PathUtils.join(base, type);
        let children = [];
        try {
          children = await IOUtils.getChildren(dir);
        } catch {
          continue;
        }
        for (const file of children.filter(p => p.endsWith(".json")).sort()) {
          let manifest = null;
          let raw;
          try {
            raw = await IOUtils.read(file, { maxBytes: 256 * 1024 });
            manifest = JSON.parse(new TextDecoder().decode(raw));
          } catch {
            out[file] = { type, name: PathUtils.filename(file), digest: raw ? sha256(raw) : null, program: null, programDigest: null };
            continue;
          }
          const program = typeof manifest?.path === "string" ? manifest.path : null;
          out[file] = {
            type,
            name: String(manifest?.name ?? PathUtils.filename(file)),
            digest: sha256(raw),
            program,
            programDigest: program && program.startsWith("/") ? await fileDigest(program) : null,
          };
        }
      }
    }
    return out;
  }

  /* user.js by content: blank lines and the AI Bridge's own temporary lines do not count. */
  async #userJs() {
    let text;
    try {
      text = await IOUtils.readUTF8(PathUtils.join(this.#profileDir, "user.js"));
    } catch {
      return null;
    }
    const lines = text
      .split("\n")
      .map(line => line.trim())
      .filter(line => line && !line.includes(AI_TEMPORARY));
    return lines.length ? sha256(new TextEncoder().encode(lines.join("\n"))) : null;
  }

  async #search() {
    try {
      await Services.search.init();
      return {
        default: (await Services.search.getDefault())?.name ?? null,
        private: (await Services.search.getDefaultPrivate())?.name ?? null,
      };
    } catch {
      return null;
    }
  }

  async snapshot() {
    return {
      build: Services.appinfo.appBuildID,
      extensions: await this.#extensions(),
      prefs: this.#prefs(),
      roots: await this.#roots(),
      modules: await this.#modules(),
      hosts: await this.#hosts(),
      policies: this.#policies(),
      userJs: await this.#userJs(),
      search: await this.#search(),
    };
  }

  // -- comparing -------------------------------------------------------------

  static compare(before, after) {
    const findings = [];
    const add = (kind, key, details) => findings.push({ id: `${kind}:${key}`, kind, key, ...details });
    for (const [id, now] of Object.entries(after.extensions ?? {})) {
      const then = before.extensions?.[id];
      if (!then) {
        if (!now.policy) {
          add("extension-added", id, { after: now });
        }
      } else if (then.version !== now.version || (!then.active && now.active)) {
        // A new version, or a disabled extension turned on, while the browser was not running.
        add("extension-changed", id, { before: then, after: now });
      }
    }
    for (const [id, then] of Object.entries(before.extensions ?? {})) {
      if (!after.extensions?.[id]) {
        add("extension-removed", id, { before: then });
      }
    }
    const names = new Set([...Object.keys(before.prefs ?? {}), ...Object.keys(after.prefs ?? {})]);
    for (const name of [...names].sort()) {
      const then = before.prefs?.[name] ?? null;
      const now = after.prefs?.[name] ?? null;
      if (then !== now) {
        add("pref-changed", name, { before: then, after: now });
      }
    }
    for (const [fingerprint, now] of Object.entries(after.roots ?? {})) {
      if (!before.roots?.[fingerprint]) {
        add("root-added", fingerprint, { after: now });
      }
    }
    for (const [name, now] of Object.entries(after.modules ?? {})) {
      const then = before.modules?.[name];
      if (!then || then.library !== now.library) {
        add("module-added", name, { before: then ?? null, after: now });
      }
    }
    for (const [file, now] of Object.entries(after.hosts ?? {})) {
      const then = before.hosts?.[file];
      if (!then) {
        add("host-added", file, { after: now });
      } else if (then.digest !== now.digest || then.program !== now.program || then.programDigest !== now.programDigest) {
        add("host-changed", file, { before: then, after: now });
      }
    }
    // An update of Nulavio itself may bring new managed settings (its own policies.json).
    const updated = Boolean(before.build && after.build && before.build !== after.build);
    if (!updated && (before.policies?.digest ?? null) !== (after.policies?.digest ?? null)) {
      add("policies-changed", "policies", { before: before.policies ?? null, after: after.policies ?? null });
    }
    if (before.userJs !== after.userJs && after.userJs !== null) {
      add(before.userJs === null ? "userjs-added" : "userjs-changed", "user.js", {});
    }
    const searchThen = before.search ?? {};
    const searchNow = after.search ?? {};
    if (after.search && (searchThen.default !== searchNow.default || searchThen.private !== searchNow.private)) {
      add("search-changed", "search", { before: before.search ?? null, after: after.search });
    }
    return findings;
  }

  // -- the record ----------------------------------------------------------------

  async #load() {
    try {
      const data = await IOUtils.readJSON(this.#recordPath);
      if (data?.schema === SCHEMA && data.snapshot && typeof data.snapshot === "object") {
        return { snapshot: data.snapshot, pending: Array.isArray(data.pending) ? data.pending : [] };
      }
    } catch {}
    return null;
  }

  async #save() {
    const { snapshot, pending } = this.#state;
    await IOUtils.writeJSON(
      this.#recordPath,
      { schema: SCHEMA, updated: new Date().toISOString(), snapshot, pending },
      { tmpPath: `${this.#recordPath}.tmp` }
    );
    await IOUtils.setPermissions(this.#recordPath, 0o600).catch(() => {});
    Services.obs.notifyObservers(null, "nulavio-guard-changed");
  }

  /** Why the Guard does not watch this instance: a temporary profile, or one an agent drives right now. */
  async #skipReason() {
    if (Services.prefs.getBoolPref("nulavio.profile.temporary", false)) {
      return "temporary";
    }
    if (await lazy.NulavioAI.workspaceAgent().catch(() => null)) {
      return "ai-workspace";
    }
    return null;
  }

  /**
   * Compare with the last record, once per session. New differences are added
   * to the findings waiting for review; the record then holds the current state.
   */
  check() {
    this.#checked ??= this.#check().catch(e => {
      console.error("Nulavio Guard: check failed", e);
      this.#checked = null;
      throw e;
    });
    return this.#checked;
  }

  async #check() {
    const skipped = await this.#skipReason();
    if (skipped) {
      return { state: "skipped", reason: skipped, findings: [] };
    }
    this.#listen(); // changes made while the snapshot is taken are recorded right after it
    const now = await this.snapshot();
    const saved = await this.#load();
    if (!saved) {
      this.#state = { snapshot: now, pending: [] };
      await this.#save();
      return { state: "first", findings: [] };
    }
    const own = name => this.#own.some(entry => (entry.endsWith(".") ? name.startsWith(entry) : name === entry));
    const fresh = Guard.compare(saved.snapshot, now).filter(f => f.kind !== "pref-changed" || !own(f.key));
    const seen = new Set(fresh.map(f => f.id));
    const at = new Date().toISOString();
    const pending = [...saved.pending.filter(f => !seen.has(f.id)), ...fresh.map(f => ({ ...f, at }))];
    this.#state = { snapshot: now, pending };
    await this.#save();
    return { state: pending.length ? "changed" : "clean", findings: this.findings() };
  }

  /** Settings Nulavio itself changes at this start (its own defaults): not changes made outside the browser. */
  ownPrefChanges(entries) {
    this.#own.push(...entries);
  }

  findings() {
    return (this.#state?.pending ?? []).map(f => ({ ...f, undoable: UNDOABLE.has(f.kind) }));
  }

  // -- keeping the record current during the session --------------------------------

  /* Changes the user makes in the browser are not "made outside it": the
     record follows extensions, watched settings and the default search
     engine as they change, and is written again when the browser quits.
     Certificate authorities, security modules, native-messaging manifests,
     policies and user.js keep the state seen at start-up: a change to them
     while the browser runs (including one made in its certificate manager)
     is reported at the next start, so nothing reaches the record unseen. */
  #listen() {
    if (this.#listening) {
      return;
    }
    this.#listening = true;
    const refresh = () => this.#scheduleRefresh();
    lazy.AddonManager.addAddonListener({
      onInstalled: refresh,
      onUninstalled: refresh,
      onEnabled: refresh,
      onDisabled: refresh,
    });
    // Held for the whole session (the observers below are weak).
    this.#observer = { observe: refresh, QueryInterface: ChromeUtils.generateQI(["nsIObserver", "nsISupportsWeakReference"]) };
    for (const entry of WATCHED_PREFS) {
      Services.prefs.addObserver(entry, this.#observer, true);
    }
    Services.obs.addObserver(this.#observer, "browser-search-engine-modified", true);
    lazy.AsyncShutdown.appShutdownConfirmed.addBlocker("Nulavio Guard: record", () => this.#refresh());
  }

  #scheduleRefresh() {
    if (this.#timer) {
      return;
    }
    this.#timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#timer.initWithCallback(() => this.#refresh().catch(e => console.error("Nulavio Guard", e)), 1000, Ci.nsITimer.TYPE_ONE_SHOT);
  }

  async #refresh() {
    this.#timer?.cancel();
    this.#timer = null;
    if (!this.#state) {
      return;
    }
    const [extensions, search] = await Promise.all([this.#extensions(), this.#search()]);
    // An extension another program placed in the profile is never taken into the record unseen,
    // even when the engine registers it during the session.
    const before = { extensions: this.#state.snapshot.extensions };
    const pendingIds = new Set(this.#state.pending.map(f => f.id));
    const at = new Date().toISOString();
    let grew = false;
    for (const finding of Guard.compare(before, { extensions })) {
      if (finding.kind === "extension-added" && finding.after.foreign && !pendingIds.has(finding.id)) {
        this.#state.pending.push({ ...finding, at });
        grew = true;
      }
    }
    this.#state.snapshot = { ...this.#state.snapshot, extensions, prefs: this.#prefs(), search };
    await this.#save();
    if (grew) {
      this.showBar();
    }
  }

  // -- the user's decisions ------------------------------------------------------------

  /**
   * "keep": the change stays and leaves the list. "undo": remove what was
   * added or restore the previous value, then leave the list.
   */
  async resolve(id, action) {
    await this.check();
    const finding = this.#state?.pending.find(f => f.id === id);
    if (!finding) {
      throw new GuardError("not-found");
    }
    if (action === "undo") {
      if (!UNDOABLE.has(finding.kind)) {
        throw new GuardError("not-undoable");
      }
      await this.#undo(finding);
    } else if (action !== "keep") {
      throw new GuardError("bad-action");
    }
    this.#state.pending = this.#state.pending.filter(f => f.id !== id);
    if (action === "undo") {
      const snapshot = this.#state.snapshot;
      if (finding.kind === "root-added" || finding.kind === "module-added") {
        const part = finding.kind === "root-added" ? "roots" : "modules";
        snapshot[part] = Object.fromEntries(Object.entries(snapshot[part] ?? {}).filter(([key]) => key !== finding.key));
      } else {
        await this.#refresh();
        return this.findings();
      }
    }
    await this.#save();
    return this.findings();
  }

  async #undo(finding) {
    switch (finding.kind) {
      case "extension-added":
      case "extension-changed": {
        const addon = await lazy.AddonManager.getAddonByID(finding.key);
        await addon?.uninstall();
        return;
      }
      case "pref-changed": {
        const name = finding.key;
        if (!watchedNames().includes(name) && !WATCHED_PREFS.some(e => e.endsWith(".") && name.startsWith(e))) {
          throw new GuardError("not-watched");
        }
        if (Services.prefs.prefIsLocked(name)) {
          throw new GuardError("pref-locked"); // set by policy or autoconfig: not changeable here
        }
        const before = finding.before;
        if (before === null) {
          Services.prefs.clearUserPref(name);
        } else if (typeof before === "boolean") {
          Services.prefs.setBoolPref(name, before);
        } else if (typeof before === "number") {
          Services.prefs.setIntPref(name, before);
        } else {
          Services.prefs.setStringPref(name, String(before));
        }
        return;
      }
      case "root-added": {
        const certdb = Cc["@mozilla.org/security/x509certdb;1"].getService(Ci.nsIX509CertDB);
        const cert = (await certdb.getCerts()).find(c => c.sha256Fingerprint === finding.key);
        if (cert) {
          certdb.deleteCertificate(cert);
        }
        return;
      }
      case "module-added": {
        const db = Cc["@mozilla.org/security/pkcs11moduledb;1"].getService(Ci.nsIPKCS11ModuleDB);
        await db.deleteModule(finding.key);
        return;
      }
      case "search-changed": {
        const before = finding.before ?? {};
        const engine = before.default ? Services.search.getEngineByName(before.default) : null;
        const privateEngine = before.private ? Services.search.getEngineByName(before.private) : null;
        if (!engine && !privateEngine) {
          throw new GuardError("engine-gone");
        }
        if (engine) {
          await Services.search.setDefault(engine, Ci.nsISearchService.CHANGE_REASON_USER);
        }
        if (privateEngine) {
          await Services.search.setDefaultPrivate(privateEngine, Ci.nsISearchService.CHANGE_REASON_USER);
        }
        return;
      }
      default:
        throw new GuardError("not-undoable");
    }
  }

  /** Show the file behind a finding (user.js, a native-messaging manifest) in the file manager. */
  reveal(id) {
    const finding = this.#state?.pending.find(f => f.id === id);
    let path = null;
    if (finding?.kind === "host-added" || finding?.kind === "host-changed") {
      path = finding.key;
    } else if (finding?.kind === "userjs-added" || finding?.kind === "userjs-changed") {
      path = PathUtils.join(this.#profileDir, "user.js");
    }
    if (!path) {
      throw new GuardError("not-found");
    }
    const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    file.initWithPath(path);
    file.reveal();
  }

  // -- telling the user -----------------------------------------------------------

  /**
   * When the Shell starts with the browser: check once the windows are back (so the bar has
   * somewhere to go), then show the bar if anything waits for review. Never throws.
   */
  atStartup(textFor, button) {
    this.configureBar(textFor, button);
    lazy.SessionStore.promiseAllWindowsRestored.then(() => this.check())
      .then(() => this.showBar())
      .catch(e => console.error("Nulavio Guard", e));
  }

  /** The bar's words, in the user's language (from the Shell, which owns the strings). */
  configureBar(textFor, button) {
    this.#bar = { textFor, button };
  }

  /** A bar in every window while findings wait; "Review" opens the Shell's review page. */
  showBar() {
    const pending = this.#state?.pending.length ?? 0;
    const url = WebExtensionPolicy.getByID("shell@nulavio.net")?.getURL("guard/review.html");
    if (!pending || !url || !this.#bar) {
      return;
    }
    const text = String(this.#bar.textFor(pending));
    const mark = win => {
      const box = win.gNotificationBox;
      if (!box) {
        return;
      }
      const existing = box.getNotificationWithValue("nulavio-guard");
      if (existing?.messageText?.textContent === text) {
        return;
      }
      existing?.close();
      const button = {
        label: String(this.#bar.button),
        callback: () => {
          win.openTrustedLinkIn(url, "tab");
          return false;
        },
      };
      box.appendNotification("nulavio-guard", { label: text, priority: box.PRIORITY_WARNING_MEDIUM }, [button]);
    };
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      mark(win);
    }
    if (!this.#barObserver) {
      this.#barObserver = subject => mark(subject);
      Services.obs.addObserver(this.#barObserver, "browser-delayed-startup-finished");
    }
  }

  hideBar() {
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      win.gNotificationBox?.getNotificationWithValue("nulavio-guard")?.close();
    }
    if (this.#barObserver) {
      Services.obs.removeObserver(this.#barObserver, "browser-delayed-startup-finished");
      this.#barObserver = null;
    }
  }
}

export const NulavioGuard = new Guard();
export const compareSnapshots = Guard.compare;
