/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow D, in the parent: the document's address comes from the engine (never from the page).
   If the site imitates one with a saved login, its tab shows Nulavio's warning page first.

   The check can wait (the first read of the saved logins in a session). When it ends, the warning
   opens only if this document is still the one its tab shows, and still on the origin that was
   checked. A change of address inside the document (history.replaceState, a new fragment) keeps the
   origin, so it does not cancel the warning; a document the tab has left (another page, or this one
   kept in the back-forward cache) is never replaced. The answer to the child says whether a
   decision was made for this document: false when it was not, so the child asks again. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioPasswords: "resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs",
});

export class NulavioLookalikeParent extends JSWindowActorParent {
  async receiveMessage(message) {
    if (message.name !== "PasswordFieldFocused" || this.browsingContext.parent) {
      return true;
    }
    const checked = this.manager.documentURI;
    const url = checked?.spec;
    const verdict = url ? await lazy.NulavioPasswords.checkLogin(url) : { suspicious: false };
    if (!verdict.suspicious) {
      return true;
    }
    // After the wait. `this.manager` is null once this document's actor is gone, and
    // `this.browsingContext` would then throw: read the manager first.
    if (!this.manager?.isCurrentGlobal) {
      return false;
    }
    const browser = this.browsingContext.embedderElement;
    if (!browser || browser.browsingContext !== this.browsingContext || this.manager.documentURI?.prePath !== checked.prePath) {
      return false;
    }
    const shell = WebExtensionPolicy.getByID("shell@nulavio.net");
    if (!shell) {
      return true;
    }
    const query = new URLSearchParams({ url, site: verdict.site, similar: verdict.similar });
    browser.loadURI(Services.io.newURI(shell.getURL(`passwords/lookalike.html?${query}`)), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
    });
    return true;
  }
}
