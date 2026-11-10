/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Protected profiles in the browser (ADR 0006, S6).

   The browser never holds profile keys. Every Vault operation runs in the
   Nulavio tools shipped next to the engine (nulavio-tools/bin/nulavio vault
   api): an argument list without secrets, one JSON request on stdin (where a
   password or recovery code travels), one JSON answer on stdout. JavaScript
   strings cannot be wiped, so a typed secret lives in this process only as
   long as the page and this call keep it.

   Unlocking mounts the profile's encrypted volume and starts a watcher that
   locks it again when that profile's window closes. A profile that is open
   cannot be locked from another one: its own windows must close first. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  NulavioRouting: "resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs",
  SelectableProfileService: "resource:///modules/profiles/SelectableProfileService.sys.mjs",
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
});

const SHELL_ID = "shell@nulavio.net";
const TIMEOUT_MS = 90000; // Argon2id (256 MiB) plus mounting; encryption of a new profile copies files
const METHODS = new Set(["password", "recovery-code", "os-keyring"]);
// Connecting a phone is not offered yet (D10): off unless this pref says otherwise. Unlocking with a
// phone that is already connected, and removing it, never depend on it.
const PREF_PHONE_PAIRING = "nulavio.vault.phone.pairing";
const phonePairing = () => Services.prefs.getBoolPref(PREF_PHONE_PAIRING, false);
const CHANGES = new Set(["new-recovery-code", "add-password", "add-keyring", "remove-method"]);
const MAX_SECRET = 1024;

export class VaultError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "VaultError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new VaultError(code, message);
}

function checkSecret(value) {
  if (typeof value !== "string" || !value.length || value.length > MAX_SECRET) {
    fail("bad-secret");
  }
  return value;
}

/** One request to the Vault helper; resolves to its JSON answer or throws its error code. */
export async function helper(request) {
  try {
    return await lazy.callTool(["vault", "api"], request, TIMEOUT_MS);
  } catch (e) {
    fail(e.code ?? "helper-failed");
  }
}

class Vault {
  #capabilities = null;

  async capabilities() {
    if (this.#capabilities) {
      return { ...this.#capabilities, phonePairing: phonePairing() };
    }
    try {
      const found = await helper({ op: "capabilities" });
      if (found.storage && found.sodium) {
        this.#capabilities = found; // only a working setup is remembered; a missing one is checked again
      }
      return { ...found, phonePairing: phonePairing() };
    } catch (e) {
      return { storage: false, sodium: false, keyring: false, phonePairing: false, reason: e.code ?? "unexpected" };
    }
  }

  async #path(profileId) {
    const service = lazy.SelectableProfileService;
    await service.init();
    const profile = await service.getProfile(Number(profileId));
    if (!profile) {
      fail("not-found");
    }
    return { profile, path: profile.path, isCurrent: profile.id === service.currentProfile?.id };
  }

  /** What the unlock page needs: name, colour, methods (ids and kinds only), lock state. */
  async status(profileId) {
    const { profile, path, isCurrent } = await this.#path(profileId);
    const listed = (await lazy.NulavioProfiles.list()).profiles.find(p => p.id === profile.id);
    const state = await helper({ op: "status", path });
    return {
      id: profile.id,
      name: profile.name,
      avatar: profile.avatar,
      color: listed?.color ?? null,
      isCurrent,
      encrypted: state.encrypted,
      locked: state.encrypted ? state.locked : false,
      running: Boolean(state.running),
      openWithoutEngine: Boolean(state.open_without_engine),
      methods: (state.methods ?? []).map(m => ({ id: m.id, method: m.method, label: m.label })),
      protection: state.protection ?? [],
    };
  }

  /** Unlock with one method, then open the profile (with a held-back address, if any). */
  async unlock(profileId, method, secret = null, url = null) {
    if (!METHODS.has(method)) {
      fail("no-such-method");
    }
    const { path } = await this.#path(profileId);
    const request = { op: "unlock", path, method };
    if (method !== "os-keyring") {
      request.secret = checkSecret(secret);
    }
    await helper(request);
    if (url) {
      return { opened: (await lazy.NulavioRouting.openIn(Number(profileId), url)).action };
    }
    return { opened: (await lazy.NulavioProfiles.switchTo(Number(profileId))).action };
  }

  async lock(profileId) {
    const { path, isCurrent } = await this.#path(profileId);
    if (isCurrent) {
      fail("is-current"); // a profile cannot lock itself while it is open
    }
    return helper({ op: "lock", path });
  }

