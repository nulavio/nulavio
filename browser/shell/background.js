/* Nulavio Shell background (event page).

   Flow E: when a download that can run programs completes, open a Nulavio
   page explaining the risk, with "Show in folder" and "Delete" and no "Open".
   Nothing is sent anywhere; nothing is stored. */

import { isRiskyFilename } from "./lib/risky.js";

async function windowFor(incognito) {
  // Keep private downloads in private windows and vice versa.
  const windows = await browser.windows.getAll({ windowTypes: ["normal"] });
  const matching = windows.filter(w => w.incognito === incognito);
  return (matching.find(w => w.focused) || matching[0] || null)?.id ?? null;
}

browser.downloads.onChanged.addListener(async delta => {
  if (delta.state?.current !== "complete") {
    return;
  }
  const [item] = await browser.downloads.search({ id: delta.id });
  if (!item || !isRiskyFilename(item.filename)) {
    return;
  }
  const windowId = await windowFor(Boolean(item.incognito));
  if (windowId === null) {
    return; // no window of the same kind: never move a private download into a normal window
  }
  await browser.tabs.create({
    windowId,
    active: true,
    url: browser.runtime.getURL(`warning/warning.html?id=${encodeURIComponent(item.id)}`),
  });
});
