/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Flow D, in the page's process: tell the parent once per document that a password field got
   focus. Nothing of the page is read: not the field's value, not the form, not the address (the
   parent knows the document's address from the engine). */

export class NulavioLookalikeChild extends JSWindowActorChild {
  #asked = false;

  handleEvent(event) {
    const field = event.target;
    if (this.#asked || event.type !== "focusin" || field?.localName !== "input" || field.type !== "password") {
      return;
    }
    this.#asked = true;
    this.sendAsyncMessage("PasswordFieldFocused");
  }
}
