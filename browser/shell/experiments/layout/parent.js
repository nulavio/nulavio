/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

this.nulavioLayout = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout;
  }

  onStartup() {
    // Before the first window opens; never let a failure stop the Shell from starting.
    try {
      this.module().adoptInitialLayout();
    } catch (e) {
      console.error("Nulavio layout startup", e);
    }
  }

  getAPI(context) {
    const layout = this.module();
    // Resolve the caller tab's live <browser> dynamically across docShell swaps;
    // never "most recent window", which can select a different/private window.
    const browserOf = () => context.xulBrowser;
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
        state: call(() => layout.state(browserOf)),
        apply: call(preset => layout.apply(browserOf, preset)),
        dismissChoice: call(() => layout.dismissChoice()),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioLayout.onChanged",
          register: fire => layout.subscribe(browserOf, () => fire.async()),
        }).api(),
      },
    };
  }
};
