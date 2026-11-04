/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Gecko159 owns tab orientation, hover, sizing and session persistence.
   D-UX2 adopts Lateral once on genuinely brand-new profiles while keeping
   pre-existing profiles untouched; no shadow "selected preset" preference. */

export const PREF_ADOPTION_VERSION = "nulavio.layout.adoptionVersion";
export const PREF_CHOICE_PENDING = "nulavio.layout.choicePending";
// UX3G N-4 (provisional decision): only profiles this build sees as new start on the Shell's
// new tab; profiles that came from earlier builds keep about:home. Written once, with adoption.
export const PREF_SHELL_START = "nulavio.startpage.shellFirstTab";
// UX6 (D-UX23): the preset the Foco key returns to.
export const PREF_BEFORE_FOCUS = "nulavio.layout.beforeFocus";

// UX3F (QA A5): Lateral's launcher width on adoption, in CSS pixels (engine default ~246).
export const ADOPTED_LAUNCHER_WIDTH = 224;
const PRESETS = Object.freeze({ lateral: "always-show", top: "hide-on-close", focus: "expand-on-hover" });
const SIDEBAR_PREFS = ["sidebar.verticalTabs", "sidebar.visibility", "sidebar.revamp"];
const OBSERVED_PREFS = [...SIDEBAR_PREFS, PREF_CHOICE_PENDING];
// Note: SidebarManager.init() automatically writes sidebar.visibility="hide-on-close"
// when verticalTabs is false, so "hide-on-close" in memory alone is not a prior-session signal.
const EXISTING_PROFILE_PREFS = [
  "sidebar.verticalTabs",
  "sidebar.backupState",
  "sidebar.new-sidebar.has-used",
];
// Files written only after a browser session has already run (never before profile lock on first boot).
const EXISTING_PROFILE_FILES = ["nulavio-guard.json", "xulstore.json", "sessionstore.jsonlz4"];
// QA A-1: one window's native step (Lit update, animation, hover measurement) settles well
// under a second. A window that closes mid-step can leave those promises pending forever,
// so each step ends when it finishes, when its window unloads, or at this deadline.
export const WINDOW_STEP_TIMEOUT_MS = 4000;
// Whole-apply safety net: the queue always moves on, even if something unforeseen hangs.
export const APPLY_DEADLINE_MS = 20000;
const GONE = Symbol("window-gone");
const TIMED_OUT = Symbol("window-timed-out");

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  CustomizableUI: "moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs",
  NetUtil: "resource://gre/modules/NetUtil.sys.mjs",
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
});

let applying = Promise.resolve();
let pendingInitialAdoption = null;

function layoutError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function fail(code) {
  throw layoutError(code);
}

function resolveTarget(target) {
  return typeof target === "function" ? target() : target;
}

function isWindowObject(target) {
  return Boolean(target && typeof target.closed === "boolean" && target.document);
}

function windowOf(target) {
  const resolved = resolveTarget(target);
  if (!resolved) return null;
  if (isWindowObject(resolved)) return resolved;
  const global = resolved.documentGlobal ?? resolved.ownerGlobal;
  return global?.browsingContext?.topChromeWindow ?? null;
}

function controller(win) {
  if (!win || win.closed || win.document.documentElement.getAttribute("windowtype") !== "navigator:browser"
      || !win.toolbar.visible || !win.SidebarController || win.SidebarController.uninitializing) {
    fail("layout-unavailable");
  }
  return win.SidebarController;
}

function windowGone(win) {
  try {
    return !win || win.closed || !win.SidebarController || win.SidebarController.uninitializing;
  } catch {
    return true;
  }
}

function startTimer(ms, callback) {
  const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  timer.initWithCallback(callback, ms, Ci.nsITimer.TYPE_ONE_SHOT);
  return timer;
}

// Run one native step for `win`. It settles with the step's result, with GONE as soon as the
// window unloads (or the step fails because it closed), or with TIMED_OUT at the deadline.
function settleInWindow(win, step, ms = WINDOW_STEP_TIMEOUT_MS) {
  if (windowGone(win)) {
    return Promise.resolve(GONE);
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const finish = (settle, value) => {
      if (settled) return;
      settled = true;
      timer?.cancel();
      try {
        win.removeEventListener("unload", onGone);
      } catch {
        // The window is already gone.
      }
      settle(value);
    };
    const onGone = () => finish(resolve, GONE);
    win.addEventListener("unload", onGone, { once: true });
    timer = startTimer(ms, () => finish(resolve, windowGone(win) ? GONE : TIMED_OUT));
    Promise.resolve().then(step).then(
      value => finish(resolve, value),
      error => (windowGone(win) ? finish(resolve, GONE) : finish(reject, error))
    );
  });
}

