/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow D, in the parent: the document's address comes from the engine (never from the page).
   If the site imitates one with a saved login, its tab shows Nulavio's warning page first. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioPasswords: "resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs",
});

export class NulavioLookalikeParent extends JSWindowActorParent {
  async receiveMessage(message) {
    if (message.name !== "PasswordFieldFocused" || this.browsingContext.parent) {
      return;
    }
    const url = this.manager.documentURI?.spec;
    const verdict = url ? await lazy.NulavioPasswords.checkLogin(url) : { suspicious: false };
    const browser = this.browsingContext.top.embedderElement;
    const shell = WebExtensionPolicy.getByID("shell@nulavio.net");
    if (!verdict.suspicious || !browser || !shell || this.manager.documentURI?.spec !== url) {
      return;
    }
    const query = new URLSearchParams({ url, site: verdict.site, similar: verdict.similar });
    browser.loadURI(Services.io.newURI(shell.getURL(`passwords/lookalike.html?${query}`)), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
    });
  }
}
