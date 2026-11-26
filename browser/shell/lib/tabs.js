/* Closing a Shell page's own tab, for every page that has a Close or Cancel (#700), and the held-link
   pages (#720).

   When the page is its window's only tab, removing that tab would close the window, and maybe the
   browser. The page opens a new tab in the same window first, which shows the new-tab page, and then
   removes its own. Loading `about:newtab` into the page's tab is not an option: the engine refuses
   `tabs.update` to that address from an extension page, so the button did nothing. A failure is
   shown, never swallowed: the page stays, and says it could not close. */

import { t } from "./i18n.js";
import { announce } from "./ui.js";

const say = text => announce(text, "error", { control: null });

// Set while this page closes its tab, so a second click (or a timer) does not open a second new tab.
let closing = false;

/** Close this page's tab, leaving its window open on a new tab when it is the only one.
    Only visible tabs count, as in the engine's own last-tab check: a window whose other tabs are all
    hidden closes with its last visible one. `failed` shows the message when the tab could not be
    closed (default: the page's status line). Returns whether the tab is going away. */
export async function closeOwnTab(failed = say) {
  if (closing) {
    return true;
  }
  closing = true;
  try {
    const tab = await browser.tabs.getCurrent();
    const visible = await browser.tabs.query({ windowId: tab.windowId, hidden: false });
    if (!visible.some(other => other.id !== tab.id)) {
      await browser.tabs.create({ windowId: tab.windowId });
    }
    await browser.tabs.remove(tab.id);
    return true;
  } catch (e) {
    closing = false; // the page stays: its buttons may try again
    console.error("could not close the tab", e);
    failed(t("tabCloseFailed"));
    return false;
  }
}

/** The same, after `ms`, so a result can be read first. The tabs are counted when it closes. */
export function closeOwnTabSoon(ms, failed = say) {
  setTimeout(() => closeOwnTab(failed), ms);
}
