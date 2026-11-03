/* Nulavio Shell background (event page).

   Flow E: when a download that can run programs completes, open a Nulavio
   page explaining the risk, with "Show in folder" and "Delete" and no "Open".
   Profiles: keep the toolbar selector showing the current profile.
   Nothing is sent anywhere; nothing is stored. */

import { workspaceBarTexts } from "./lib/agent-texts.js";
import { t } from "./lib/i18n.js";
import { drawProfileIcon } from "./lib/profile-icon.js";
import { isRiskyFilename } from "./lib/risky.js";
import { temporaryStorageText } from "./lib/ui.js";

// This is an event page: without a listener here it would not start with the browser after the
// first run, and the work below (profile icon, AI requests, temporary bar) would wait for an event.
browser.runtime.onStartup.addListener(() => {});

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
  if (state.reason === "temporary") {
    await browser.action.setIcon({ imageData: drawProfileIcon({ name: t("profilesTemporaryShort"), temporary: true }) });
    await browser.action.setTitle({ title: t("profilesTemporaryButton") });
    await browser.nulavioProfiles.markTemporary(`${t("profilesTemporaryBar")} ${temporaryStorageText(state.temporary)}`);
    return;
  }
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
let linkMenu = false; // the item exists (there are other profiles)

async function buildLinkMenu() {
  linkMenu = false;
  await browser.menus.remove(LINK_MENU).catch(() => {}); // only this menu: others (send link) stay
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
  linkMenu = true;
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
  // A hidden item is left out of onShown's menuIds, so the link context decides here:
  // checking menuIds kept the item hidden everywhere after one private window.
  browser.menus.onShown.addListener(async (info, tab) => {
    if (linkMenu && info.contexts.includes("link")) {
      await browser.menus.update(LINK_MENU, { visible: !tab?.incognito }).catch(() => {});
      browser.menus.refresh();
    }
  });
  browser.nulavioProfiles.onChanged.addListener(rebuildLinkMenu);
  rebuildLinkMenu();
}

// -- AI & Automation: permission requests from agents, and the AI Workspace mark --
// In the user's windows, requests from the AI Bridge open a request page. In a
// window an agent drives (its AI Workspace, or one of the user's profiles) none
// are shown; a bar that cannot be closed says who drives it, at which level and
// where, with "Parar agente"; raw automation gets its own critical bar.

async function setUpAI() {
  const agent = await browser.nulavioAI.workspaceAgent();
  if (!agent) {
    await browser.nulavioAI.watch();
    return;
  }
  const { agents } = await browser.nulavioAI.overview().catch(() => ({ agents: [] }));
  const record = agents.find(a => a.id === agent);
  const target = await browser.nulavioAI.workspaceTarget();
  await browser.nulavioAI.markWorkspace(workspaceBarTexts(record?.name ?? agent, record?.autonomy, target));
}

if (browser.nulavioAI) {
  setUpAI().catch(console.error);
}

// -- Nulavio Connect: send one link to a KDE Connect device, on the user's click --
// The menu lists the devices reachable when it opens; never offered in private windows.
// The item is hidden until then, and the engine leaves hidden items out of onShown's
// menuIds, so a link menu is recognised by its context (the item's URL patterns still
// keep it off non-web links).

const SEND_MENU = "nulavio-send-link";

if (browser.nulavioConnect && browser.menus) {
  const scope = { contexts: ["link"], targetUrlPatterns: ["http://*/*", "https://*/*"] };
  browser.menus.create({ id: SEND_MENU, title: t("menuSendLink"), visible: false, ...scope });
  let shown = [];
  let visible = false;
  let opened = 0; // the menu that is open now: answers for one already closed are dropped
  // The device list comes from KDE Connect's own tool (a helper process, ~1-2 s): a recent answer
  // is used at once, so only the first link menu in a while waits for it. A phone that left in the
  // last 30 s can still be listed; sending to it fails as for any unreachable device.
  const FRESH_MS = 30000;
  let known = null;
  let knownAt = 0;
  const devices = async () => {
    if (known && Date.now() - knownAt < FRESH_MS) {
      return known;
    }
    const found = await browser.nulavioConnect.kdeDevices().catch(() => null);
    // Only a list with devices is kept: a failure or an empty answer (KDE Connect still starting,
    // a phone not connected yet) is asked again at the next menu (review F14).
    known = found?.length ? found : null;
    knownAt = Date.now();
    return found ?? [];
  };
  browser.menus.onHidden.addListener(() => {
    opened++;
    if (visible) {
      visible = false; // each menu starts without it: no stale devices, nothing in private windows
      browser.menus.update(SEND_MENU, { visible: false }).catch(() => {});
    }
  });
  browser.menus.onShown.addListener(async (info, tab) => {
    const menu = ++opened;
    if (!info.contexts.includes("link") || tab?.incognito) {
      return;
    }
    const reachable = await devices();
    if (menu !== opened) {
      return;
    }
    await Promise.all(shown.map(id => browser.menus.remove(id).catch(() => {})));
    shown = reachable.map(device => {
      const id = `${SEND_MENU}:${device.id}`;
      browser.menus.create({ id, parentId: SEND_MENU, title: device.name, ...scope });
      return id;
    });
    if (menu !== opened) {
      return;
    }
    visible = reachable.length > 0;
    await browser.menus.update(SEND_MENU, { visible });
    browser.menus.refresh();
  });
  browser.menus.onClicked.addListener((info, tab) => {
    const id = String(info.menuItemId);
    if (id.startsWith(`${SEND_MENU}:`) && !tab?.incognito) {
      browser.nulavioConnect.sendLink(info.linkUrl, id.slice(SEND_MENU.length + 1)).catch(console.error);
    }
  });
}

// -- Nulavio Assistant: "Perguntar ao assistente" on a selection, and its shortcut (UX5-G) --
// Both only put something in the panel of that window (the selection as an item, or the focus on
// the question) and open it; nothing is sent until Send. Never in private windows, and none of it
// is offered where an agent drives the browser (its AI Workspace). The label never repeats the
// selection itself. The listeners are added at once, so the event page wakes for them.

const ASK_MENU = "nulavio-ask-selection";

if (browser.nulavioAI && browser.menus) {
  browser.nulavioAI
    .workspaceAgent()
    .then(agent => {
      if (!agent) {
        browser.menus.create({ id: ASK_MENU, title: t("menuAskSelection"), contexts: ["selection"] }, () => void browser.runtime.lastError);
      }
    })
    .catch(console.error);
  browser.menus.onShown.addListener(async (info, tab) => {
    if (info.contexts.includes("selection")) {
      await browser.menus.update(ASK_MENU, { visible: !tab?.incognito }).catch(() => {});
      browser.menus.refresh();
    }
  });
  browser.menus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === ASK_MENU && tab && !tab.incognito) {
      const offer = { kind: "selection", pageUrl: info.pageUrl ?? "", frameUrl: info.frameUrl ?? "", text: info.selectionText ?? "" };
      browser.nulavioAI.assistantOffer(offer, tab.id).catch(console.error);
    }
  });
}

if (browser.nulavioAI && browser.commands) {
  browser.commands.onCommand.addListener(async (command, tab) => {
    if (command !== "open-assistant") {
      return;
    }
    const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
    if (target && !target.incognito) {
      browser.nulavioAI.assistantOffer({ kind: "composer" }, target.id).catch(console.error);
    }
  });
}
