/* The one place that closes a Shell page's own tab (#700, #720, #741). The background runs it for every page
   (lib/tabs.js asks it to), so closes are decided one at a time per window.

   When the tab is its window's last visible one, removing it would close the window, and maybe the browser:
   a new tab is opened in that window first, then the page's tab is removed. Only visible tabs count, as in the
   engine's own last-tab check. Each page used to count and remove from its own document: two Shell pages that
   were a window's only tabs, closing at once (a timer on one, a click on the other), each counted the other,
   neither opened a new tab, and the second removal closed the window. Here a close in a window waits for the
   one before it there, so it counts after that removal took effect.

   No imports and no `browser` global: `tabs` is the extension's `browser.tabs`, or a fake in the unit tests. */

const MOVED = Symbol("moved");
const LEFT = "the page that asked left its tab";

/** Returns `close(tabId, url)`: closes that tab, leaving its window open on a new tab when it is the last visible
    one, as long as the tab still shows `url` (the page that asked). Resolves when the tab was removed; rejects
    with the engine's error, or when the tab no longer shows that page, and the tab then stays. */
export function tabCloser(tabs) {
  const last = new Map(); // window id -> the last close queued in that window

  // Where the tab is now, refused when it no longer shows the page that asked: a tab navigated to another page
  // while its close waited holds that page now, and is never removed for the one that left.
  async function where(tabId, url) {
    const tab = await tabs.get(tabId);
    if (tab.url !== url) {
      throw new Error(LEFT);
    }
    return tab.windowId;
  }

  // Each look reads the tab that asked (page, window) and its window's visible tabs together. A removal follows
  // only a look that found another visible tab and came after an earlier look: a tab moved, navigated or left
  // alone while it was counted is decided again, and nothing is opened or removed for a tab that left the page.
  // The engine has no atomic count-and-remove, so a change after the last look still lands after the decision.
  async function closeIn(windowId, tabId, url) {
    for (let look = 0; look < 3; look++) {
      const [tab, visible] = await Promise.all([tabs.get(tabId), tabs.query({ windowId, hidden: false })]);
      if (tab.url !== url) {
        throw new Error(LEFT);
      }
      if (tab.windowId !== windowId) {
        return MOVED; // dragged to another window while it waited: counted there, after the closes queued there
      }
      const others = visible.some(other => other.id !== tabId);
      if (others && look > 0) {
        await tabs.remove(tabId);
        return true;
      }
      if (!others) {
        try {
          await tabs.create({ windowId });
        } catch (e) {
          // Its window may have closed because the tab left it (dragged out alone): counted where it is now.
          if ((await where(tabId, url)) !== windowId) {
            return MOVED;
          }
          throw e;
        }
      }
    }
    throw new Error("the window kept changing while the tab closed");
  }

  // A close waits for the whole of the one before it in its window, however long that takes: a removal that asks
  // first (a page that warns before it is left) is still pending while the person answers, and a close counted
  // before that answer would count that tab as staying.
  return async function close(tabId, url) {
    const windowId = await where(tabId, url);
    const before = last.get(windowId) ?? Promise.resolve();
    const mine = before.catch(() => {}).then(() => closeIn(windowId, tabId, url));
    last.set(windowId, mine);
    const done = () => {
      if (last.get(windowId) === mine) {
        last.delete(windowId);
      }
    };
    mine.then(done, done);
    return (await mine) === MOVED ? close(tabId, url) : true;
  };
}
