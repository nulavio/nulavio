/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioWhatsNew.sys.mjs. Errors cross
   to the page as their stable code only. */

this.nulavioWhatsNew = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioWhatsNew.sys.mjs").NulavioWhatsNew;
  }

  /* With the browser, independent of the background page: the Help menu entry, and the bar after an update. */
  onStartup() {
    // Never let a failure here stop the Shell from starting.
    try {
      const extension = this.extension;
      this.module().atStartup({
        bar: version => extension.localizeMessage("whatsNewBar", [String(version)]),
        barFrom: (from, version) => extension.localizeMessage("whatsNewBarFrom", [String(from), String(version)]),
        button: extension.localizeMessage("whatsNewButton"),
        menu: extension.localizeMessage("whatsNewMenu"),
      });
    } catch (e) {
      console.error("Nulavio what's new", e);
    }
  }

  getAPI() {
    const NulavioWhatsNew = this.module();
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
      nulavioWhatsNew: {
        notes: call(language => NulavioWhatsNew.notes(language)),
        setting: call(() => NulavioWhatsNew.setting()),
        setNotice: call(on => NulavioWhatsNew.setNotice(on)),
      },
    };
  }
};
