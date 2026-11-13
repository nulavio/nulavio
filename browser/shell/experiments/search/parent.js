/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioSearch.sys.mjs so it can be
   tested directly. Errors cross to the page as their stable code only. */

this.nulavioSearch = class extends ExtensionAPI {
  module() {
    // The built-in add-on's files are also served from resource://, the only
    // scheme (with chrome:) the engine accepts for privileged modules.
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSearch.sys.mjs").NulavioSearch;
  }

  onStartup() {
    // This always-on Shell lifecycle also installs the scoped native-window sheet;
    // it exposes no additional API to extension pages or web content.
    ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWindow.sys.mjs").NulavioWindow.start();
    // One settings page (ADR 0008): Nulavio's panes inside the engine's about:preferences.
    try {
      ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings.start();
    } catch (e) {
      console.error("Nulavio settings start-up failed", e);
    }
    // After first paint, like the engine's own search add-ons, so start-up is not slowed.
    const { ExtensionParent } = ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");
    ExtensionParent.browserPaintedPromise
      .then(() => this.module().startup())
      .catch(e => console.error("Nulavio Search start-up failed", e));
  }

  onShutdown(isAppShutdown) {
    if (!isAppShutdown) {
      ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWindow.sys.mjs").NulavioWindow.stop();
      ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings.stop();
    }
  }

  getAPI(context) {
    const search = this.module();
    const call = fn => async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        if (e?.code) {
          throw new ExtensionUtils.ExtensionError(e.code);
        }
        console.error(e);
        throw new ExtensionUtils.ExtensionError("unexpected");
      }
    };
    return {
      nulavioSearch: {
        state: call(() => search.state()),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioSearch.onChanged",
          register: fire => search.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
