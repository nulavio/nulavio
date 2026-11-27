/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioPasswords.sys.mjs. Errors cross
   to the page as their stable code only. */

this.nulavioPasswords = class extends ExtensionAPI {
  // Experiment scripts share one scope: no top-level declarations here.
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs").NulavioPasswords;
  }

  onStartup() {
    // The profile password typed on Nulavio's own pages is never offered to the engine's password manager.
    try {
      this.module().excludeShellPages(this.extension.baseURI.prePath);
    } catch (e) {
      console.error("Nulavio pages and the password manager", e);
    }
    // Flow D: the engine's own window-actor system, not a content script in pages.
    try {
      this.module().registerLookalikeCheck();
    } catch (e) {
      console.error("Nulavio look-alike check", e);
    }
  }

  getAPI(context) {
    const passwords = this.module();
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
    // Whether the calling page is in a private window, as the engine says (its browsing context, or the context's
    // own flag): either one is enough, so a private window's choice is never written to the profile.
    const inPrivate = () => Boolean(context.browsingContext?.usePrivateBrowsing || context.incognito);
    return {
      nulavioPasswords: {
        state: call(() => passwords.state()),
        choose: call(key => passwords.choose(key)),
        check: call(url => passwords.checkLogin(url, { inPrivate: inPrivate() })),
        dismiss: call((url, site, similar, back) =>
          passwords.dismissFor(url, {
            site,
            similar,
            back: Boolean(back),
            browser: context.xulBrowser,
            inPrivate: inPrivate(),
          })
        ),
        canGoBack: call(() => passwords.canGoBack(context.xulBrowser)),
      },
    };
  }
};
