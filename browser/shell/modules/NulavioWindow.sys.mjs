/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Window styles live with the built-in Shell. The sheet matches only native
   sidebar documents and steps aside for contrast modes and installed themes. */
const sheets = Cc["@mozilla.org/content/style-sheet-service;1"].getService(Ci.nsIStyleSheetService);
const sidebarFocus = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/sidebar-focus.css");

export const NulavioWindow = {
  start() {
    if (!sheets.sheetRegistered(sidebarFocus, sheets.AGENT_SHEET)) {
      sheets.loadAndRegisterSheet(sidebarFocus, sheets.AGENT_SHEET);
    }
  },

  stop() {
    if (sheets.sheetRegistered(sidebarFocus, sheets.AGENT_SHEET)) {
      sheets.unregisterSheet(sidebarFocus, sheets.AGENT_SHEET);
    }
  },
};
