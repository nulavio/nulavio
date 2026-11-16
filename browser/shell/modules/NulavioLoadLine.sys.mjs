/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* A calm page-loading line along the top of the page (#318).

   One line per window, for the selected tab only, at the top edge of that tab's page (inside its browser
   stack): under the tab's notification bars, the toolbar, the band and the identity, so it never covers any of
   them. It is decorative (aria-hidden): the engine's own busy state for assistive technology is unchanged.

   It follows the engine's own state for the tab's top-level document: shown from the start of its network
   activity, gone at once when the document has loaded, and when a load stops, fails or is aborted (the engine's
   STATE_START and STATE_STOP for that document). The engine's progress amounts for a web page are not reliable
   (measured on 160.0: most loads from a page's process report none, a few report some), so the line is always the
   calm indeterminate state: it never claims how far a load has gone. A background tab never
   shows it.

   Colour: a neutral token (window-band.css), never a status colour or the band's, so it cannot read as a
   security state. Under reduced motion it is a static line: no sliding, no growing. */

const LINE = "nulavio-load-line";
const HTML = "http://www.w3.org/1999/xhtml";
const { STATE_START, STATE_STOP, STATE_IS_NETWORK } = Ci.nsIWebProgressListener;

const windows = new Map(); // window → { line, listener, select, unload }

function lineOf(win) {
  return windows.get(win)?.line ?? null;
}

/** Put the line on top of the selected tab's page, and show the tab's state now. */
function follow(win) {
  const line = lineOf(win);
  const browser = win.gBrowser?.selectedBrowser;
  const stack = browser?.parentNode;
  if (!line || !stack) {
    return;
  }
  if (line.parentNode !== stack) {
    stack.append(line);
  }
  if (browser.webProgress?.isLoadingDocument) {
    show(line);
  } else {
    hide(line);
  }
}

function show(line) {
  line.hidden = false;
  line.dataset.state = "loading";
}

function hide(line) {
  line.hidden = true;
  delete line.dataset.state;
}

function attach(win) {
  if (windows.has(win) || !win.gBrowser || win.closed) {
    return;
  }
  const line = win.document.createElementNS(HTML, "div");
  line.id = LINE;
  line.setAttribute("aria-hidden", "true");
  line.hidden = true;
  // The tabbrowser calls these for the selected tab only.
  const listener = {
    onStateChange(webProgress, _request, flags) {
      if (!webProgress?.isTopLevel || !(flags & STATE_IS_NETWORK)) {
        return;
      }
      if (flags & STATE_START) {
        show(line);
      } else if (flags & STATE_STOP) {
        hide(line); // loaded, stopped, failed or aborted: gone at once
      }
    },
    QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]),
  };
  const select = () => follow(win);
  const unload = () => detach(win);
  windows.set(win, { line, listener, select, unload });
  win.gBrowser.addProgressListener(listener);
  win.gBrowser.tabContainer.addEventListener("TabSelect", select);
  win.addEventListener("unload", unload, { once: true });
  follow(win);
}

function detach(win) {
  const state = windows.get(win);
  if (!state) {
    return;
  }
  windows.delete(win);
  win.gBrowser?.removeProgressListener(state.listener);
  win.gBrowser?.tabContainer.removeEventListener("TabSelect", state.select);
  win.removeEventListener("unload", state.unload);
  state.line.remove();
}

let watching = null;

export const NulavioLoadLine = {
  /** From the Shell's start: the line in every browser window. */
  watch() {
    if (watching) {
      return;
    }
    watching = { observe: win => attach(win) };
    Services.obs.addObserver(watching, "browser-delayed-startup-finished");
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (win.gBrowserInit?.delayedStartupFinished) {
        attach(win);
      }
    }
  },

  unwatch() {
    if (!watching) {
      return;
    }
    Services.obs.removeObserver(watching, "browser-delayed-startup-finished");
    for (const win of [...windows.keys()]) {
      detach(win);
    }
    watching = null;
  },
};
