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
    try {
      ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLoadLine.sys.mjs").NulavioLoadLine.watch();
    } catch (e) {
      console.error("Nulavio load line", e); // the tab's own throbber still says a page is loading
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
        // D-UX23: from the Foco key (background page): the tab the key was pressed in, never
        // "most recent window"; the outcome is announced in that window.
        toggleFocus: call(tabId => {
          const win = context.extension.tabManager.get(tabId).window;
          const say = key => win.A11yUtils?.announce({ raw: context.extension.localizeMessage(key) }).catch(() => {});
          return layout.toggleFocus(win, say);
        }),
        // #157, #469: Ctrl+Alt+C, from the background page, in the tab the key was pressed in.
        copyLinkToHighlight: call(tabId => {
          // A tab being moved to another window has no wrapper for that moment: nothing to copy from.
          const tab = context.extension.tabManager.get(tabId);
          if (!tab) {
            return false;
          }
          const say = key => tab.window?.A11yUtils?.announce({ raw: context.extension.localizeMessage(key) }).catch(() => {});
          return layout.copyLinkToHighlight(tab.nativeTab?.linkedBrowser ?? null, say);
        }),
        // #321: Ctrl+Alt+P, the address bar of the window the key was pressed in, in the engine's actions mode.
        openActions: call(tabId => layout.openActions(context.extension.tabManager.get(tabId)?.window ?? null)),
        // From Settings (a page) or from the key (the background page, with the tab it was pressed in).
        setImmersive: call((on, tabId) => {
          const win = tabId === null || tabId === undefined ? null : context.extension.tabManager.get(tabId).window;
          const say = key => win?.A11yUtils?.announce({ raw: context.extension.localizeMessage(key) }).catch(() => {});
          return layout.setImmersive(on ?? !layout.immersive().on, say);
        }),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioLayout.onChanged",
          register: fire => layout.subscribe(browserOf, () => fire.async()),
        }).api(),
      },
    };
  }
};
