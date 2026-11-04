/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio Connect, P0 (docs/adr/0004-nulavio-connect.md).

   What the desktop offers this browser, checked for real: D-Bus name
   ownership and properties on the session bus (busctl), the freedesktop
   default-application settings (xdg-settings, xdg-mime), and the files an
   integration installs itself. Programs run with an argument list through
   the engine's Subprocess module, never a shell, and with a timeout.
   Discovery changes nothing and sends nothing anywhere. When something
   cannot be known the state is "unknown"; nothing is guessed.

   The one change offered is making Nulavio the default browser, only on the
   user's click, with the previous choice kept so it can be restored.
   Definitions are shared with the launcher (browser/config/integrations.json). */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  callTool: "resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs",
  AddonManager: "resource://gre/modules/AddonManager.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
  Subprocess: "resource://gre/modules/Subprocess.sys.mjs",
});

const DEFINITIONS_URL = "resource://builtin-addons/nulavio-shell/shared/integrations.json";
const DESKTOP_ID = "net.nulavio.Nulavio.desktop";
const PREF_PREVIOUS = "nulavio.connect.previousBrowser";
const PICKER_PREF = "widget.use-xdg-desktop-portal.file-picker";
const TIMEOUT_MS = 5000;
// No spaces or quoting: xdg-settings reads the first word of Exec= without unquoting it.
const SAFE_PATH = /^\/[A-Za-z0-9._+\-/]+$/;
// Standard system locations of native-messaging hosts; a build reads one of them (fixed at build time).
const SYSTEM_HOST_DIRS = ["/usr/lib64/mozilla/native-messaging-hosts", "/usr/lib/mozilla/native-messaging-hosts"];
const DESKTOP_ID_RE = /^[A-Za-z0-9._-]+\.desktop$/;

export class ConnectError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "ConnectError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new ConnectError(code, message);
}

function readText(uri) {
  return new Promise((resolve, reject) => {
    lazy.NetUtil.asyncFetch({ uri, loadUsingSystemPrincipal: true }, (stream, status) => {
      if (!Components.isSuccessCode(status)) {
        reject(new Error(`cannot read ${uri}`));
        return;
      }
      resolve(lazy.NetUtil.readInputStreamToString(stream, stream.available(), { charset: "UTF-8" }));
    });
  });
}

/** Run a program found on PATH with an argument list; {exitCode, stdout} or null if absent. */
export async function run(command, args) {
  let path;
  try {
    path = await lazy.Subprocess.pathSearch(command);
  } catch {
    return null;
  }
  const proc = await lazy.Subprocess.call({ command: path, arguments: args, stderr: "pipe" });
  const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  timer.initWithCallback(() => proc.kill(), TIMEOUT_MS, Ci.nsITimer.TYPE_ONE_SHOT);
  const drain = async pipe => {
    let text = "";
    let chunk;
    while ((chunk = await pipe.readString())) {
      text += chunk;
    }
    return text.trim();
  };
  try {
    const [stdout, stderr] = await Promise.all([drain(proc.stdout), drain(proc.stderr)]);
    const { exitCode } = await proc.wait();
    return { exitCode, stdout, stderr };
  } finally {
    timer.cancel();
  }
}

async function nameOwner(name) {
  // NameHasOwner first: asking about an absent, activatable name must not start its service.
  const has = await run("busctl", [
    "--user", "--no-pager", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
    "org.freedesktop.DBus", "NameHasOwner", "s", name,
  ]);
  if (!has || has.exitCode !== 0 || has.stdout !== "b true") {
    return null;
  }
  const result = await run("busctl", ["--user", "--no-pager", "status", name]);
  if (!result || result.exitCode !== 0) {
    return null;
  }
  const fields = Object.fromEntries(
    result.stdout.split("\n").filter(l => l.includes("=")).map(l => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)])
  );
  const exe = fields.Exe ?? "";
  // Comm is cut to 15 characters by the kernel; the executable's name is not.
  return exe ? PathUtils.filename(exe) : fields.Comm || "a process";
}

async function busProperty(bus, path, iface, prop) {
  const result = await run("busctl", ["--user", "--no-pager", "get-property", bus, path, iface, prop]);
  const match = result?.exitCode === 0 ? /^[a-z]\s+(.+)$/.exec(result.stdout) : null;
  return match ? match[1].replace(/^"|"$/g, "") : null;
}

