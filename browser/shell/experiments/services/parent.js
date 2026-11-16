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
    const tabOf = tabId => context.extension.tabManager.get(tabId)?.nativeTab ?? null;
    return {
      nulavioServices: {
        menu: call(() => services.menu()),
        check: call((itemId, target, tabId) => {
          const tab = tabOf(tabId);
          return services.check(itemId, { target, isPrivate: !tab || services.isPrivate(tab.linkedBrowser) });
        }),
        open: call(async (itemId, clicked, tabId) => {
          const tab = tabOf(tabId);
          if (!tab) {
            return { done: false };
          }
          const isPrivate = services.isPrivate(tab.linkedBrowser);
          const built = services.build(itemId, { text: clicked.text ?? "", target: clicked.target ?? "", isPrivate });
          const win = tab.ownerGlobal;
          if (built.assistant) {
            // The page goes into the assistant's panel as an item, with the question written: nothing is sent
            // until Send, and only to the agent the person connected (ADR 0007).
            const { NulavioAI } = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs");
            await NulavioAI.assistantOffer({ kind: "page" }, tabId);
            await NulavioAI.assistantOffer({ kind: "draft", text: context.extension.localizeMessage("summaryAssistantDraft") }, tabId);
            return { done: true };
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
