/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

this.nulavioServices = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioServices.sys.mjs").NulavioServices;
  }

  getAPI(context) {
    const services = this.module();
    const call = fn => async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        if (e?.code) {
          throw new ExtensionUtils.ExtensionError(e.code);
        }
        console.error(e);
        throw new ExtensionUtils.ExtensionError("services-failed");
      }
    };
    // The tab the menu was opened in, never "the most recent window"; whether it is private is read here.
    const wrapperOf = tabId => {
      try {
        return context.extension.tabManager.get(tabId);
      } catch {
        return null; // a tab that is gone
      }
    };
    const tabOf = tabId => wrapperOf(tabId)?.nativeTab ?? null;
    // The page's address as the tab has it: the menu's own data has none for a page the Shell holds no host
    // permission for, and a page's address is the engine's to say, not the caller's.
    const pageOf = tab => tab?.linkedBrowser?.currentURI?.spec ?? "";
    return {
      nulavioServices: {
        menu: call(() => services.menu()),
        check: call((itemId, _target, tabId) => {
          const tab = tabOf(tabId);
          return services.check(itemId, { target: pageOf(tab), isPrivate: !tab || services.isPrivate(tab.linkedBrowser) });
        }),
        open: call(async (itemId, clicked, tabId) => {
          const tab = tabOf(tabId);
          if (!tab) {
            return { done: false };
          }
          const isPrivate = services.isPrivate(tab.linkedBrowser);
          const built = services.build(itemId, { text: clicked.text ?? "", target: pageOf(tab), isPrivate });
          const win = wrapperOf(tabId)?.window; // the tab's own window (a XUL tab's ownerGlobal is not reachable here)
          if (!win) {
            return { done: false };
          }
          // A new tab next to this one, in the same window, so a private window's service opens privately.
          win.openTrustedLinkIn(built.open, "tab", { relatedToCurrent: true, inBackground: false });
          return { done: true };
        }),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioServices.onChanged",
          register: fire => services.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
