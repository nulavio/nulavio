/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Called by the address bar (patch 0005) before it loads what the user
   typed. Returns true when Smart Profile Routing took the navigation over
   (another profile, or a question first); false means "load it here".
   The logic lives in the Nulavio Shell (modules/NulavioRouting.sys.mjs). */

export const NulavioUrlbarRouting = {
  handle({ url, postData, where, isPrivate }) {
    try {
      const { NulavioRouting } = ChromeUtils.importESModule(
        "resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs"
      );
      return NulavioRouting.routeNavigation({ url, postData, where, isPrivate, source: "typed" });
    } catch (e) {
      console.error("Nulavio: Smart Profile Routing is unavailable", e);
      return false;
    }
  },
};
