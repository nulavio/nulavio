/* Nulavio Shell background (event page).

   Flow E: when a download that can run programs completes, open a Nulavio
   page explaining the risk, with "Show in folder" and "Delete" and no "Open".
   Profiles: keep the toolbar selector showing the current profile.
   Nothing is sent anywhere; nothing is stored. */

import { workspaceBarTexts } from "./lib/agent-texts.js";
import { t } from "./lib/i18n.js";
import { TOOLBAR_INK, drawProfileIcon } from "./lib/profile-icon.js";
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

// The button is drawn in the toolbar's icon colour: the theme's, and the private chrome's (dark in
// both themes) in each private window. Redrawn when the theme changes. The scheme is the browser window's, read in the
// parent process and announced from there (nulavioPersonalise, on look-and-feel-changed): this page is windowless, and a
// desktop's own scheme change never reached its matchMedia, so the button kept the other scheme's ink (#368).
const darkTheme = matchMedia("(prefers-color-scheme: dark)");
let shownProfile = null;

async function toolbarDark() {
  const state = await browser.nulavioPersonalise?.state().catch(() => null);
  return state?.system?.dark ?? darkTheme.matches; // Track A has no experiments
}

async function setProfileIcon(profile) {
  shownProfile = profile;
  const ink = (await toolbarDark()) ? TOOLBAR_INK.dark : TOOLBAR_INK.light;
  await browser.action.setIcon({ imageData: drawProfileIcon(profile, { ink }) });
  const windows = await browser.windows.getAll({ windowTypes: ["normal"] }).catch(() => []);
  for (const win of windows.filter(w => w.incognito)) {
    await browser.action.setIcon({ windowId: win.id, imageData: drawProfileIcon(profile, { ink: TOOLBAR_INK.private }) }).catch(() => {});
  }
}

async function showCurrentProfile() {
  const state = await browser.nulavioProfiles.list();
  if (state.reason === "temporary") {
    await setProfileIcon({ name: t("profilesTemporaryShort"), temporary: true });
    await browser.action.setTitle({ title: t("profilesTemporaryButton") });
    await browser.nulavioProfiles.markTemporary(`${t("profilesTemporaryBar")} ${temporaryStorageText(state.temporary)}`);
    return;
  }
  const current = state.profiles.find(p => p.isCurrent);
  if (!state.available || !current) {
    await browser.action.setTitle({ title: t("profilesButton") });
    return;
  }
  await setProfileIcon(current);
  // The menu's key as the engine has it now (UX6: it can be changed in Settings > Atalhos).
  const command = (await browser.commands?.getAll?.().catch(() => []))?.find(c => c.name === "_execute_action");
  await browser.action.setTitle({
    title: command?.shortcut ? t("profilesButtonNamedKey", [current.name, command.shortcut]) : t("profilesButtonNamed", [current.name]),
  });
}

