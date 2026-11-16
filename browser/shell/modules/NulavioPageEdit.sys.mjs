/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* "Editar o texto da página" (#161): the page menu's item and Ctrl+Alt+E make the text of the tab's page
   editable in place, for a screenshot, a mock-up or to try a wording, and turn it off again.

   - Only the top document of a web page (http, https, file): the engine's own pages, Nulavio's pages, the
     PDF viewer and the source viewer are not offered. Frames keep what they are, from any site.
   - While it is on, the tab shows a bar of the engine's own kind (not drawn by the page): the page is
     editable, nothing is saved and reloading it discards the changes, with a button that stops it.
   - Nothing is saved anywhere. The bar is one of the tab's transient notifications, which the engine
     removes when another document comes; the page process turns editing off when its document leaves
     (NulavioPageEditChild), so a page shown again from the cache is not editable without the bar. */

const ACTOR = "NulavioPageEdit";
const BAR = "nulavio-page-edit";
const CHILD = "resource://builtin-addons/nulavio-shell/modules/NulavioPageEditChild.sys.mjs";
const SCHEMES = new Set(["http", "https", "file"]);

let registered = false;

function register() {
  if (registered) {
    return;
  }
  try {
    ChromeUtils.registerWindowActor(ACTOR, {
      child: { esModuleURI: CHILD, events: { pagehide: { mozSystemGroup: true } } },
      matches: ["http://*/*", "https://*/*", "file:///*"],
      allFrames: false,
      messageManagerGroups: ["browsers"],
      // Runs in web content processes: its only answer is a boolean, and the parent decides nothing from it
      // but which words the bar says.
      safeForUntrustedWebProcess: true,
    });
  } catch (e) {
    if (e?.name !== "NotSupportedError") {
      throw e; // anything but "already registered" (a Shell started again in the same session)
    }
  }
  registered = true;
}

function fail(code) {
  throw Object.assign(new Error(code), { code });
}

/** The tab's top document, when it is a web page that can be edited; otherwise null. */
function editable(browser) {
  const global = browser?.browsingContext?.currentWindowGlobal;
  const uri = browser?.currentURI;
  if (!global || !uri || !SCHEMES.has(uri.scheme)) {
    return null;
  }
  const principal = global.documentPrincipal;
  // The PDF viewer and an error page live at the address of what they show: their document is not the page's.
  if (!principal || principal.isSystemPrincipal || principal.originNoSuffix === "resource://pdf.js" || browser.documentContentType === "application/pdf") {
    return null;
  }
  if (!principal.schemeIs(uri.scheme) || global.documentURI?.spec !== uri.spec) {
    return null; // an error page (about:neterror, about:certerror) under the address it failed to load
  }
  return global;
}

/** The tab's bar: the page is editable, nothing is saved, reloading discards the changes; a button stops it. */
async function showBar(win, box, browser) {
  const t = key => WebExtensionPolicy.getByID("shell@nulavio.net")?.extension?.localizeMessage(key) || key;
  const stop = {
    label: t("pageEditStop"),
    callback: () => {
      NulavioPageEdit.set(browser, false, key => win.A11yUtils?.announce({ raw: t(key) }).catch(() => {})).catch(() => {});
      return false; // set() closes the bar
    },
  };
  await box.appendNotification(BAR, { label: t("pageEditBar"), priority: box.PRIORITY_INFO_MEDIUM }, [stop]);
}

const MENU_ITEM = "context-nulavio-edit-page";
let watching = null;

/* The page menu's item, among the engine's own, next to "View Page Source": a checkbox, shown where the page's
   source would be offered (or while the page is editable), for a page that can be edited, and not on a frame
   (editing is for the tab's page). */
function addMenuItem(win) {
  const doc = win.document;
  const menu = doc.getElementById("contentAreaContextMenu");
  if (!menu || doc.getElementById(MENU_ITEM)) {
    return;
  }
  const t = key => WebExtensionPolicy.getByID("shell@nulavio.net")?.extension?.localizeMessage(key) || key;
  const item = doc.createXULElement("menuitem");
  item.id = MENU_ITEM;
  item.setAttribute("type", "checkbox");
  item.setAttribute("label", t("menuEditPage"));
  item.hidden = true;
  item.addEventListener("command", () => {
    const browser = win.gContextMenu?.browser ?? win.gBrowser.selectedBrowser;
    const say = key => win.A11yUtils?.announce({ raw: t(key) }).catch(() => {});
    NulavioPageEdit.set(browser, !NulavioPageEdit.state(browser).on, say).catch(() => {}); // the other way from the bar
  });
  // After the engine has decided its own items for this menu (its handler is the element's attribute).
  menu.addEventListener("popupshowing", event => {
    if (event.target !== menu) {
      return;
    }
    const context = win.gContextMenu;
    const browser = context?.browser;
    const source = doc.getElementById("context-viewsource");
    const tab = Boolean(browser && browser === win.gBrowser.selectedBrowser && !context.inFrame);
    const now = tab ? NulavioPageEdit.state(browser) : null;
    // While the page is editable, the engine hides "View Page Source" (the page is a text field now): the item
    // stays, to stop editing.
    item.hidden = !now?.available || !(now.on || (source && !source.hidden));
    item.setAttribute("checked", String(Boolean(now?.on)));
  });
  const source = doc.getElementById("context-viewsource");
  menu.insertBefore(item, source?.parentNode === menu ? source : null);
}

export const NulavioPageEdit = {
  /** From the Shell's start: the page menu's item in every browser window. */
  watch() {
    if (watching) {
      return;
    }
    watching = { observe: win => addMenuItem(win) };
    Services.obs.addObserver(watching, "browser-delayed-startup-finished");
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (win.gBrowserInit?.delayedStartupFinished) {
        addMenuItem(win);
      }
    }
  },

  /** Whether the tab's page is editable now (the bar says so), and whether it could be. */
  state(browser) {
    const box = browser?.ownerDocument?.defaultView?.gBrowser?.getNotificationBox(browser);
    return { on: Boolean(box?.getNotificationWithValue(BAR)), available: Boolean(editable(browser)) };
  },

  /** Turn editing on or off (`on` null: the other way) for the tab's page. `say(key)` announces the outcome. */
  async set(browser, on = null, say = () => {}) {
    const win = browser?.ownerDocument?.defaultView;
    const box = win?.gBrowser?.getNotificationBox(browser);
    if (!box) {
      fail("page-edit-unavailable");
    }
    const want = on === null ? !box.getNotificationWithValue(BAR) : Boolean(on);
    const global = editable(browser);
    if (!global) {
      box.getNotificationWithValue(BAR)?.close();
      if (want) {
        say("pageEditNotHere");
        fail("page-edit-unavailable");
      }
      return this.state(browser);
    }
    register();
    let now = false;
    try {
      now = (await global.getActor(ACTOR).sendQuery("Set", { on: want })) === true;
    } catch (e) {
      now = false; // the document went away meanwhile: a new one is not editable
    }
    // The answer is for the document asked; another one may have come since. The bar follows the tab's page.
    const same = browser.browsingContext?.currentWindowGlobal === global;
    if (now && same) {
      if (!box.getNotificationWithValue(BAR)) {
        await showBar(win, box, browser);
      }
      say("pageEditOn");
    } else {
      box.getNotificationWithValue(BAR)?.close();
      say(want && !same ? "pageEditNotHere" : "pageEditOff");
    }
    return this.state(browser);
  },
};
