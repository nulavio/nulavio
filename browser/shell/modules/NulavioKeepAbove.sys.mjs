/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* "Manter acima das outras janelas", on KDE Plasma (#170).

   Wayland gives an application no way to ask for its window to stay above the others. KDE Plasma's window
   manager, KWin, can do it ("keep above"), and lets a program on the same session bus ask through its D-Bus
   interfaces. Everything here goes through busctl with an argument list (NulavioConnect.run: no shell, a
   timeout), as Nulavio Connect does:
   - which window is this one: KWin's own list of windows (its "windows" runner, which matches captions), each
     answer checked with getWindowInfo against this process's id and a caption made unique for that moment.
     The window's id is kept for the window's life and checked again on each use;
   - the change: a KWin script of one line, written by this module with only that id (checked to be a UUID)
     and true or false in it, loaded, run once and unloaded. It changes nothing but that window's keepAbove;
   - the state shown: read back from KWin (getWindowInfo), never assumed.
   Elsewhere (another desktop, KWin not on the bus, scripting off) the menu item is shown unavailable, with
   the reason. Nothing is sent anywhere but to KWin on this session's bus. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  run: "resource://builtin-addons/nulavio-shell/modules/NulavioConnect.sys.mjs",
});

const KWIN = "org.kde.KWin";
const PLUGIN = "nulavio-keep-above";
const UUID = /^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$/;
const MARK = "nulavio-keep-above-";

function fail(code) {
  throw Object.assign(new Error(code), { code });
}

async function bus(...args) {
  const result = await lazy.run("busctl", ["--user", "--no-pager", "--json=short", "call", ...args]);
  if (!result || result.exitCode !== 0) {
    return null;
  }
  if (!result.stdout) {
    return []; // a method that returns nothing
  }
  try {
    return JSON.parse(result.stdout).data;
  } catch {
    return null;
  }
}

/** Whether KWin is on this session's bus with its scripting interface; the reason when it is not. */
async function kwin() {
  const has = await bus("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", KWIN);
  if (!has) {
    return { available: false, reason: "keepAboveNoBus" };
  }
  if (has[0] !== true) {
    return { available: false, reason: "keepAboveNotPlasma" };
  }
  const loaded = await bus(KWIN, "/Scripting", "org.kde.kwin.Scripting", "isScriptLoaded", "s", PLUGIN);
  return loaded ? { available: true, reason: null } : { available: false, reason: "keepAboveNoScripting" };
}

/** KWin's record of one window: { pid, caption, keepAbove }, or null. */
async function info(uuid) {
  const data = await bus(KWIN, "/KWin", "org.kde.KWin", "getWindowInfo", "s", uuid);
  const fields = data?.[0];
  if (!fields || typeof fields !== "object") {
    return null;
  }
  const value = name => fields[name]?.data;
  return { pid: value("pid"), caption: value("caption"), keepAbove: value("keepAbove") === true };
}

function wait(ms) {
  return new Promise(resolve => {
    const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    timer.initWithCallback(resolve, ms, Ci.nsITimer.TYPE_ONE_SHOT);
  });
}

/* The window's id in KWin. Its caption is made unique for a moment (a random mark), the runner is asked for it,
   and an answer counts only if KWin says it is a window of this process with exactly that caption. */
async function findWindow(win) {
  const doc = win.document;
  const mark = MARK + Services.uuid.generateUUID().toString().slice(1, -1);
  const before = doc.title;
  doc.title = mark;
  try {
    for (let attempt = 0; attempt < 20; attempt++) {
      await wait(50);
      const matches = (await bus(KWIN, "/WindowsRunner", "org.kde.krunner1", "Match", "s", mark))?.[0] ?? [];
      for (const match of matches) {
        const uuid = String(match?.[0] ?? "").replace(/^\d+_/, "");
        if (!UUID.test(uuid)) {
          continue;
        }
        const found = await info(uuid);
        if (found?.pid === Services.appinfo.processID && found.caption === mark) {
          return uuid;
        }
      }
    }
    return null;
  } finally {
    if (doc.title === mark) {
      doc.title = before;
    }
    win.gBrowser?.updateTitlebar?.();
  }
}

const windows = new WeakMap(); // chrome window → its id in KWin

async function windowId(win) {
  const known = windows.get(win);
  if (known) {
    const now = await info(known);
    if (now?.pid === Services.appinfo.processID) {
      return known;
    }
    windows.delete(win);
  }
  const found = await findWindow(win);
  if (found) {
    windows.set(win, found);
  }
  return found;
}

/** The one line KWin runs: that window, kept above or not. `uuid` is checked; `on` is a boolean. */
export function script(uuid, on) {
  if (!UUID.test(uuid) || typeof on !== "boolean") {
    fail("keep-above-invalid");
  }
  return `// Nulavio (#170): keep one window above the others, or not.\n` +
    `for (const w of workspace.windowList()) { if (w.internalId.toString() === "${uuid}") { w.keepAbove = ${on}; } }\n`;
}

