/* Nulavio Shell background (event page).

   Flow E: when a download that can run programs completes, open a Nulavio
   page explaining the risk, with "Show in folder" and "Delete" and no "Open".
   Profiles: keep the toolbar selector showing the current profile.
   Nothing is sent anywhere; nothing is stored. */

import { t } from "./lib/i18n.js";
import { drawProfileIcon } from "./lib/profile-icon.js";
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

// -- Profile selector (Track B: the engine's profiles; absent in Track A) --

async function showCurrentProfile() {
  const state = await browser.nulavioProfiles.list();
  const current = state.profiles.find(p => p.isCurrent);
  if (!state.available || !current) {
    await browser.action.setTitle({ title: t("profilesButton") });
    return;
  }
  await browser.action.setIcon({ imageData: drawProfileIcon(current) });
  await browser.action.setTitle({ title: t("profilesButtonNamed", [current.name]) });
}

if (browser.nulavioProfiles && browser.action) {
  browser.nulavioProfiles.onChanged.addListener(() => showCurrentProfile().catch(console.error));
  showCurrentProfile().catch(console.error);
}
