/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioConnect.sys.mjs so it can be
   tested directly. Errors cross to the page as their stable code only. */

this.nulavioConnect = class extends ExtensionAPI {
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioConnect.sys.mjs").NulavioConnect;
  }

  getAPI() {
    const connect = this.module();
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
      nulavioConnect: {
        discover: call(() => connect.discover()),
        defaultBrowserState: call(() => connect.defaultBrowserState()),
        setDefaultBrowser: call(() => connect.setDefaultBrowser()),
        restoreDefaultBrowser: call(() => connect.restoreDefaultBrowser()),
        kdeDevices: call(() => connect.kdeDevices()),
        sendLink: call((url, device) => connect.sendLink(url, device)),
        setKrunner: call(enabled => connect.setKrunner(enabled)),
      },
    };
  }
};