let queue = Promise.resolve(); // one change at a time: two windows never share a script or a plugin name

async function runScript(text) {
  const run = queue.then(() => runScriptNow(text));
  queue = run.catch(() => {});
  return run;
}

async function runScriptNow(text) {
  // A new directory and a new file for each run, both created here (a link or anything already at either path is
  // refused), so nothing is written through a path another program prepared.
  const dir = await IOUtils.createUniqueDirectory(PathUtils.profileDir, PLUGIN, 0o700);
  const name = PathUtils.filename(dir);
  const file = PathUtils.join(dir, "script.js");
  try {
    await IOUtils.writeUTF8(file, text, { mode: "create" });
    await IOUtils.setPermissions(file, 0o600);
  } catch (e) {
    await IOUtils.remove(dir, { recursive: true, ignoreAbsent: true });
    throw e;
  }
  try {
    const id = (await bus(KWIN, "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", file, name))?.[0];
    if (!Number.isInteger(id) || id < 0) {
      fail("keep-above-failed");
    }
    if (!(await bus(KWIN, `/Scripting/Script${id}`, "org.kde.kwin.Script", "run"))) {
      fail("keep-above-failed");
    }
  } finally {
    await bus(KWIN, "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", name);
    await IOUtils.remove(dir, { recursive: true, ignoreAbsent: true });
  }
}

const MENU_ITEM = "nulavio-menu-keep-above";
let watching = null;

function t(key) {
  return WebExtensionPolicy.getByID("shell@nulavio.net")?.extension?.localizeMessage(key) || key;
}

/* The View menu's checkbox, next to Full Screen: its state is KWin's, read each time the menu opens. Where KWin
   cannot do it, the item is disabled and says why. */
function addMenuItem(win) {
  const doc = win.document;
  const popup = doc.getElementById("menu_viewPopup");
  if (!popup || doc.getElementById(MENU_ITEM)) {
    return;
  }
  const item = doc.createXULElement("menuitem");
  item.id = MENU_ITEM;
  item.setAttribute("type", "checkbox");
  item.setAttribute("label", t("menuKeepAbove"));
  item.setAttribute("autocheck", "false");
  const say = key => win.A11yUtils?.announce({ raw: t(key) }).catch(() => {});
  item.addEventListener("command", () => {
    NulavioKeepAbove.set(win, null, say).catch(e => e?.code || console.error(e));
  });
  popup.addEventListener("popupshowing", event => {
    if (event.target !== popup) {
      return;
    }
    item.setAttribute("disabled", "true"); // until KWin has answered
    NulavioKeepAbove.state(win).then(
      now => {
        item.setAttribute("checked", String(now.on));
        item.toggleAttribute("disabled", !now.available);
        item.setAttribute("label", now.available ? t("menuKeepAbove") : `${t("menuKeepAbove")} (${t(now.reason)})`);
      },
      e => console.error(e)
    );
  });
  const fullScreen = [doc.getElementById("fullScreenItem"), doc.getElementById("enterFullScreenItem")].find(node => node?.parentNode === popup);
  popup.insertBefore(item, fullScreen ?? null);
}

export const NulavioKeepAbove = {
  /** From the Shell's start: the View menu item in every browser window. */
  watch() {
    if (watching) {
      return;
    }
    watching = { observe: win => addMenuItem(win) };
    Services.obs.addObserver(watching, "browser-delayed-startup-finished");
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (win.gBrowserInit?.delayedStartupFinished) {
        addMenuItem(win);
      }
    }
  },

  /** For a browser window: { available, reason, on } as KWin reports it now. */
  async state(win) {
    const desktop = await kwin();
    if (!desktop.available) {
      return { ...desktop, on: false };
    }
    const uuid = await windowId(win);
    const now = uuid ? await info(uuid) : null;
    return now ? { available: true, reason: null, on: now.keepAbove } : { available: false, reason: "keepAboveNoWindow", on: false };
  },

  /** KWin's id for the window, as this module found and checked it (for the tests). */
  windowId(win) {
    return windowId(win);
  },

  /** Keep the window above the others or not (`on` null: the other way). `say(key)` announces what KWin did. */
  async set(win, on = null, say = () => {}) {
    const desktop = await kwin();
    if (!desktop.available) {
      say(desktop.reason);
      fail("keep-above-unavailable");
    }
    const uuid = await windowId(win);
    const before = uuid ? await info(uuid) : null;
    if (!before) {
      say("keepAboveNoWindow");
      fail("keep-above-unavailable");
    }
    const want = on === null ? !before.keepAbove : Boolean(on);
    await runScript(script(uuid, want));
    const after = await info(uuid);
    if (after?.keepAbove !== want) {
      say("keepAboveFailed");
      fail("keep-above-failed");
    }
    say(want ? "keepAboveOn" : "keepAboveOff");
    return { available: true, reason: null, on: after.keepAbove };
  },
};
