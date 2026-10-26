/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Nulavio's command-line handler. Registered at build time (components.conf)
   under "l-nulavio-routing", so it runs before the browser's own handler
   ("m-browser") both at start-up and for links that arrive through the
   remote service: Smart Profile Routing decides where a link opens before
   any request is made for it. The logic lives in the Nulavio Shell
   (modules/NulavioRouting.sys.mjs); this file only hands the command line over. */

export class NulavioCommandLineHandler {
  QueryInterface = ChromeUtils.generateQI(["nsICommandLineHandler"]);

  helpInfo = "";

  handle(cmdLine) {
    let routing;
    try {
      routing = ChromeUtils.importESModule(
        "resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs"
      ).NulavioRouting;
    } catch (e) {
      console.error("Nulavio: Smart Profile Routing is unavailable", e);
      return;
    }
    routing.handleCommandLine(cmdLine);
  }
}
