/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioPrivacy.sys.mjs. Errors cross
   to the page as their stable code only. */

this.nulavioPrivacy = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy;
  }

  onStartup() {
    // Before the first page loads; never let a failure stop the Shell from starting.
    try {
      this.module().seedDefaults();
    } catch (e) {
      console.error("Nulavio privacy defaults", e);
    }
  }

  getAPI(context) {
    const NulavioPrivacy = this.module();
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
      nulavioPrivacy: {
        dns: call(() => NulavioPrivacy.dns()),
        setDns: call(details => NulavioPrivacy.setDns(details)),
        dismissDnsChoice: call(() => NulavioPrivacy.dismissDnsChoice()),
        firstRun: call(() => NulavioPrivacy.firstRun()),
        firstRunDone: call(steps => NulavioPrivacy.firstRunDone(steps)),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioPrivacy.onChanged",
          register: fire => NulavioPrivacy.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
