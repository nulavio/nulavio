/* The one place that closes a Shell page's own tab (#700, #720, #741). The background runs it for every page
   (lib/tabs.js asks it to), so closes are decided one at a time per window.

   When the tab is its window's last visible one, removing it would close the window, and maybe the browser:
   a new tab is opened in that window first, then the page's tab is removed. Only visible tabs count, as in the
   engine's own last-tab check. Each page used to count and remove from its own document: two Shell pages that
   were a window's only tabs, closing at once (a timer on one, a click on the other), each counted the other,
   neither opened a new tab, and the second removal closed the window. Here a close in a window waits for the
   one before it there, so it counts after that removal took effect.

   No imports and no `browser` global: `tabs` is the extension's `browser.tabs`, or a fake in the unit tests. */

// How long a close waits for the one before it in the same window. A removal that never settles (a page that
// asks before it is left, and the person stays) must not keep every later close in that window waiting.
const WAIT_MS = 5000;

const MOVED = Symbol("moved");

/** Returns `close(tabId)`: closes that tab, leaving its window open on a new tab when it is the last visible
    one. Resolves when the tab was removed; rejects with the engine's error, and the tab then stays. */
export function tabCloser(tabs, { wait = WAIT_MS } = {}) {
  const last = new Map(); // window id -> the last close queued in that window

  async function closeIn(windowId, tabId) {
    const tab = await tabs.get(tabId);
    if (tab.windowId !== windowId) {
      return MOVED; // dragged to another window while it waited: counted there, after the closes queued there
    }
    const visible = await tabs.query({ windowId, hidden: false });
    if (!visible.some(other => other.id !== tabId)) {
      await tabs.create({ windowId });
    }
    await tabs.remove(tabId);
    return true;
  }

  return async function close(tabId) {
    const { windowId } = await tabs.get(tabId);
    const before = last.get(windowId);
    let timer;
    const turn = before
      ? Promise.race([before.catch(() => {}), new Promise(resolve => (timer = setTimeout(resolve, wait)))])
      : Promise.resolve();
    const mine = turn.then(() => {
      clearTimeout(timer);
      return closeIn(windowId, tabId);
    });
    last.set(windowId, mine);
    const done = () => {
      if (last.get(windowId) === mine) {
        last.delete(windowId);
      }
    };
    mine.then(done, done);
    return (await mine) === MOVED ? close(tabId) : true;
  };
}