  /**
   * "Bloquear agora" for this browser's own profile (UX4): a profile cannot lock itself while it
   * is open, so the tools first start a watcher that locks it once this instance has exited, and
   * then the browser quits the way the person would. The engine still asks about unsaved work
   * and many open tabs; if the person keeps the windows, nothing closes and the watcher locks
   * the profile at the next exit instead.
   */
  async lockCurrent() {
    const path = Services.dirsvc.get("ProfD", Ci.nsIFile).path;
    if ((await lazy.profileLockState(path)) !== "unlocked") {
      fail("not-encrypted");
    }
    await helper({ op: "lock-on-exit", path });
    const cancel = Cc["@mozilla.org/supports-PRBool;1"].createInstance(Ci.nsISupportsPRBool);
    Services.obs.notifyObservers(cancel, "quit-application-requested");
    if (cancel.data) {
      return { quit: false };
    }
    Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit);
    return { quit: true };
  }

  /** Create a profile that is encrypted from the start; returns its id and the recovery code (shown once). */
  async createProtected({ name, templateId = null, avatar, color, password = null, keyring = false } = {}) {
    if (!password && !keyring) {
      fail("no-method");
    }
    if (password !== null) {
      checkSecret(password);
    }
    const id = await lazy.NulavioProfiles.create({ name, templateId, avatar, color });
    const { path } = await this.#path(id);
    try {
      const { recovery_code: recoveryCode } = await helper({ op: "encrypt", path, password, keyring: Boolean(keyring) });
      return { id, recoveryCode };
    } catch (e) {
      // Never leave a profile the user believes is protected but is not.
      await lazy.NulavioProfiles.remove(id).catch(console.error);
      throw e;
    }
  }

  /** Add or remove a method, or replace the recovery code: an existing secret is asked again first. */
  async change(profileId, op, { current, password = null, envelope = null } = {}) {
    if (!CHANGES.has(op)) {
      fail("bad-request");
    }
    const { path } = await this.#path(profileId);
    const request = { op, path, current: checkSecret(current) };
    if (op === "add-password") {
      request.password = checkSecret(password);
    }
    if (op === "remove-method") {
      request.envelope = String(envelope ?? "");
    }
    const answer = await helper(request);
    return { done: true, recoveryCode: answer.recovery_code ?? null };
  }

  // -- phone (Nulavio Companion, ADR 0005, S11) ---------------------------------------------

  /**
   * Start pairing a phone ("pair", needs a current secret) or an unlock with the paired phone
   * ("unlock"). The Nulavio tools run the operation; the page gets the session id and the code to
   * show, as rows of QR modules drawn by the engine's own encoder.
   */
  async phoneStart(profileId, kind, { current = null } = {}) {
    if (kind === "pair" && !phonePairing()) {
      fail("phone-not-yet"); // the page does not offer it; a call from elsewhere is refused the same way
    }
    const { path } = await this.#path(profileId);
    const request = kind === "pair" ? { op: "phone-pair-start", path, current: checkSecret(current) } : { op: "phone-unlock-start", path };
    const answer = await helper(request);
    if (answer.error || typeof answer.qr !== "string") {
      fail(answer.error ?? "failed");
    }
    const { QR } = ChromeUtils.importESModule("moz-src:///toolkit/components/qrcode/encoder.mjs");
    const { matrix } = QR.encodeToMatrix(answer.qr, "L");
    const rows = matrix.map(row => row.map(dark => (dark ? "1" : "0")).join(""));
    return { session: answer.session, expiry: answer.expiry, qr: rows, code: answer.qr };
  }

  /** A running session: "status", "confirm" (the user's answer about the 6 digits) or "cancel". */
  async phoneSession(session, action, match = false) {
    return helper({ op: "phone-session", session: String(session), action, match: Boolean(match) });
  }

  /** After an unlock with the phone: open the profile, with the held-back address if any. */
  async phoneOpen(profileId, url = null) {
    if (url) {
      return { opened: (await lazy.NulavioRouting.openIn(Number(profileId), url)).action };
    }
    return { opened: (await lazy.NulavioProfiles.switchTo(Number(profileId))).action };
  }

  /** The page for connecting and removing phones. */
  async openPhonePage(profileId) {
    const win = Services.wm.getMostRecentBrowserWindow();
    const policy = WebExtensionPolicy.getByID(SHELL_ID);
    if (!win || !policy) {
      fail("no-window");
    }
    win.openTrustedLinkIn(`${policy.getURL("vault/phone.html")}?p=${Number(profileId)}`, "tab");
  }

  /** The page shown instead of a locked profile: never the site, never the profile itself. */
  async openUnlockPage(profileId, url = null, source = null) {
    const win = Services.wm.getMostRecentBrowserWindow();
    const policy = WebExtensionPolicy.getByID(SHELL_ID);
    if (!win || !policy) {
      fail("no-window");
    }
    const params = new URLSearchParams({ p: String(profileId) });
    if (url) {
      params.set("u", url);
    }
    if (source) {
      params.set("src", source);
    }
    win.openTrustedLinkIn(`${policy.getURL("vault/unlock.html")}?${params}`, "tab");
  }
}

export const NulavioVault = new Vault();

/** The helper call, for other Shell modules (profile deletion). */
export const vaultHelper = helper;