async function xdg(args) {
  const result = await run(args[0], args.slice(1));
  return result && result.exitCode === 0 ? result.stdout : "";
}

function dataDirs() {
  const home = Services.env.get("HOME");
  const dataHome = Services.env.get("XDG_DATA_HOME") || PathUtils.join(home, ".local", "share");
  const others = (Services.env.get("XDG_DATA_DIRS") || "/usr/local/share:/usr/share").split(":").filter(Boolean);
  return [dataHome, ...others];
}

async function desktopName(desktopId) {
  if (!DESKTOP_ID_RE.test(desktopId)) {
    return desktopId;
  }
  for (const base of dataDirs()) {
    try {
      const text = await IOUtils.readUTF8(PathUtils.join(base, "applications", desktopId));
      const line = text.split("\n").find(l => l.startsWith("Name="));
      if (line) {
        return line.slice(5).trim();
      }
    } catch {}
  }
  return desktopId;
}

function status(spec, state, reason, params = {}, evidence = []) {
  return { id: spec.id, priority: spec.priority, state, reason, params, evidence };
}

class NulavioConnectClass {
  #definitions = null;

  async definitions() {
    this.#definitions ??= JSON.parse(await readText(DEFINITIONS_URL)).integrations;
    return this.#definitions;
  }

  // -- probes --------------------------------------------------------------

  async #plasma(spec) {
    // The directories this build reads (as NativeManifests.sys.mjs does).
    const dirs = ["XREUserNativeManifests", "XRESysNativeManifests"]
      .map(key => {
        try {
          return PathUtils.join(Services.dirsvc.get(key, Ci.nsIFile).path, "native-messaging-hosts");
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    let manifestPath = null;
    for (const dir of dirs) {
      const candidate = PathUtils.join(dir, `${spec.nativeHost}.json`);
      if (await IOUtils.exists(candidate)) {
        manifestPath = candidate;
        break;
      }
    }
    if (!manifestPath) {
      for (const other of SYSTEM_HOST_DIRS.filter(d => !dirs.includes(d))) {
        if (await IOUtils.exists(PathUtils.join(other, `${spec.nativeHost}.json`))) {
          return status(spec, "unavailable", "not-read", { dir: other }, [
            `${spec.nativeHost}.json is in ${other}`,
            `this build reads ${dirs.join(" and ")}`,
          ]);
        }
      }
      return status(spec, "unavailable", "not-installed", {}, [`no ${spec.nativeHost}.json in ${dirs.join(", ")}`]);
    }
    let manifest;
    try {
      manifest = await IOUtils.readJSON(manifestPath);
    } catch (e) {
      return status(spec, "error", "manifest-unreadable", {}, [`${manifestPath}: ${e.message}`]);
    }
    const evidence = [`host manifest ${manifestPath}`];
    const host = String(manifest.path ?? "");
    let info = null;
    try {
      info = host ? await IOUtils.stat(host) : null;
    } catch {}
    if (!info || info.type !== "regular" || !(info.permissions & 0o111)) {
      return status(spec, "error", "host-missing", {}, [...evidence, `missing ${host}`]);
    }
    if (info.permissions & 0o022) {
      return status(spec, "error", "host-writable", {}, [...evidence, `${host} is group/world-writable`]);
    }
    if (!(manifest.allowed_extensions ?? []).includes(spec.extension)) {
      return status(spec, "error", "extension-not-allowed", {}, [...evidence, `${spec.extension} not in allowed_extensions`]);
    }
    evidence.push(`host program ${host}`);
    const session = await nameOwner(spec.session);
    if (!session) {
      return status(spec, "unavailable", "no-session", {}, [...evidence, `D-Bus name ${spec.session} not owned`]);
    }
    evidence.push(`D-Bus name ${spec.session} owned by ${session}`);
    const addon = await lazy.AddonManager.getAddonByID(spec.extension);
    if (addon?.isActive) {
      return status(spec, "enabled", "enabled", {}, [...evidence, `extension ${spec.extension} ${addon.version} active in this profile`]);
    }
    return status(spec, "available", "ready", { page: spec.extensionPage }, [
      ...evidence,
      `extension ${spec.extension} ${addon ? "installed but disabled" : "not installed"} in this profile`,
    ]);
  }

  async #portals(spec) {
    const owner = await nameOwner(spec.busName);
    if (!owner) {
      return status(spec, "unavailable", "no-service", {}, [`D-Bus name ${spec.busName} not owned`]);
    }
    const versions = [];
    for (const iface of spec.interfaces) {
      const version = await busProperty(spec.busName, spec.objectPath, `org.freedesktop.portal.${iface}`, "version");
      versions.push(`${iface} ${version ? `v${version}` : "not reported"}`);
    }
    const picker = Services.prefs.getIntPref(PICKER_PREF, 2);
    const usage = picker === 1 ? "always" : picker === 0 ? "never" : "automatic";
    return status(spec, "available", "ready", { picker: usage }, [
      `D-Bus name ${spec.busName} owned by ${owner}`,
      `interfaces: ${versions.join(", ")}`,
      `${PICKER_PREF} = ${picker} (${usage})`,
    ]);
  }

  async #secrets(spec) {
    const owner = await nameOwner(spec.busName);
    const related = [];
    for (const name of spec.related ?? []) {
      if (await nameOwner(name)) {
        related.push(`D-Bus name ${name} owned`);
      }
    }
    if (!owner) {
      return status(spec, "unavailable", "no-service", {}, [`D-Bus name ${spec.busName} not owned`, ...related]);
    }
    return status(spec, "available", "ready", { provider: owner }, [`D-Bus name ${spec.busName} owned by ${owner}`, ...related]);
  }

