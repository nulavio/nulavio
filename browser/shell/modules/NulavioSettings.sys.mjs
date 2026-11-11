/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* One settings page (ADR 0008): Nulavio's options live inside the engine's own
   about:preferences, as native panes and groups, instead of a second page.

   No engine patch: when a preferences document is created, this module runs
   settings/native/panes.js in that document's own global, before the page builds
   its panes. That script uses the engine's public pane registry (SettingPaneManager,
   SettingGroupManager, Preferences) exactly as the engine's own panes do.

   Only a system-principal about:preferences (or its alias about:settings) is ever
   touched; web content and extension pages never match. If the script fails, the
   page stays the engine's stock page: nothing of it is removed before ours is in. */

const PANES = "resource://builtin-addons/nulavio-shell/settings/native/panes.js";
const L10N = "resource://builtin-addons/nulavio-shell/l10n/{locale}/";
const TOPIC = "chrome-document-global-created";
const PAGES = new Set(["preferences", "settings"]);

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
      Services.scriptloader.loadSubScript(PANES, win);
    } catch (e) {
      console.error("Nulavio settings: the engine's page is shown as it is", e);
    }
  }
}

export const NulavioSettings = new SettingsHost();
