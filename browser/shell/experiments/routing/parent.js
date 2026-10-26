/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioRouting.sys.mjs (and the
   pure decisions in modules/NulavioRouter.sys.mjs) so it can be tested
   directly. Errors cross to the page as their stable code only. */

this.nulavioRouting = class extends ExtensionAPI {
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs").NulavioRouting;
  }

  getAPI(context) {
    const routing = this.module();
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
      nulavioRouting: {
        state: call(() => routing.state()),
        setEnabled: call(enabled => routing.setEnabled(enabled)),
        addRule: call(rule => routing.addRule(rule)),
        removeRule: call(id => routing.removeRule(id)),
        setRuleAction: call((id, action) => routing.setRuleAction(id, action)),
        ruleFor: call(url => routing.ruleFor(url)),
        openIn: call((profileId, url) => routing.openIn(profileId, url)),
        onChanged: new ExtensionCommon.EventManager({
          context,
          name: "nulavioRouting.onChanged",
          register: fire => routing.subscribe(() => fire.async()),
        }).api(),
      },
    };
  }
};