if (browser.nulavioProfiles && browser.action) {
  browser.nulavioProfiles.onChanged.addListener(() => showCurrentProfile().catch(console.error));
  showCurrentProfile().catch(console.error);
  browser.commands?.onChanged?.addListener(() => showCurrentProfile().catch(console.error));
  // commands.reset() fires no onChanged in Firefox 159: Settings > Atalhos says when it restored a key.
  browser.runtime.onMessage.addListener(message => {
    if (message?.type === "commands-reset") {
      showCurrentProfile().catch(console.error);
    }
  });
  const redraw = () => shownProfile && setProfileIcon(shownProfile).catch(console.error);
  darkTheme.addEventListener("change", redraw);
  browser.nulavioPersonalise?.onChanged.addListener(redraw);
  browser.windows.onCreated.addListener(win => {
    if (win.incognito && shownProfile) {
      browser.action.setIcon({ windowId: win.id, imageData: drawProfileIcon(shownProfile, { ink: TOOLBAR_INK.private }) }).catch(() => {});
    }
  });
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
// the question) and open it; nothing is sent until Send. Never in private windows: there the item
// is hidden by the window's own sheet (window-band.css, #138) before the menu is drawn, and a click
// that still reached it does nothing; its visibility is never changed here, since that would change
// it in every window and only after the menu was on screen. None of it is offered where an agent
// drives the browser (its AI Workspace). The label never repeats the selection itself. The listeners
// are added at once, so the event page wakes for them.

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

// -- Nulavio keys (UX6, D-UX23) ---------------------------------------------
// Ctrl+Alt+F toggles the Foco layout (and back to the preset it came from). Ctrl+Alt+B only opens
// the profile menu, which shows the same "Bloquear agora" confirmation as its button (Cancel
// focused); nothing here locks a profile or changes a protection itself. Both can be remapped in the
// engine's extension shortcuts view (Settings > Atalhos).

let lockAsked = 0; // when Ctrl+Alt+B was pressed; the menu takes it once, within a few seconds

if (browser.commands) {
  browser.commands.onCommand.addListener(async (command, tab) => {
    if (command === "toggle-focus" && browser.nulavioLayout?.toggleFocus) {
      const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
      if (target) {
        browser.nulavioLayout.toggleFocus(target.id).catch(() => {}); // announced in the window
      }
    } else if (command === "toggle-immersive" && browser.nulavioLayout?.setImmersive) {
      // Ctrl+Alt+I: Immersive on or off (ADR 0009). The window decides where it applies; the toolbar is
      // always back for a prompt, and stays wherever the band cannot name the page.
      const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
      browser.nulavioLayout.setImmersive(null, target?.id ?? null).catch(() => {}); // announced in the window
    } else if (command === "copy-link-to-highlight" && browser.nulavioLayout?.copyLinkToHighlight) {
      // #157: the engine's "Copy Link to Highlight", for the selection of the tab the key was pressed in.
      const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
      if (target) {
        browser.nulavioLayout.copyLinkToHighlight(target.id).catch(() => {}); // announced in the window
      }
    } else if (command === "toggle-page-editing" && browser.nulavioLayout?.setPageEditing) {
      // #161: the text of the tab's page editable in place, or no longer; nothing is saved (the tab says so).
      const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
      if (target) {
        browser.nulavioLayout.setPageEditing(null, target.id).catch(() => {}); // announced in the window
      }
    } else if (command === "toggle-keep-above" && browser.nulavioLayout?.setKeepAbove) {
      // #170: KDE Plasma's "keep above" for the window the key was pressed in; KWin's own answer is announced.
      const target = tab ?? (await browser.tabs.query({ active: true, currentWindow: true }))[0];
      if (target) {
        browser.nulavioLayout.setKeepAbove(target.id).catch(() => {}); // announced in the window
      }
    } else if (command === "lock-profile") {
      lockAsked = Date.now();
      browser.action.openPopup(tab ? { windowId: tab.windowId } : {}).catch(console.error);
    }
  });
  browser.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type === "take-lock-request") {
      respond(Date.now() - lockAsked < 5000);
      lockAsked = 0;
    }
  });
}

// -- "@ia" in the address bar (UX5-H, Q7): what follows only fills the assistant's question --
// Nothing is kept while typing, and Enter only opens the panel of that window with the text in the
// question; Send stays the person's. Search suggestions never get it: the engine skips them for text
// that starts with "@" and names no search engine (bug 1551049; tests/integration/test_search.py 05b
// checks it). In a private window the text is dropped.

if (browser.nulavioAI && browser.omnibox) {
  browser.omnibox.setDefaultSuggestion({ description: t("omniboxDefault") });
  browser.omnibox.onInputEntered.addListener(async text => {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tab || tab.incognito || (await browser.nulavioAI.workspaceAgent())) {
      return;
    }
    browser.nulavioAI.assistantOffer({ kind: "draft", text: String(text).slice(0, 8000) }, tab.id).catch(console.error);
  });
}

