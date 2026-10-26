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

// -- "Open link in profile": the user's explicit choice from a link's menu --
// Only web links; never offered in private windows (private browsing never
// switches profile). The link goes with the routed flag, so no rule moves it again.

const LINK_MENU = "nulavio-open-link-in";
let menuBuild = null;

async function buildLinkMenu() {
  await browser.menus.removeAll();
  const state = await browser.nulavioProfiles.list();
  const others = state.available ? state.profiles.filter(p => !p.isCurrent && p.id !== null) : [];
  if (!others.length) {
    return;
  }
  const scope = { contexts: ["link"], targetUrlPatterns: ["http://*/*", "https://*/*"] };
  browser.menus.create({ id: LINK_MENU, title: t("menuOpenLinkIn"), ...scope });
  for (const profile of others) {
    browser.menus.create({ id: `${LINK_MENU}:${profile.id}`, parentId: LINK_MENU, title: profile.name, ...scope });
  }
}

function rebuildLinkMenu() {
  clearTimeout(menuBuild);
  menuBuild = setTimeout(() => buildLinkMenu().catch(console.error), 100);
}

if (browser.nulavioProfiles && browser.nulavioRouting && browser.menus) {
  browser.menus.onClicked.addListener((info, tab) => {
    const id = String(info.menuItemId);
    if (!id.startsWith(`${LINK_MENU}:`) || tab?.incognito) {
      return;
    }
    const profileId = Number(id.slice(LINK_MENU.length + 1));
    browser.nulavioRouting.openIn(profileId, info.linkUrl).catch(e => {
      if (e?.message === "locked" && browser.nulavioVault) {
        return browser.nulavioVault.openUnlockPage(profileId, info.linkUrl);
      }
      console.error(e);
    });
  });
  browser.menus.onShown.addListener(async (info, tab) => {
    if (info.menuIds.includes(LINK_MENU)) {
      await browser.menus.update(LINK_MENU, { visible: !tab?.incognito });
      browser.menus.refresh();
    }
  });
  browser.nulavioProfiles.onChanged.addListener(rebuildLinkMenu);
  rebuildLinkMenu();
}

// -- AI & Automation: permission requests from agents, and the AI Workspace mark --
// In the user's windows, requests from the AI Bridge open a request page. In an
// AI Workspace (driven by an agent) none are shown; a bar says who drives it.

async function setUpAI() {
  const agent = await browser.nulavioAI.workspaceAgent();
  if (!agent) {
    await browser.nulavioAI.watch();
    return;
  }
  const { agents } = await browser.nulavioAI.overview().catch(() => ({ agents: [] }));
  const name = agents.find(a => a.id === agent)?.name ?? agent;
  await browser.nulavioAI.markWorkspace(browser.i18n.getMessage("aiWorkspaceBar", [name]));
}

if (browser.nulavioAI) {
  setUpAI().catch(console.error);
}
