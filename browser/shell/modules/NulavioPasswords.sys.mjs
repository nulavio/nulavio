/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Passwords (docs/brand/ux-flows.md, flows B, D and H).

   Flow B: choose who saves and fills passwords in this profile. The state is
   real: whether each official extension is installed and on, whether a
   desktop app registered its native-messaging host, how many logins the
   engine keeps (a count, never their contents). Choosing an extension
   installs the version Nulavio pins (addons.mozilla.org address, SHA-256
   checked by the engine, Mozilla signature required) after the user's one
   confirmation, and turns the engine's own save and fill prompts off, so
   only one manager offers to fill. Nulavio never reads a vault.

   Flow D: before a password is typed on a site that looks like one where the
   user keeps a login in the engine's manager (confusable characters, one or
   two letters apart, or the brand plus a login word), a Nulavio page asks
   first. The comparison is local. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AddonManager: "resource://gre/modules/AddonManager.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
});

const DATA_URL = "resource://builtin-addons/nulavio-shell/shared/providers.json";
const ORDER = ["builtin", "proton-pass", "keepassxc", "bitwarden"];
export const PREF_DISMISSED = "nulavio.passwords.lookalikeDismissed";
// The engine's own permission name (LoginManager.sys.mjs); test_vault_ui checks it still decides.
const PERMISSION_SAVE_LOGINS = "login-saving";
const LOGIN_WORDS = ["login", "signin", "secure", "account", "verify", "update", "support", "auth", "conta", "seguro", "acesso", "entrar", "senha"];

export class PasswordsError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "PasswordsError";
    this.code = code;
  }
}

function fail(code) {
  throw new PasswordsError(code);
}

// -- look-alike sites (flow D) ----------------------------------------------------------

/* Characters that read as others. A small, explicit table: Latin look-alikes and the Cyrillic
   and Greek letters most used in phishing names. */
const CONFUSABLE = new Map(
  Object.entries({
    0: "o", 1: "l", 3: "e", 5: "s", 7: "t", 8: "b", "|": "l", ı: "i", ł: "l",
    а: "a", е: "e", о: "o", р: "p", с: "c", у: "y", х: "x", і: "i", ј: "j", ѕ: "s", ԁ: "d", ӏ: "l", ԛ: "q", ԝ: "w",
    α: "a", ο: "o", ρ: "p", ν: "v", τ: "t", κ: "k", ι: "i",
  })
);

/** A host label reduced to how it reads: confusables mapped, "rn" as "m", "vv" as "w", no hyphens. */
export function skeleton(label) {
  const mapped = Array.from(String(label).normalize("NFKC").toLowerCase(), c => CONFUSABLE.get(c) ?? c).join("");
  return mapped.replaceAll("rn", "m").replaceAll("vv", "w").replaceAll("-", "");
}

/** Damerau-Levenshtein distance (adjacent swaps count as one edit). */
export function distance(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...new Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) {
    d[0][j] = j;
  }
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
  }
  return d[a.length][b.length];
}

function siteOf(host) {
  try {
    return Services.eTLD.getBaseDomainFromHost(host);
  } catch {
    return host;
  }
}

function brandOf(site) {
  try {
    const suffix = Services.eTLD.getPublicSuffixFromHost(site);
    return site.slice(0, site.length - suffix.length - 1) || site;
  } catch {
    return site.split(".")[0];
  }
}

/** The host in Unicode, whatever the engine would display (mixed-script names stay punycode there). */
function unicodeHost(host) {
  try {
    return Cc["@mozilla.org/network/idn-service;1"].getService(Ci.nsIIDNService).convertACEtoUTF8(host);
  } catch {
    return host;
  }
}

function displayHost(host) {
  try {
    return Cc["@mozilla.org/network/idn-service;1"].getService(Ci.nsIIDNService).convertToDisplayIDN(host);
  } catch {
    return host;
  }
}

/**
 * The saved site `host` imitates, or null. Same site is never suspicious; a saved brand is
 * compared with every label of the visited host, so "paypal.com.login-check.example" matches too.
 */
