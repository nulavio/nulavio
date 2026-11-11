/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* One settings page (ADR 0008): Nulavio's options live inside the engine's own
   about:preferences, as native panes and groups, instead of a second page.

   No engine patch: when a preferences document is created, this module imports
   settings/native/panes.mjs into that document's own global (the page's own module
   loader, a fixed resource:// address), before the page builds its panes. That module
   uses the engine's pane registry (SettingPaneManager, SettingGroupManager, Preferences)
   exactly as the engine's own panes do.

   Only a system-principal about:preferences (or its alias about:settings) is ever
   touched; web content and extension pages never match. If the module fails, the
   page stays the engine's stock page: panes.mjs checks the registry's shape before it
   changes anything and undoes its own part when a step throws.

   This module is also the one place that knows where a Nulavio section lives in that
   page (SECTIONS), so every "Configurações" entry of the Shell opens the same page. */

const MODULE = "resource://builtin-addons/nulavio-shell/settings/native/panes.mjs";
const L10N = "resource://builtin-addons/nulavio-shell/l10n/{locale}/";
const TOPIC = "chrome-document-global-created";
const PAGES = new Set(["preferences", "settings"]);
const SHELL = "shell@nulavio.net";

/* The panes an entry point may ask for, by their address in about:preferences. "" is the page's
   own first pane. The names starting with "nulavio" are registered by panes.mjs. */
export const PANES = Object.freeze([
  "",
  "appearance",
  "nulavioProfiles",
  "privacy",
  "passwordsAutofill",
  "search",
  "nulavioAssistant",
  "tabsBrowsing",
  "nulavioIntegrations",
]);
/* Where each section of the Shell's own page (settings/settings.html#<section>) is found in the one
   page. A section that moved keeps no entry in the old page's navigation; the others are detail
   pages reached from their pane, and go back to it. */
export const SECTIONS = Object.freeze({
  layout: "appearance",
  appearance: "appearance",
  shortcuts: "tabsBrowsing",
  search: "search",
  passwords: "passwordsAutofill",
  exceptions: "privacy",
  dns: "privacy",
  profiles: "nulavioProfiles",
  routing: "nulavioProfiles",
  ai: "nulavioAssistant",
  integrations: "nulavioIntegrations",
});

class SettingsHost {
  #started = false;
  #source = null;

  start() {
    if (this.#started) {
      return;
    }
    this.#started = true;
    // The panes' words: Fluent files inside the Shell, in the two languages it ships.
    this.#source = new L10nFileSource("nulavio-shell", "app", ["en-US", "pt-BR"], L10N);
    L10nRegistry.getInstance().registerSources([this.#source]);
    Services.obs.addObserver(this, TOPIC);
  }

  stop() {
    if (!this.#started) {
      return;
    }
    this.#started = false;
    Services.obs.removeObserver(this, TOPIC);
    L10nRegistry.getInstance().removeSources(["nulavio-shell"]);
    this.#source = null;
  }

  /**
   * Open the settings page at `pane` in `win`. With `browser` (the tab that asked, when it is the
   * one in front) the page replaces what that tab shows, so "back" from a detail page does not
   * leave a second tab behind; otherwise the settings tab of this window is found or opened (the
   * calling window, never "the most recent one").
   */
  open(win, pane = "", browser = null) {
    if (!win || win.closed || typeof win.switchToTabHavingURI !== "function" || !PANES.includes(pane)) {
      throw Object.assign(new Error("no-window"), { code: "no-window" });
    }
    const url = `about:preferences${pane ? `#${pane}` : ""}`;
    if (browser && win.gBrowser?.selectedBrowser === browser) {
      win.openTrustedLinkIn(url, "current");
      return;
    }
    win.switchToTabHavingURI(url, true, {
      ignoreFragment: "whenComparingAndReplace",
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
    });
  }

  /** As open(), for a caller that names a pane or one of the old page's sections ("layout", "dns"…). */
  openFor(win, where = "", browser = null) {
    const pane = Object.hasOwn(SECTIONS, where) ? SECTIONS[where] : where;
    if (!PANES.includes(pane)) {
      throw Object.assign(new Error("invalid-section"), { code: "invalid-section" });
    }
    this.open(win, pane, browser);
  }

  /** The address of a detail page of the Shell (a section not yet drawn by the settings page itself). */
  detail(section) {
    if (!Object.hasOwn(SECTIONS, section)) {
      throw Object.assign(new Error("invalid-section"), { code: "invalid-section" });
    }
    return WebExtensionPolicy.getByID(SHELL)?.getURL(`settings/settings.html#${section}`) ?? null;
  }

  observe(win) {
    let uri;
    try {
      uri = win.document.documentURIObject;
    } catch {
      return;
    }
    if (!uri?.schemeIs("about") || !PAGES.has(uri.filePath) || !win.document.nodePrincipal.isSystemPrincipal) {
      return;
    }
    // Registered before the page's own DOMContentLoaded listener (its scripts have not run yet),
    // so the panes exist when the page reads the address and opens its first pane.
    win.document.addEventListener("DOMContentLoaded", () => this.#extend(win), { once: true });
  }

  #extend(win) {
    try {
      // The window's own ChromeUtils: "current" is then the page's global, so the module gets the page's
      // registry instances, the ones its panes are read from.
      win.ChromeUtils.importESModule(MODULE, { global: "current" });
    } catch (e) {
      console.error("Nulavio settings: the engine's page is shown as it is", e);
    }
  }
}

export const NulavioSettings = new SettingsHost();
