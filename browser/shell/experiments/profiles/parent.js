/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioProfiles.sys.mjs so it can
   be tested directly. Errors cross to the page as their stable code only. */

this.nulavioProfiles = class extends ExtensionAPI {
  module() {
    // The built-in add-on's files are also served from resource://, the only
    // scheme (with chrome:) the engine accepts for privileged modules.
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;
  }

  getAPI(context) {
    const profiles = this.module();
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
      nulavioProfiles: {
        list: call(() => profiles.list()),
        options: call(() => profiles.options()),
        create: call(details => profiles.create(details)),
        update: call((id, details) => profiles.update(id, details)),
        switchTo: call(id => profiles.switchTo(id)),
        remove: call(id => profiles.remove(id)),
        openManager: call(() => profiles.openManager()),
        openCurrentPage: call(page => profiles.openCurrentPage(page)),
        avatarSvg: call((avatar, ink) => profiles.avatarSvg(avatar, ink)),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioProfiles.onChanged",
          register: fire => profiles.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
