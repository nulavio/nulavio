/* Closing a Shell page's own tab, for every page that has a Close or Cancel (#700), and the held-link
   pages (#720).

   When the page is its window's only tab, removing that tab would close the window, and maybe the
   browser. The page's tab is closed by the background (lib/tab-closer.js), which opens a new tab in the
   same window first, when it has to, and decides one close at a time per window: two Shell pages closing
   at once each counted the other from their own documents, and the window closed (#741). Loading
   `about:newtab` into the page's tab is not an option: the engine refuses `tabs.update` to that address
   from an extension page, so the button did nothing. A failure is shown, never swallowed: the page stays,
   and says it could not close. */

import { t } from "./i18n.js";
import { announce } from "./ui.js";

const say = text => announce(text, "error", { control: null });

// Set while this page closes its tab, so a second click (or a timer) does not open a second new tab.
let closing = false;

/** Close this page's tab, leaving its window open on a new tab when it is the last visible one.
    `failed` shows the message when the tab could not be closed (default: the page's status line).
    Returns whether the tab is going away. */
export async function closeOwnTab(failed = say) {
  if (closing) {
    return true;
  }
  closing = true;
  try {
    // The background closes the tab this message comes from (background.js, "close-own-tab"). When it
    // works, this page goes away with its tab, usually before the answer arrives. Any other answer (no
    // listener answered) means the tab stays.
    if ((await browser.runtime.sendMessage({ type: "close-own-tab" })) !== true) {
      throw new Error("the background did not close the tab");
    }
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
