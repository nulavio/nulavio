/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

this.nulavioPersonalise = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  getAPI(context) {
    const { NulavioPersonalise } = ChromeUtils.importESModule(
      "resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs"
    );
    const call = fn => async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        if (e?.code) throw new ExtensionUtils.ExtensionError(e.code);
        console.error(e);
        throw new ExtensionUtils.ExtensionError("personalise-failed");
      }
    };
    return {
      nulavioPersonalise: {
        state: call(() => NulavioPersonalise.state()),
        setDensity: call(value => NulavioPersonalise.set("density", value)),
        setAccent: call(value => NulavioPersonalise.set("accent", value)),
        setMoreContrast: call(value => NulavioPersonalise.set("moreContrast", value)),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioPersonalise.onChanged",
          register: fire => NulavioPersonalise.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
