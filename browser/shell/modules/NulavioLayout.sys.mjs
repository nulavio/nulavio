/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Gecko159 owns tab orientation, hover, sizing and session persistence.
   No startup defaults/migration and no shadow "selected preset" preference.
   The only writable profile prefs are the two literal names in apply(). */

const PRESETS = Object.freeze({ lateral: "always-show", top: "hide-on-close", focus: "expand-on-hover" });
const OBSERVED_PREFS = ["sidebar.verticalTabs", "sidebar.visibility", "sidebar.revamp"];
let applying = Promise.resolve();

function fail(code) {
  const error = new Error(code);
  error.code = code;
  throw error;
}

function controller(win) {
  if (!win || win.closed || win.document.documentElement.getAttribute("windowtype") !== "navigator:browser"
      || !win.toolbar.visible || !win.SidebarController || win.SidebarController.uninitializing) {
    fail("layout-unavailable");
  }
  return win.SidebarController;
}

async function ready(win) {
  const sidebar = controller(win);
  await sidebar.promiseInitialized;
  controller(win);
  await sidebar.waitUntilStable();
  return sidebar;
}

export const NulavioLayout = {
  async state(win) {
    const sidebar = await ready(win);
    const vertical = Services.prefs.getBoolPref("sidebar.verticalTabs");
    const visibility = Services.prefs.getStringPref("sidebar.visibility");
    const ui = sidebar.getUIState();
    const hover = win.document.documentElement.hasAttribute("sidebar-expand-on-hover");
    const available = Services.prefs.getBoolPref("sidebar.revamp") && !!ui;
    const locked = OBSERVED_PREFS.some(pref => Services.prefs.prefIsLocked(pref));
    let preset = "custom";
    // Use both the native configuration and actual window state. Temporary
    // hover expansion is Foco; explicitly pinning it open disables hover.
    if (available && win.gBrowser.tabContainer.verticalMode === vertical) {
      if (!vertical && visibility === PRESETS.top) {
        preset = "top";
      } else if (vertical && ui.launcherVisible && visibility === PRESETS.lateral && ui.launcherExpanded && !hover) {
        preset = "lateral";
      } else if (vertical && ui.launcherVisible && visibility === PRESETS.focus && hover) {
        preset = "focus";
      }
    }
    return { preset, available, locked };
  },

  apply(win, preset) {
    // Serialize explicit choices across Settings tabs/windows, including the
    // async native hover measurement. A rejection must not poison the queue.
    const pending = applying.then(async () => {
      if (typeof preset !== "string" || !Object.hasOwn(PRESETS, preset)) {
        fail("layout-invalid");
      }
      await ready(win);
      if (!Services.prefs.getBoolPref("sidebar.revamp")) {
        fail("layout-unavailable");
      }
      if (OBSERVED_PREFS.some(pref => Services.prefs.prefIsLocked(pref))) {
        fail("layout-locked");
      }
      const windows = [...Services.wm.getEnumerator("navigator:browser")]
        .filter(w => !w.closed && w.toolbar.visible && !w.SidebarController?.uninitializing);
      await Promise.all(windows.map(ready));
      controller(win);
      if (!Services.prefs.getBoolPref("sidebar.revamp")) fail("layout-unavailable");
      if (OBSERVED_PREFS.some(pref => Services.prefs.prefIsLocked(pref))) fail("layout-locked");
      // Orientation first: SidebarManager normalizes visibility synchronously.
      // The final explicit visibility then wins, including re-selecting a
      // preset whose prefs already match but whose window was collapsed.
      try {
        Services.prefs.setBoolPref("sidebar.verticalTabs", preset !== "top");
        Services.prefs.setStringPref("sidebar.visibility", PRESETS[preset]);
        await Promise.all(windows.map(async w => {
          const sidebar = controller(w);
          await sidebar.waitUntilStable();
          // updateVisibility affects only launcher expansion/visibility, keeping
          // open panels, widths, position, tools and tab/group data intact.
          sidebar._state.updateVisibility(true, preset === "lateral");
          await sidebar.toggleExpandOnHover(preset === "focus");
          await sidebar.waitUntilStable();
        }));
        return await this.state(win);
      } catch (e) {
        // After a native write (e.g. a window closing mid-transition), changes
        // may already exist. Never promise a rollback or "nothing changed".
        console.error("Nulavio layout transition", e);
        fail("layout-failed");
      }
    });
    applying = pending.catch(() => {});
    return pending;
  },

  subscribe(win, listener) {
    controller(win);
    let active = true;
    const changed = () => { if (active) listener(); };
    const observer = new win.MutationObserver(changed);
    observer.observe(win.document.documentElement, { attributes: true, attributeFilter: ["sidebar-expand-on-hover"] });
    observer.observe(win.document.getElementById("sidebar-container"), {
      attributes: true, attributeFilter: ["hidden", "sidebar-launcher-expanded"],
    });
    observer.observe(win.gBrowser.tabContainer, { attributes: true, attributeFilter: ["orient", "expanded"] });
    for (const pref of OBSERVED_PREFS) Services.prefs.addObserver(pref, changed);
    const unsubscribe = () => {
      if (!active) return;
      active = false;
      observer.disconnect();
      for (const pref of OBSERVED_PREFS) Services.prefs.removeObserver(pref, changed);
      win.removeEventListener("unload", unsubscribe);
    };
    win.addEventListener("unload", unsubscribe, { once: true });
    return unsubscribe;
  },
};