  async #defaultBrowser(spec) {
    if (!(await run("xdg-settings", ["--version"]))) {
      return status(spec, "unknown", "no-tool", {}, ["xdg-settings is not installed"]);
    }
    const current = await xdg(["xdg-settings", "get", "default-web-browser"]);
    const evidence = [`xdg-settings default-web-browser: ${current || "not set"}`];
    const handlers = [];
    for (const type of spec.types) {
      const handler = await xdg(["xdg-mime", "query", "default", type]);
      handlers.push(handler);
      evidence.push(`xdg-mime ${type}: ${handler || "not set"}`);
    }
    const ours = new Set(spec.nulavioDesktopIds);
    const previous = Services.prefs.getStringPref(PREF_PREVIOUS, "");
    const previousName = previous ? await desktopName(previous) : "";
    if (ours.has(current) && handlers.slice(0, 2).every(h => ours.has(h))) {
      return status(spec, "enabled", "is-nulavio", { previous, previousName }, evidence);
    }
    return status(spec, "available", "other", { name: current ? await desktopName(current) : "", previous, previousName }, evidence);
  }

  // -- public ---------------------------------------------------------------

  async discover() {
    const probes = {
      "plasma-browser-integration": spec => this.#plasma(spec),
      "xdg-portals": spec => this.#portals(spec),
      "secret-service": spec => this.#secrets(spec),
      "default-browser": spec => this.#defaultBrowser(spec),
    };
    const results = [];
    const definitions = await this.definitions();
    for (const spec of definitions.filter(d => d.priority === "P0")) {
      try {
        results.push(await probes[spec.id](spec));
      } catch (e) {
        results.push(status(spec, "error", "check-failed", {}, [String(e?.message ?? e)]));
      }
    }
    // P1/P2: probed by the Nulavio tools (one implementation, shared with `nulavio integrations`).
    const later = definitions.filter(d => d.priority !== "P0");
    if (later.length) {
      let items = [];
      try {
        items = (await lazy.callTool(["integrations", "api"], { op: "discover" }, 30000)).items ?? [];
      } catch (e) {
        items = later.map(spec => status(spec, "unknown", "tools-missing", {}, [String(e?.code ?? e)]));
      }
      for (const spec of later) {
        const item = items.find(i => i.id === spec.id);
        results.push(item ? status(spec, item.state, item.reason || "check-failed", item.params ?? {}, item.evidence ?? []) : status(spec, "unknown", "check-failed"));
      }
    }
    return results;
  }

  async #tools(request) {
    try {
      return await lazy.callTool(["integrations", "api"], request, 30000);
    } catch (e) {
      fail(e.code ?? "helper-failed");
    }
  }

  /** KDE Connect devices reachable now: [{id, name}]. */
  async kdeDevices() {
    return (await this.#tools({ op: "devices" })).devices ?? [];
  }

  /** Share one web address with one device, on the user's click (link menu). */
  async sendLink(url, device) {
    if (!/^https?:\/\//.test(String(url))) {
      fail("bad-url");
    }
    return this.#tools({ op: "send-link", url: String(url), device: String(device) });
  }

  /** Install or remove the KRunner plugin (two user-level files). */
  async setKrunner(enabled) {
    return this.#tools({ op: enabled ? "krunner-enable" : "krunner-disable" });
  }

  /** The user clicked "Make Nulavio the default browser". */
  /** The default-browser check alone, for the new tab's first run (no other probe, no tools). */
  async defaultBrowserState() {
    const spec = (await this.definitions()).find(d => d.id === "default-browser");
    const { state, reason } = await this.#defaultBrowser(spec);
    return { state, reason };
  }

  async setDefaultBrowser() {
    const spec = (await this.definitions()).find(d => d.id === "default-browser");
    const before = await xdg(["xdg-settings", "get", "default-web-browser"]);
    const entryPath = await this.#writeDesktopEntry();
    const result = await run("xdg-settings", ["set", "default-web-browser", DESKTOP_ID]);
    if (!result) {
      fail("no-tool");
    }
    if (result.exitCode !== 0) {
      fail("set-failed", `exit ${result.exitCode}: ${result.stderr || result.stdout}`);
    }
    const after = await this.#defaultBrowser(spec);
    if (after.state !== "enabled") {
      fail("not-applied", after.evidence.join("; "));
    }
    if (before && !spec.nulavioDesktopIds.includes(before) && DESKTOP_ID_RE.test(before)) {
      Services.prefs.setStringPref(PREF_PREVIOUS, before);
    }
    return { desktopEntry: entryPath };
  }

  /** The user clicked "Restore <previous browser>". */
  async restoreDefaultBrowser() {
    const previous = Services.prefs.getStringPref(PREF_PREVIOUS, "");
    if (!DESKTOP_ID_RE.test(previous)) {
      fail("no-previous");
    }
    const result = await run("xdg-settings", ["set", "default-web-browser", previous]);
    if (!result || result.exitCode !== 0) {
      fail("set-failed", result?.stdout ?? "");
    }
    Services.prefs.clearUserPref(PREF_PREVIOUS);
  }

  /** A user-level desktop entry for this installation (needed by the default-application settings). */
  async #writeDesktopEntry() {
    const binary = Services.dirsvc.get("XREExeF", Ci.nsIFile);
    const launcher = binary.parent.clone();
    launcher.append(binary.leafName.replace(/-bin$/, ""));
    const exec = launcher.exists() ? launcher.path : binary.path;
    if (!SAFE_PATH.test(exec)) {
      fail("path-unsupported", exec);
    }
    const iconFile = PathUtils.join(binary.parent.path, "browser", "chrome", "icons", "default", "default128.png");
    const icon = (await IOUtils.exists(iconFile)) && SAFE_PATH.test(iconFile) ? iconFile : "web-browser";
    const entry = [
      "[Desktop Entry]",
      "Type=Application",
      "Version=1.5",
      "Name=Nulavio",
      "GenericName=Web Browser",
      "Comment=Private by default; works with your password manager",
      `Exec=${exec} %u`,
      `Icon=${icon}`,
      "Terminal=false",
      "StartupNotify=true",
      "StartupWMClass=nulavio",
      "Categories=Network;WebBrowser;",
      // xdg-settings expects a default browser to declare about: and unknown schemes too.
      "MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/about;x-scheme-handler/unknown;",
      "",
    ].join("\n");
    const dir = PathUtils.join(dataDirs()[0], "applications");
    await IOUtils.makeDirectory(dir, { ignoreExisting: true, permissions: 0o755 });
    const path = PathUtils.join(dir, DESKTOP_ID);
    await IOUtils.writeUTF8(path, entry, { tmpPath: `${path}.tmp` });
    await IOUtils.setPermissions(path, 0o644);
    return path;
  }
}

export const NulavioConnect = new NulavioConnectClass();