// -- Web services on a click: translation (#156) -------------------------------
// One item per service and use, named after the service ("Traduzir seleção com DeepL"), only for services the
// person added in Settings. Each time a menu opens, the module says whether an item may be used there: hidden in a
// private window unless the person allowed it, and shown but unusable, with the reason in its words, for an address
// a service should not fetch (this computer, a local network, not a web page). The click opens the service's
// address in a new tab; nothing is sent before it. The listeners are added at once, so the event page wakes for them.

const SERVICE_MENU = "nulavio-svc-";
const serviceItems = new Map(); // menu id -> the module's item
const serviceStates = new Map(); // menu id -> what the item shows now ({visible, enabled, title})

function serviceTitle(item, reason = null) {
  const key = { "translate-selection": "menuTranslateSelection", "translate-page": "menuTranslatePage" }[item.use];
  const title = t(key, item.name);
  return reason ? t("menuServiceRefused", [title, t(`menuServiceReason_${reason.replaceAll("-", "_")}`)]) : title;
}

async function drawServiceMenus() {
  const items = await browser.nulavioServices.menu();
  for (const id of serviceItems.keys()) {
    await browser.menus.remove(id).catch(() => {});
  }
  serviceItems.clear();
  serviceStates.clear();
  for (const [index, item] of items.entries()) {
    const id = `${SERVICE_MENU}${index}`; // the item's own id stays in the map: menu ids become element ids
    serviceItems.set(id, item);
    serviceStates.set(id, { visible: true, enabled: true, title: serviceTitle(item) });
    browser.menus.create({ id, title: serviceTitle(item), contexts: item.contexts }, () => void browser.runtime.lastError);
  }
}

// One drawing at a time, in order: several settings changed together (a choice and its clean-up) must not leave the
// map naming one service for an item that shows another.
let serviceDrawing = (async () => {})();
let serviceRedraw = null;
function redrawServiceMenus() {
  // Settings changed together arrive as several events: one drawing for all of them (as rebuildLinkMenu does).
  clearTimeout(serviceRedraw);
  serviceRedraw = setTimeout(() => {
    serviceDrawing = serviceDrawing.then(drawServiceMenus).catch(console.error);
  }, 100);
}

if (browser.nulavioServices && browser.menus) {
  serviceDrawing = drawServiceMenus().catch(console.error);
  browser.nulavioServices.onChanged.addListener(redrawServiceMenus);
  browser.menus.onShown.addListener(async (info, tab) => {
    // Every item this menu's contexts call for, not only the ones the engine drew: an item hidden in a private
    // window is not drawn anywhere until it is made visible again here.
    const shown = [...serviceItems.keys()].filter(id => serviceItems.get(id).contexts.some(context => info.contexts.includes(context)));
    if (!shown.length || !tab) {
      return;
    }
    // Only an item whose state changes is updated, and the menu drawn again only then: an open menu drawn again
    // replaces its items under the pointer.
    let changed = false;
    for (const id of shown) {
      const item = serviceItems.get(id);
      const target = info.pageUrl ?? "";
      const verdict = await browser.nulavioServices.check(item.id, target, tab.id).catch(() => ({ usable: false, reason: "not-found", hidden: true }));
      const next = { visible: !verdict.hidden, enabled: verdict.usable, title: serviceTitle(item, verdict.usable ? null : verdict.reason) };
      const now = serviceStates.get(id);
      if (now && now.visible === next.visible && now.enabled === next.enabled && now.title === next.title) {
        continue;
      }
      await browser.menus.update(id, next);
      serviceStates.set(id, next);
      changed = true;
    }
    if (changed) {
      browser.menus.refresh();
    }
  });
  browser.menus.onClicked.addListener(async (info, tab) => {
    await serviceDrawing; // a drawing under way decides what the item now is
    const item = serviceItems.get(String(info.menuItemId));
    if (!item || !tab) {
      return;
    }
    const target = info.pageUrl ?? "";
    browser.nulavioServices.open(item.id, { text: info.selectionText ?? "", target }, tab.id).catch(console.error);
  });
}
