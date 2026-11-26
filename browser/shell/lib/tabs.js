/* Closing a Shell page's own tab, for every page that has a Close or Cancel (#700).

   When the page is its window's only tab, removing that tab would close the window, and maybe the
   browser. The page opens a new tab in the same window first, which shows the new-tab page, and then
   removes its own. Loading `about:newtab` into the page's tab is not an option: the engine refuses
   `tabs.update` to that address from an extension page, so the button did nothing. A failure is
   shown, never swallowed: the page stays, and says it could not close. */

import { t } from "./i18n.js";
import { announce } from "./ui.js";

const say = text => announce(text, "error", { control: null });

/** Close this page's tab, leaving its window open on a new tab when it is the only one.
    `failed` shows the message when the tab could not be closed (default: the page's status line). */
export async function closeOwnTab(failed = say) {
  try {
    const tab = await browser.tabs.getCurrent();
    const siblings = await browser.tabs.query({ windowId: tab.windowId });
    if (siblings.length < 2) {
      await browser.tabs.create({ windowId: tab.windowId });
    }
    await browser.tabs.remove(tab.id);
  } catch (e) {
    console.error("could not close the tab", e);
    failed(t("tabCloseFailed"));
  }
}

/** The same, after `ms`, so a result can be read first. The tabs are counted when it closes. */
export function closeOwnTabSoon(ms, failed = say) {
  setTimeout(() => closeOwnTab(failed), ms);
}