export function lookalikeOf(host, savedSites) {
  const site = siteOf(host);
  if (savedSites.includes(site)) {
    return null;
  }
  const labels = unicodeHost(host).split(".");
  const siteLabels = labels.slice(0, labels.length - (site.split(".").length - 1));
  for (const saved of savedSites) {
    const brand = brandOf(saved);
    if (brand.length < 4) {
      continue; // too short to compare without false alarms
    }
    const target = skeleton(brand);
    for (const label of siteLabels) {
      const shape = skeleton(label);
      if (shape === target) {
        return saved;
      }
      if (distance(shape, target) <= (target.length >= 8 ? 2 : 1)) {
        return saved;
      }
      const words = label.toLowerCase().split(/[-_]/);
      if (words.length > 1 && words.some(w => skeleton(w) === target) && words.some(w => LOGIN_WORDS.includes(w))) {
        return saved;
      }
    }
  }
  return null;
}

// -- the module -----------------------------------------------------------------------------

class Passwords {
  #data = null;
  #savedSites = null;
  #observing = false;

  async #providers() {
    if (!this.#data) {
      this.#data = await new Promise((resolve, reject) => {
        lazy.NetUtil.asyncFetch({ uri: DATA_URL, loadUsingSystemPrincipal: true }, (stream, status) => {
          if (!Components.isSuccessCode(status)) {
            reject(new PasswordsError("data-missing"));
            return;
          }
          resolve(JSON.parse(lazy.NetUtil.readInputStreamToString(stream, stream.available(), { charset: "UTF-8" })));
        });
      });
    }
    return this.#data.providers;
  }

  async #nativeHost(name) {
    for (const key of ["XREUserNativeManifests", "XRESysNativeManifests"]) {
      try {
        const base = Services.dirsvc.get(key, Ci.nsIFile).path;
        if (await IOUtils.exists(PathUtils.join(base, "native-messaging-hosts", `${name}.json`))) {
          return true;
        }
      } catch {}
    }
    return false;
  }

  /** Who saves and fills passwords in this profile, and what each option needs. */
  async state() {
    const providers = await this.#providers();
    const engineOn = Services.prefs.getBoolPref("signon.rememberSignons", true);
    const list = [];
    for (const key of ORDER.filter(k => providers[k])) {
      const provider = providers[key];
      const item = { key, extension: null, native: null };
      if (provider.extension) {
        const addon = await lazy.AddonManager.getAddonByID(provider.extension.id);
        item.extension = {
          name: provider.extension.name,
          pinned: provider.extension.version,
          installed: Boolean(addon),
          enabled: Boolean(addon?.isActive),
          version: addon?.version ?? null,
        };
      }
      if (provider.native) {
        item.native = { required: Boolean(provider.native.required), found: await this.#nativeHost(provider.native.name) };
      }
      list.push(item);
    }
    let current = engineOn ? "builtin" : null;
    if (!current) {
      current = list.find(i => i.extension?.enabled)?.key ?? "none";
    }
    // A count only, and counted without reading the logins: reading them decrypts them, which asks for the primary
    // password of a profile that has one, every time a page shows this state.
    return { current, providers: list, engineLogins: await Services.logins.countLoginsAsync("", "", "") };
  }

  /**
   * Use a provider in this profile (after the user's confirmation in the page). Installs the pinned
   * official extension if needed, turns it on, and sets the engine's prompts. Saved engine logins
   * are never deleted; choosing "builtin" does not remove any extension (flow H).
   */
  async choose(key) {
    const providers = await this.#providers();
    const provider = providers[key];
    if (!provider) {
      fail("unknown-provider");
    }
    if (provider.extension) {
      const pinned = provider.extension;
      let addon = await lazy.AddonManager.getAddonByID(pinned.id);
      if (!addon) {
        const install = await lazy.AddonManager.getInstallForURL(pinned.url, {
          hash: `sha256:${pinned.sha256}`,
          name: pinned.name,
          version: pinned.version,
          telemetryInfo: { source: "nulavio-shell" },
        });
        addon = await install.install().catch(() => null);
        if (!addon || addon.id !== pinned.id) {
          fail("install-failed"); // download, hash or signature check failed: nothing changed
        }
      }
      if (!addon.isActive) {
        await addon.enable();
      }
    }
    for (const [name, value] of Object.entries(provider.prefs)) {
      Services.prefs.setBoolPref(name, value);
    }
    return this.state();
  }

  // -- flow D ------------------------------------------------------------------------------

  async #sites() {
    if (!this.#savedSites) {
      const logins = await Services.logins.getAllLogins();
      const sites = new Set();
      for (const login of logins) {
        try {
          sites.add(siteOf(new URL(login.origin).hostname));
        } catch {}
      }
      this.#savedSites = [...sites];
      if (!this.#observing) {
        this.#observing = true;
        Services.obs.addObserver(() => (this.#savedSites = null), "passwordmgr-storage-changed");
      }
    }
    return this.#savedSites;
  }

  #dismissed() {
    try {
      const list = JSON.parse(Services.prefs.getStringPref(PREF_DISMISSED, "[]"));
      return Array.isArray(list) ? list : [];
    } catch {
      return [];
    }
  }

  /** Whether a password field on `url` belongs to a site that imitates one with a saved login. */
  async checkLogin(url) {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      return { suspicious: false };
    }
    if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname) {
      return { suspicious: false };
    }
    const similar = lookalikeOf(parsed.hostname, await this.#sites());
    const pair = similar ? pairEntry(siteOf(parsed.hostname), similar) : null;
    if (!similar || this.#dismissed().some(entry => pairEntry(...String(entry).split(" ")) === pair)) {
      return { suspicious: false };
    }
    return { suspicious: true, site: displayHost(siteOf(parsed.hostname)), similar };
  }

  /** Nulavio's own pages take a protected profile's password (unlock, protection, phone). The engine's
     password manager must never offer to keep it: it would copy that password into the logins of the
     profile that happens to be open, which may have no protection at all. Saving is turned off for the
     Shell's origin, the exception a person sets with "never save for this site". The engine checks it
     before a submitted form and before an edited password field (LoginManagerParent), and offers no
     generated password where saving is off. Set again at every start, so removing the exception in
     the engine's settings does not last. The permission service is used directly: Services.logins
     would load the password manager during startup. */
  excludeShellPages(origin) {
    const principal = Services.scriptSecurityManager.createContentPrincipal(Services.io.newURI(origin), {});
    if (Services.perms.testExactPermissionFromPrincipal(principal, PERMISSION_SAVE_LOGINS) !== Services.perms.DENY_ACTION) {
      Services.perms.addFromPrincipal(principal, PERMISSION_SAVE_LOGINS, Services.perms.DENY_ACTION);
    }
  }

  /** Watch password fields in web pages (top documents only), through the engine's window actors. */
  registerLookalikeCheck() {
    if (this.registered) {
      return;
    }
    this.registered = true;
    const base = "resource://builtin-addons/nulavio-shell/modules/";
    ChromeUtils.registerWindowActor("NulavioLookalike", {
      parent: { esModuleURI: `${base}NulavioLookalikeParent.sys.mjs` },
      child: { esModuleURI: `${base}NulavioLookalikeChild.sys.mjs`, events: { focusin: { capture: true } } },
      matches: ["http://*/*", "https://*/*"],
      allFrames: false,
      messageManagerGroups: ["browsers"],
      // Runs in web content processes: the parent trusts no data from them. The only message carries
      // no data, and the address comes from the engine (documentURI), not from the page.
      safeForUntrustedWebProcess: true,
    });
  }

  /** "Continue anyway": not asked again for this pair of sites (kept in this profile only). */
  dismiss(site, similar) {
    const entry = pairEntry(site, similar);
    const list = this.#dismissed().filter(e => e !== entry);
    list.push(entry);
    Services.prefs.setStringPref(PREF_DISMISSED, JSON.stringify(list.slice(-200)));
  }

  /** The pairs the person chose to continue on, newest first (Settings › Passwords). */
  listConfirmed() {
    return this.#dismissed()
      .map(entry => {
        const [site = "", similar = ""] = String(entry).split(" ");
        return { site: displayHost(site), similar };
      })
      .filter(pair => pair.site && pair.similar)
      .reverse();
  }

  /** Undo "continue anyway": the warning comes back for this pair. Removing a pair that is not there changes nothing. */
  removeConfirmed(site, similar) {
    const wanted = pairEntry(site, similar);
    const left = this.#dismissed().filter(entry => {
      const [s = "", t = ""] = String(entry).split(" ");
      return pairEntry(s, t) !== wanted;
    });
    if (left.length) {
      Services.prefs.setStringPref(PREF_DISMISSED, JSON.stringify(left));
    } else {
      Services.prefs.clearUserPref(PREF_DISMISSED);
    }
    return this.listConfirmed();
  }
}

/** A stored pair: both sites in the engine's ASCII form, as checkLogin() compares them. */
function pairEntry(site, similar) {
  const ace = host => {
    try {
      return Cc["@mozilla.org/network/idn-service;1"].getService(Ci.nsIIDNService).convertUTF8toACE(String(host)).toLowerCase();
    } catch {
      return String(host).toLowerCase();
    }
  };
  return `${ace(site)} ${ace(similar)}`;
}

export const NulavioPasswords = new Passwords();
