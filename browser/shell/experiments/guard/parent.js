/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioGuard.sys.mjs. Errors cross
   to the page as their stable code only. */

this.nulavioGuard = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard;
  }

  /* Runs when the Shell starts with the browser, independent of its background page
     (an event page that may not be running): the check never waits for a page. */
  onStartup() {
    // Never let a Guard failure stop the Shell from starting.
    try {
      const NulavioGuard = this.module();
      const extension = this.extension;
      // What one finding is, in the review page's own titles (guard/review.js): the bar names it when it is the only one.
      const TITLES = {
        "extension-added": f => ["guardExtensionAdded", [f.after.name]],
        "extension-changed": f => ["guardExtensionChanged", [f.after.name]],
        "extension-removed": f => ["guardExtensionRemoved", [f.before.name]],
        "pref-changed": () => ["guardPrefChanged", []],
        "root-added": () => ["guardRootAdded", []],
        "module-added": f => ["guardModuleAdded", [f.key]],
        "host-added": f => ["guardHostAdded", [f.after.name]],
        "host-changed": f => ["guardHostChanged", [f.after.name]],
        "policies-changed": () => ["guardPolicies", []],
        "userjs-added": () => ["guardUserJsAdded", []],
        "userjs-changed": () => ["guardUserJsChanged", []],
        "search-changed": () => ["guardSearchChanged", []],
      };
      const textFor = (count, only) => {
        const named = only && Object.hasOwn(TITLES, only.kind) ? TITLES[only.kind](only) : null;
        return named
          ? extension.localizeMessage("guardBarOne", [extension.localizeMessage(named[0], named[1].map(String))])
          : extension.localizeMessage("guardBar", [String(count)]);
      };
      NulavioGuard.atStartup(textFor, extension.localizeMessage("guardReviewButton"));
    } catch (e) {
      console.error("Nulavio Guard", e);
    }
  }

  getAPI() {
    const NulavioGuard = this.module();
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
      nulavioGuard: {
        check: call(() => NulavioGuard.check()),
        findings: call(async () => (await NulavioGuard.check(), NulavioGuard.findings())),
        resolve: call((id, action) => NulavioGuard.resolve(id, action)),
        reveal: call(async id => (await NulavioGuard.check(), NulavioGuard.reveal(id))),
        hideBar: call(() => NulavioGuard.hideBar()),
      },
    };
  }
};
