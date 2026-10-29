/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

this.nulavioLayout = class extends ExtensionAPI {
  getAPI(context) {
    const layout = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout;
    // Same caller-window resolution as the assistant API; never "most recent
    // window", which can select a different/private window or another tab.
    const windowOf = () => {
      const browser = context.xulBrowser;
      const global = browser?.documentGlobal ?? browser?.ownerGlobal;
      return global?.browsingContext?.topChromeWindow ?? null;
    };
    const call = fn => async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        if (e?.code) throw new ExtensionUtils.ExtensionError(e.code);
        console.error(e);
        throw new ExtensionUtils.ExtensionError("layout-failed");
      }
    };
    return {
      nulavioLayout: {
        state: call(() => layout.state(windowOf())),
        apply: call(preset => layout.apply(windowOf(), preset)),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioLayout.onChanged",
          register: fire => layout.subscribe(windowOf(), () => fire.async()),
        }).api(),
      },
    };
  }
};
