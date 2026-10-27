/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioVault.sys.mjs so it can be
   tested directly. Errors cross to the page as their stable code only. */

this.nulavioVault = class extends ExtensionAPI {
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs").NulavioVault;
  }

  getAPI() {
    const vault = this.module();
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
      nulavioVault: {
        capabilities: call(() => vault.capabilities()),
        status: call(id => vault.status(id)),
        unlock: call((id, method, secret, url) => vault.unlock(id, method, secret ?? null, url ?? null)),
        lock: call(id => vault.lock(id)),
        createProtected: call(details => vault.createProtected(details)),
        change: call((id, op, details) => vault.change(id, op, details)),
        openUnlockPage: call((id, url) => vault.openUnlockPage(id, url ?? null, "selector")),
        phoneStart: call((id, kind, details) => vault.phoneStart(id, kind, { current: details?.current ?? null })),
        phoneSession: call((session, action, match) => vault.phoneSession(session, action, match ?? false)),
        phoneOpen: call((id, url) => vault.phoneOpen(id, url ?? null)),
        openPhonePage: call(id => vault.openPhonePage(id)),
      },
    };
  }
};