async function ready(win) {
  const sidebar = controller(win);
  const started = await settleInWindow(win, () => sidebar.promiseInitialized);
  if (started === GONE || started === TIMED_OUT) {
    // Closed, or its sidebar never finished starting: nothing reliable to read or change.
    fail("layout-unavailable");
  }
  if (pendingInitialAdoption) {
    await pendingInitialAdoption;
  }
  controller(win);
  // Waiting for animations is best effort; only a window that went away is an error.
  if (await settleInWindow(win, () => sidebar.waitUntilStable()) === GONE) {
    fail("layout-unavailable");
  }
  return controller(win);
}

// QA M-1: a "Preferences" policy on any sidebar.* pref (Status default, user, clear or
// locked) means the administrator manages the sidebar. First-run adoption never overrides it.
function policyManagesSidebar() {
  try {
    const prefs = Services.policies?.getActivePolicies?.()?.Preferences;
    // UX3E QA N-2: only a policy over the layout itself (orientation, visibility, the
    // revamped sidebar) keeps a new profile out of adoption; tool lists or the
    // sidebar's side do not.
    return Boolean(prefs) && typeof prefs === "object"
      && Object.keys(prefs).some(name => SIDEBAR_PREFS.includes(name));
  } catch {
    return false;
  }
}

function adoptionUnavailable() {
  return !Services.prefs.getBoolPref("sidebar.revamp", true)
    || SIDEBAR_PREFS.some(pref => Services.prefs.prefIsLocked(pref))
    || policyManagesSidebar();
}

function setShellStart(isNew) {
  if (!Services.prefs.prefIsLocked(PREF_SHELL_START)) {
    Services.prefs.setBoolPref(PREF_SHELL_START, isNew);
  }
}

function setAdoptionMarkers(choicePending) {
  if (!Services.prefs.prefIsLocked(PREF_ADOPTION_VERSION)) {
    Services.prefs.setIntPref(PREF_ADOPTION_VERSION, 1);
  }
  if (!Services.prefs.prefIsLocked(PREF_CHOICE_PENDING)) {
    Services.prefs.setBoolPref(PREF_CHOICE_PENDING, choicePending);
  }
}

function startupCutoffMs() {
  try {
    const info = Services.startup?.getStartupInfo?.();
    const stamp = info?.afterProfileLocked ?? info?.process;
    const ms = stamp?.getTime?.();
    return typeof ms === "number" && Number.isFinite(ms) ? ms : null;
  } catch {
    return null;
  }
}

function readSmallUtf8File(file) {
  if (!file.exists()) {
    return null;
  }
  const stream = Cc["@mozilla.org/network/file-input-stream;1"].createInstance(Ci.nsIFileInputStream);
  stream.init(file, -1, 0, 0);
  try {
    const avail = stream.available();
    if (!avail) {
      return null;
    }
    return lazy.NetUtil.readInputStreamToString(stream, avail, { charset: "UTF-8" });
  } finally {
    stream.close();
  }
}

function fileExistedBeforeStartup(file, cutoff) {
  try {
    if (!file.exists()) {
      return false;
    }
    return cutoff === null || file.lastModifiedTime < cutoff;
  } catch {
    return false;
  }
}

function timesFileHasPriorUse(dir, cutoff) {
  try {
    const timesFile = dir.clone();
    timesFile.append("times.json");
    const text = readSmallUtf8File(timesFile);
    if (!text) {
      return false;
    }
    const times = JSON.parse(text);
    if (typeof times?.firstUse === "number" && times.firstUse > 0) {
      return cutoff === null || times.firstUse < cutoff;
    }
    return false;
  } catch {
    return false;
  }
}

