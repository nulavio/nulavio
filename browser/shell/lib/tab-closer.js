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
      throw new Error("the page that asked left its tab");
    }
    return tab.windowId;
  }

  async function closeIn(windowId, tabId, url) {
    if ((await where(tabId, url)) !== windowId) {
      return MOVED; // dragged to another window while it waited: counted there, after the closes queued there
    }
    const visible = await tabs.query({ windowId, hidden: false });
    if (!visible.some(other => other.id !== tabId)) {
      await tabs.create({ windowId });
    }
    // Once more just before the removal: a tab moved or navigated while it was counted is decided again.
    if ((await where(tabId, url)) !== windowId) {
      return MOVED;
    }
    await tabs.remove(tabId);
    return true;
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
