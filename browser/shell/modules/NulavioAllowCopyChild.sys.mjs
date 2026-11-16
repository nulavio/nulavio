/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* "Permitir copiar e colar neste site" (#160), in the page's process. For a document whose own address (its
   origin: scheme, host and port) has the permission, this runs as its window is created, before any of the
   page's scripts, and:
   - adds the first listeners in the capture phase of the window for copy, cut, paste, contextmenu and
     selectstart, which stop the event there, so the page's own handlers never see it and cannot cancel it.
     The browser's own handling (its menu, the clipboard) is not a page handler and still runs;
   - adds a user sheet that makes text selectable again where the page turned selection off.
   Frames are documents of their own and are decided by their own address: a frame from another site is left as
   it is. Nothing is read from the page and no message is sent. */

export const ALLOW_COPY = "nulavio-allow-copy";
export const EVENTS = Object.freeze(["copy", "cut", "paste", "contextmenu", "selectstart"]);
const SELECTABLE = `data:text/css,${encodeURIComponent("*, ::before, ::after { user-select: text !important; }")}`;

function stop(event) {
  event.stopImmediatePropagation();
}

export class NulavioAllowCopyChild extends JSWindowActorChild {
  handleEvent(event) {
    if (event.type !== "DOMWindowCreated") {
      return;
    }
    const win = this.contentWindow;
    const principal = this.document?.nodePrincipal;
    if (!win || !principal?.isContentPrincipal || !(principal.schemeIs("http") || principal.schemeIs("https"))) {
      return;
    }
    let allowed = false;
    try {
      allowed = Services.perms.testExactPermissionFromPrincipal(principal, ALLOW_COPY) === Services.perms.ALLOW_ACTION;
    } catch {
      // No answer from the engine: the page keeps its own rules.
    }
    if (!allowed) {
      return;
    }
    for (const type of EVENTS) {
      win.addEventListener(type, stop, { capture: true });
    }
    try {
      win.windowUtils.loadSheetUsingURIString(SELECTABLE, win.windowUtils.USER_SHEET);
    } catch (e) {
      console.error("Nulavio allow copy", e); // the events are free; selection stays as the page set it
    }
  }
}
