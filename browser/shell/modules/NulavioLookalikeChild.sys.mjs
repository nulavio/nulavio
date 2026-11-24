/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow D, in the page's process: tell the parent once per document that the person is about to use
   a password field. Nothing of the page is read: not the field's value, not the key, not the form,
   not the address (the parent knows the document's address from the engine).

   Only the person's own input counts: the field gets the focus, a click or a key in it, while the
   document has the engine's transient user activation (a click, a tap or a key the person pressed in
   it, a few seconds at most). A focus the page gives itself (script, autofocus) asks nothing; the
   first click or key in that field then does. The engine sends these actors trusted events only;
   isTrusted is checked as well. */

const EVENTS = new Set(["focusin", "mousedown", "keydown"]);

export class NulavioLookalikeChild extends JSWindowActorChild {
  #asked = false;

  handleEvent(event) {
    const field = event.target;
    if (this.#asked || !event.isTrusted || !EVENTS.has(event.type)) {
      return;
    }
    if (field?.localName !== "input" || field.type !== "password") {
      return;
    }
    if (!this.document.hasValidTransientUserGestureActivation) {
      return;
    }
    this.#asked = true;
    // The parent answers false when it could not decide for this document (the tab no longer showed
    // it when the check ended): the next use of a password field asks again. A failed query (the
    // warning replaced the page, or the check itself failed) is not asked again for this document.
    this.sendQuery("PasswordFieldFocused").then(
      decided => {
        if (decided === false) {
          this.#asked = false;
        }
      },
      () => {}
    );
  }
}
