/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* "Editar o texto da página" (#161), in the page's process: the top document of the tab becomes editable
   (document.designMode), or stops being. Frames are documents of their own and are left as they are, from
   any site. Nothing of the page is read or sent: the answer is only whether the document is now editable.

   A document that leaves (another page, a reload, the tab closing) stops being editable first, so a page
   brought back from the engine's cache is never editable without the marker the parent shows. */

export class NulavioPageEditChild extends JSWindowActorChild {
  receiveMessage(message) {
    if (message.name !== "Set" || this.browsingContext?.top !== this.browsingContext) {
      return false;
    }
    const doc = this.document;
    doc.designMode = message.data?.on === true ? "on" : "off";
    return doc.designMode === "on";
  }

  handleEvent(event) {
    if (event.type === "pagehide" && event.target === this.document && this.document.designMode === "on") {
      this.document.designMode = "off";
    }
  }
}