function prefFilesHavePriorState(dir, cutoff) {
  for (const name of ["prefs.js", "user.js"]) {
    try {
      const file = dir.clone();
      file.append(name);
      if (!fileExistedBeforeStartup(file, cutoff)) {
        continue;
      }
      const text = readSmallUtf8File(file);
      if (text && /^\s*user_pref\(\s*"(?:browser\.migration\.version|sidebar\.)/m.test(text)) {
        return true;
      }
    } catch {
      // Ignore unreadable pref files and continue checking other markers.
    }
  }
  return false;
}

function hasExistingProfileState() {
  if (Services.prefs.getIntPref("nulavio.privacy.seeded", 0) >= 1) {
    return true;
  }
  if (EXISTING_PROFILE_PREFS.some(pref => Services.prefs.prefHasUserValue(pref))) {
    return true;
  }
  if (Services.prefs.prefHasUserValue("sidebar.visibility")
      && Services.prefs.getStringPref("sidebar.visibility", "") !== PRESETS.top) {
    return true;
  }
  let dir = null;
  try {
    dir = Services.dirsvc.get("ProfD", Ci.nsIFile);
  } catch {
    // No profile directory bound: fall back to the migration preference.
    return Services.prefs.getIntPref("browser.migration.version", -1) > 0;
  }
  const cutoff = startupCutoffMs();
  for (const name of EXISTING_PROFILE_FILES) {
    const file = dir.clone();
    file.append(name);
    if (fileExistedBeforeStartup(file, cutoff)) {
      return true;
    }
  }
  if (timesFileHasPriorUse(dir, cutoff)) {
    return true;
  }
  // BrowserGlue._beforeUIStartup sets browser.migration.version in memory and
  // XPIProvider may flush prefs.js during this startup; only pref files written
  // before this process locked the profile reflect prior state.
  return prefFilesHavePriorState(dir, cutoff);
}

function hasRegisteredTabstrips(cui) {
  try {
    for (const win of cui.windows) {
      if (win.closed) {
        continue;
      }
      const horizNode = win.document.getElementById(cui.AREA_TABSTRIP);
      const vertNode = win.document.getElementById(cui.AREA_VERTICAL_TABSTRIP);
      const horiz = horizNode && cui.getCustomizationTarget(horizNode);
      const vert = vertNode && cui.getCustomizationTarget(vertNode);
      if (horiz?.classList?.contains("customization-target")
          && vert?.classList?.contains("customization-target")) {
        return true;
      }
    }
  } catch {
    // Fall back to listener registration while CustomizableUI finishes starting.
  }
  return false;
}

function expandAdoptedWindows() {
  const tasks = [];
  for (const w of Services.wm.getEnumerator("navigator:browser")) {
    if (w.closed || !w.toolbar?.visible || w.SidebarController?.uninitializing) {
      continue;
    }
    // Bounded per window (QA A-1): the layout queue waits for this adoption.
    tasks.push(
      settleInWindow(w, async () => {
        await w.SidebarController.promiseInitialized;
        if (!windowGone(w) && w.toolbar?.visible) {
          await w.SidebarController.waitUntilStable();
          if (!windowGone(w) && w.toolbar?.visible) {
            w.SidebarController._state?.updateVisibility(true, true);
            // Native per-window sidebar state (saved with the window), never a pref;
            // a width the person dragged is kept.
            if (w.SidebarController._state && !w.SidebarController._state.expandedLauncherWidth) {
              w.SidebarController._state.expandedLauncherWidth = ADOPTED_LAUNCHER_WIDTH;
            }
            await w.SidebarController.waitUntilStable();
          }
        }
      }).catch(() => {})
    );
  }
  return Promise.all(tasks);
}

function writeAdoptedLateralPrefs() {
  if (adoptionUnavailable() || Services.prefs.prefHasUserValue("sidebar.verticalTabs")) {
    return false;
  }
  Services.prefs.setBoolPref("sidebar.verticalTabs", true);
  Services.prefs.setStringPref("sidebar.visibility", PRESETS.lateral);
  return true;
}

// Write Lateral; when that is no longer possible (a lock, the user's own choice, the native
// sidebar off), the first-run card must not claim the profile started in Lateral.
function commitAdoptedLateral() {
  const written = writeAdoptedLateralPrefs();
  if (!written && !Services.prefs.prefIsLocked(PREF_CHOICE_PENDING)) {
    Services.prefs.setBoolPref(PREF_CHOICE_PENDING, false);
  }
  return written;
}

function scheduleInitialLateralCommit() {
  let cui = null;
  try {
    cui = lazy.CustomizableUI;
  } catch {
    cui = null;
  }
  // CustomizableUI.initialize() runs before extension startup with verticalTabs=false
  // (gCurrentVerticalTabs=false). Setting sidebar.verticalTabs=true before the first
  // window registers TabsToolbar + vertical-tabs makes updateTabStripOrientation()
  // bail out on !tabstripAreasReady, leaving gCurrentVerticalTabs=false and breaking
  // the first switch back to horizontal tabs. Waiting for both areas avoids that.
  if (!cui?.addListener || hasRegisteredTabstrips(cui)) {
    commitAdoptedLateral();
    const done = expandAdoptedWindows().finally(() => {
      if (pendingInitialAdoption === done) {
        pendingInitialAdoption = null;
      }
    });
    pendingInitialAdoption = done;
    return;
  }
  let settled = false;
  let resolveDone;
  const done = new Promise(resolve => {
    resolveDone = resolve;
  });
  pendingInitialAdoption = done;
  const detachHooks = () => {
    cui.removeListener(areaListener);
    for (const [obs, topic] of [
      [delayedStartupObserver, "browser-delayed-startup-finished"],
      [shutdownObserver, "quit-application-granted"],
    ]) {
      try {
        Services.obs?.removeObserver?.(obs, topic);
      } catch {
        // Observer may already be removed.
      }
    }
  };
  const finish = async () => {
    if (settled) {
      return;
    }
    settled = true;
    detachHooks();
    try {
      if (commitAdoptedLateral()) {
        await expandAdoptedWindows();
      }
    } finally {
      if (pendingInitialAdoption === done) {
        pendingInitialAdoption = null;
      }
      resolveDone();
    }
  };
  const maybeFinish = () => {
    if (!settled && hasRegisteredTabstrips(cui)) {
      Promise.resolve().then(finish);
    }
  };
  const areaListener = {
    onAreaNodeRegistered: maybeFinish,
  };
  const delayedStartupObserver = {
    observe: maybeFinish,
  };
  const shutdownObserver = {
    observe() {
      if (!settled) {
        settled = true;
        detachHooks();
        commitAdoptedLateral();
        if (pendingInitialAdoption === done) {
          pendingInitialAdoption = null;
        }
        resolveDone();
      }
    },
  };
  cui.addListener(areaListener);
  Services.obs?.addObserver?.(delayedStartupObserver, "browser-delayed-startup-finished");
  Services.obs?.addObserver?.(shutdownObserver, "quit-application-granted");
}

function liveBrowserWindows() {
  return [...Services.wm.getEnumerator("navigator:browser")]
    .filter(w => !windowGone(w) && w.toolbar.visible);
}

async function applyPreset(target, preset, ticket) {
  if (typeof preset !== "string" || !Object.hasOwn(PRESETS, preset)) {
    fail("layout-invalid");
  }
  await ready(windowOf(target));
  if (!Services.prefs.getBoolPref("sidebar.revamp")) {
    fail("layout-unavailable");
  }
  if (SIDEBAR_PREFS.some(pref => Services.prefs.prefIsLocked(pref))) {
    fail("layout-locked");
  }
  // Another window that closes or never settles is left out; it reads the native prefs
  // itself when it starts. Only the caller's window has to be ready.
  const windows = (await Promise.all(liveBrowserWindows().map(w => ready(w).then(() => w, () => null))))
    .filter(Boolean);
  controller(windowOf(target));
  if (!Services.prefs.getBoolPref("sidebar.revamp")) fail("layout-unavailable");
  if (SIDEBAR_PREFS.some(pref => Services.prefs.prefIsLocked(pref))) fail("layout-locked");
  if (ticket.cancelled) fail("layout-failed");
  // Orientation first: SidebarManager normalizes visibility synchronously.
  // The final explicit visibility then wins, including re-selecting a
  // preset whose prefs already match but whose window was collapsed.
  try {
    Services.prefs.setBoolPref("sidebar.verticalTabs", preset !== "top");
    Services.prefs.setStringPref("sidebar.visibility", PRESETS[preset]);
    if (!Services.prefs.prefIsLocked(PREF_CHOICE_PENDING)) {
      Services.prefs.setBoolPref(PREF_CHOICE_PENDING, false);
    }
    await Promise.all(windows.map(async w => {
      const result = await settleInWindow(w, async () => {
        const sidebar = controller(w);
        await sidebar.waitUntilStable();
        controller(w);
        // updateVisibility affects only launcher expansion/visibility, keeping
        // open panels, widths, position, tools and tab/group data intact.
        sidebar._state.updateVisibility(true, preset === "lateral");
        await sidebar.toggleExpandOnHover(preset === "focus");
        await sidebar.waitUntilStable();
        controller(w);
      });
      if (result === TIMED_OUT) {
        console.warn("Nulavio layout: a window did not settle in time; its native state is reported as it is");
      }
    }));
    return await NulavioLayout.state(target);
  } catch (e) {
    // After a native write, changes may already exist. Never promise a rollback
    // or "nothing changed".
    console.error("Nulavio layout transition", e);
    fail("layout-failed");
  }
}

export const NulavioLayout = {
  /**
   * Adopt Lateral on genuinely brand-new profiles (D-UX2) once on first run,
   * while keeping every pre-existing profile's layout intact.
   */
  adoptInitialLayout() {
    if (Services.prefs.getIntPref(PREF_ADOPTION_VERSION, 0) >= 1) {
      return "already";
    }
    if (hasExistingProfileState()) {
      setAdoptionMarkers(false);
      setShellStart(false);
      return "existing";
    }
    setShellStart(true);
    if (adoptionUnavailable()) {
      setAdoptionMarkers(false);
      return "unavailable";
    }
    const nonInteractive = Boolean(Services.prefs.getStringPref("nulavio.ai.workspace", ""))
      || Services.prefs.getBoolPref("nulavio.profile.temporary", false);
    setAdoptionMarkers(!nonInteractive);
    scheduleInitialLateralCommit();
    return "adopted";
  },

  /**
   * UX3G N-4: whether the session's first window may open on the Shell's new tab. Decided with
   * the layout adoption (the same new-profile rule); a profile from an earlier build, or one
   * adopted before this flag existed, keeps about:home.
   */
  startsOnShellTab() {
    this.adoptInitialLayout();
    return Services.prefs.getBoolPref(PREF_SHELL_START, false);
  },

  dismissChoice() {
    if (Services.prefs.prefIsLocked(PREF_CHOICE_PENDING)) {
      fail("layout-locked");
    }
    Services.prefs.setBoolPref(PREF_CHOICE_PENDING, false);
  },

  async state(target) {
    const win = windowOf(target);
    const sidebar = await ready(win);
    const vertical = Services.prefs.getBoolPref("sidebar.verticalTabs");
    const visibility = Services.prefs.getStringPref("sidebar.visibility");
    const ui = sidebar.getUIState();
    const hover = win.document.documentElement.hasAttribute("sidebar-expand-on-hover");
    const available = Services.prefs.getBoolPref("sidebar.revamp") && !!ui;
    const locked = SIDEBAR_PREFS.some(pref => Services.prefs.prefIsLocked(pref));
    let preset = "custom";
    // Use both the native configuration and actual window state. Temporary
    // hover expansion is Foco; explicitly pinning it open disables hover.
    if (available && win.gBrowser.tabContainer.verticalMode === vertical) {
      if (!vertical && visibility === PRESETS.top) {
        preset = "top";
      } else if (vertical && ui.launcherVisible && visibility === PRESETS.lateral && ui.launcherExpanded && !hover) {
        preset = "lateral";
      } else if (vertical && ui.launcherVisible && visibility === PRESETS.focus && (hover || ui.launcherExpanded)) {
        // QA M-3: the sidebar button is Foco's keyboard route (its hint says so). Natively it
        // pins the launcher open and pauses hover until pressed again; that is still Foco.
        preset = "focus";
      }
    }
    const nonInteractive = lazy.PrivateBrowsingUtils.isWindowPrivate(win)
      || Boolean(Services.prefs.getStringPref("nulavio.ai.workspace", ""))
      || Services.prefs.getBoolPref("nulavio.profile.temporary", false);
    // QA B-3: a marker pinned by the administrator (autoconfig) is not a choice the person can
    // close, so it never shows the one-time card.
    const choicePending = available && !locked && !nonInteractive
      && !Services.prefs.prefIsLocked(PREF_CHOICE_PENDING)
      && Services.prefs.getBoolPref(PREF_CHOICE_PENDING, false);
    return { preset, available, locked, choicePending };
  },

  /**
   * UX6 (D-UX23): the Foco key and quick action. In Foco it returns to the preset it came from
   * (Lateral when unknown); otherwise it remembers Lateral or Abas no topo and applies Foco.
   * `say(key)` announces the outcome in the window (on, off, or why nothing changed).
   */
  async toggleFocus(target, say = () => {}) {
    try {
      const { preset } = await this.state(target);
      if (preset === "focus") {
        const back = Services.prefs.getStringPref(PREF_BEFORE_FOCUS, "lateral") === "top" ? "top" : "lateral";
        const state = await this.apply(target, back);
        say("layoutFocusOff");
        return state;
      }
      if ((preset === "lateral" || preset === "top") && !Services.prefs.prefIsLocked(PREF_BEFORE_FOCUS)) {
        Services.prefs.setStringPref(PREF_BEFORE_FOCUS, preset);
      }
      const state = await this.apply(target, "focus");
      say("layoutFocusOn");
      return state;
    } catch (e) {
      say(e?.code === "layout-locked" ? "layoutLocked" : "layoutUnavailable");
      throw e;
    }
  },

  apply(target, preset) {
    // Serialize explicit choices across Settings/Newtab tabs and windows, including the
    // async native hover measurement. Neither a rejection nor a step that never settles
    // (a window closing mid-transition, QA A-1) may hold the queue: every window step is
    // bounded and cancelled when its window unloads, and the whole apply has a deadline
    // after which it stops before writing anything.
    const pending = applying.then(() => new Promise((resolve, reject) => {
      const ticket = { cancelled: false };
      const timer = startTimer(APPLY_DEADLINE_MS, () => {
        ticket.cancelled = true;
        console.error("Nulavio layout transition did not settle in time");
        reject(layoutError("layout-failed"));
      });
      applyPreset(target, preset, ticket).then(resolve, reject).finally(() => timer.cancel());
    }));
    applying = pending.catch(() => {});
    return pending;
  },

  subscribe(target, listener) {
    const initial = resolveTarget(target);
    if (!initial) {
      fail("layout-unavailable");
    }
    const browserTarget = isWindowObject(initial) ? null : initial;
    const initialWin = windowOf(initial);
    if (!browserTarget) {
      controller(initialWin);
    }
    let active = true;
    let currentBrowser = browserTarget;
    let currentWin = null;
    let observer = null;
    let cancelPendingSwap = null;
    const changed = () => {
      if (active) listener();
    };
    const onWindowUnload = () => {
      unsubscribe();
    };
    const detachWindow = () => {
      if (observer) {
        observer.disconnect();
        observer = null;
      }
      if (currentWin) {
        currentWin.removeEventListener("unload", onWindowUnload);
        currentWin = null;
      }
    };
    const attachWindow = win => {
      controller(win);
      currentWin = win;
      observer = new win.MutationObserver(changed);
      observer.observe(win.document.documentElement, { attributes: true, attributeFilter: ["sidebar-expand-on-hover"] });
      observer.observe(win.document.getElementById("sidebar-container"), {
        attributes: true, attributeFilter: ["hidden", "sidebar-launcher-expanded"],
      });
      observer.observe(win.gBrowser.tabContainer, { attributes: true, attributeFilter: ["orient", "expanded"] });
      win.addEventListener("unload", onWindowUnload, { once: true });
    };
    const onSwapDocShells = event => {
      if (!active || !currentBrowser) return;
      const swappingFrom = currentBrowser;
      const nextBrowser = event.detail;
      swappingFrom.removeEventListener("SwapDocShells", onSwapDocShells);
      detachWindow();
      const onEndSwap = () => {
        cancelPendingSwap = null;
        if (!active) return;
        currentBrowser = nextBrowser;
        if (currentBrowser) {
          currentBrowser.addEventListener("SwapDocShells", onSwapDocShells);
          try {
            attachWindow(windowOf(currentBrowser));
          } catch {
            // Host window is a popup or closing; state() reports unavailable.
          }
        }
        changed();
      };
      cancelPendingSwap = () => swappingFrom.removeEventListener("EndSwapDocShells", onEndSwap);
      swappingFrom.addEventListener("EndSwapDocShells", onEndSwap, { once: true });
    };
    function unsubscribe() {
      if (!active) return;
      active = false;
      if (cancelPendingSwap) {
        cancelPendingSwap();
        cancelPendingSwap = null;
      }
      if (currentBrowser) {
        currentBrowser.removeEventListener("SwapDocShells", onSwapDocShells);
        currentBrowser = null;
      }
      detachWindow();
      for (const pref of OBSERVED_PREFS) Services.prefs.removeObserver(pref, changed);
    }
    if (currentBrowser) {
      currentBrowser.addEventListener("SwapDocShells", onSwapDocShells);
      try {
        attachWindow(initialWin);
      } catch {
        // Chromeless/popup or closing host window; keep pref and swap listeners alive.
      }
    } else {
      attachWindow(initialWin);
    }
    for (const pref of OBSERVED_PREFS) Services.prefs.addObserver(pref, changed);
    return unsubscribe;
  },
};
