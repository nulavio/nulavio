/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow D, in the parent: the addresses come from the engine (never from the page). If a site of the
   tab's page imitates one with a saved login, the tab shows Nulavio's warning page first.

   The field can be in the tab's page or in any frame of it. The parent checks the field's document,
   then each document around it up to the tab's page: for each, the site the engine gives it (its own
   http or https address, or, for a document without one such as about:blank, about:srcdoc or blob:,
   the http or https site of its principal; an opaque, system, expanded or extension principal gives
   none), once per host. The first one that imitates a saved site decides.

   The check can wait (the first read of the saved logins in a session). When it ends, the warning
   opens only if this document is still current, the tab still shows the page it was part of, and the
   document that was found still has the site that was checked; for a field in a frame, its "continue"
   goes back to the tab's page. A change of address inside a document (history.replaceState, a new
   fragment) keeps the site, so it does not cancel the warning; a page the tab has left (another page,
   or this one kept in the back-forward cache) is never replaced. The
   answer to the child says whether a decision was made for this document: false when it was not, so
   the child asks again. Nothing is decided either while a Primary Password is set and not yet entered:
   the module compares nothing rather than ask for it, and the person's next input in a password field
   asks again. */

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  NulavioPasswords: "resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs",
});

// The tab's browser -> the tab's page for which a warning is being opened, where its history stood, and when: a
// second document of that page that finds a look-alike before that warning is shown does not open another one over
// it, and is told nothing was decided (it asks again on the next input). The entry ends once the warning took its
// entry in the history (the entry after the page changed: the page shown again by Back warns again), the tab shows
// another page, or after OPENING_MS (a load the page's beforeunload kept, or one that was stopped).
const opening = new WeakMap();
const OPENING_MS = 10_000;
const MAX_ENTRIES = "browser.sessionhistory.max_entries";

/** The id of the entry after the one the tab shows, or null. */
function nextEntry(history) {
  try {
    return history && history.index + 1 < history.count ? history.getEntryAtIndex(history.index + 1).ID : null;
  } catch {
    return null;
  }
}

/** Where the tab's history stands, to tell whether the warning opened for `page` is still on its way. */
function historyState(page, history) {
  return { page, index: history?.index, count: history?.count, next: nextEntry(history) };
}

function onItsWay(browser, page, history) {
  const pending = opening.get(browser);
  if (!pending) {
    return false;
  }
  const now = historyState(page, history);
  if (
    Object.entries(now).every(([key, value]) => pending[key] === value) &&
    Date.now() - pending.at < OPENING_MS
  ) {
    return true;
  }
  opening.delete(browser);
  return false;
}

const web = uri => Boolean(uri && (uri.schemeIs("http") || uri.schemeIs("https")));

/** The site's address the engine gives a document (a window global), or null. */
function siteAddress(global) {
  const uri = global?.documentURI;
  if (web(uri)) {
    return uri;
  }
  const principal = global?.documentPrincipal;
  if (principal?.isContentPrincipal && web(principal)) {
    return Services.io.newURI(`${principal.exposablePrePath}/`);
  }
  return null;
}

export class NulavioLookalikeParent extends JSWindowActorParent {
  async receiveMessage(message) {
    if (message.name !== "PasswordFieldFocused") {
      return true;
    }
    const top = this.browsingContext.top;
    const page = top.currentWindowGlobal;
    const fieldInPage = this.manager === page;
    // The field's document first, then each document around it, up to the tab's page; one check per host.
    const sites = [];
    for (let global = this.manager; global; global = global.browsingContext?.parentWindowContext) {
      const address = siteAddress(global);
      if (address && !sites.some(site => site.address.host === address.host)) {
        sites.push({ global, address });
      }
    }
    let found = null;
    let locked = false;
    for (const site of sites) {
      const verdict = await lazy.NulavioPasswords.checkLogin(site.address.spec);
      if (verdict.suspicious) {
        found = site;
        break;
      }
      locked ||= Boolean(verdict.locked);
    }
    if (!found) {
      return !locked;
    }
    // After the wait. `this.manager` is null once this document's actor is gone, and
    // `this.browsingContext` would then throw: read the manager, and use the contexts read before.
    if (!this.manager?.isCurrentGlobal || !found.global.isCurrentGlobal || top.currentWindowGlobal !== page) {
      return false;
    }
    const browser = top.embedderElement;
    if (!browser || browser.browsingContext !== top || siteAddress(found.global)?.prePath !== found.address.prePath) {
      return false;
    }
    const shell = WebExtensionPolicy.getByID("shell@nulavio.net");
    if (!shell) {
      return true;
    }
    const history = top.sessionHistory;
    if (onItsWay(browser, page, history)) {
      return false; // this page's warning is already on its way: not decided for this document
    }
    // Only an address: the page asks the module again which saved site `url` imitates. A field in the tab's
    // page, at a site's address, gives that address as it is. A field in a frame gives only the origin of the
    // site found (a document's path, query and fragment stay out of the tab's address), and a flag without an
    // address (`in=frame`): "continue" goes back to the tab's page in its history, never to an address, and
    // never opens the frame's document as the tab's page.
    const own = fieldInPage && web(page.documentURI);
    const url = own ? found.address.spec : `${found.address.scheme}://${found.address.hostPort}/`;
    const query = new URLSearchParams({ url });
    if (!own) {
      query.set("in", "frame");
    }
    const warning = shell.getURL(`passwords/lookalike.html?${query}`);
    if (!own) {
      // The warning takes the entry after the tab's page (the last one when the history is full): its "continue"
      // goes back from there only (NulavioPasswords.canGoBack).
      // The engine keeps at least the default number of entries, whatever the pref says (nsSHistory::Startup).
      const max = Math.max(
        Services.prefs.getIntPref(MAX_ENTRIES, 50),
        Services.prefs.getDefaultBranch("").getIntPref(MAX_ENTRIES, 50)
      );
      const index = Math.min((history?.index ?? -1) + 1, max - 1);
      lazy.NulavioPasswords.bindWarning(browser, { index, url: warning });
    }
    opening.set(browser, { ...historyState(page, history), at: Date.now() });
    browser.loadURI(Services.io.newURI(warning), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
    });
    return true;
  }
}
