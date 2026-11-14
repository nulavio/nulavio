/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Farol is privileged chrome, independent of the cosmetic Horizon preference.
   Native controls remain in their own toolbars. Only our area/widget is repaired
   after customization; no reset of the user's placements or preferences. */
const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AboutNewTab: "resource:///modules/AboutNewTab.sys.mjs",
  ActionsProviderQuickActions: "moz-src:///browser/components/urlbar/ActionsProviderQuickActions.sys.mjs",
  CustomizableUI: "moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs",
  ExtensionParent: "resource://gre/modules/ExtensionParent.sys.mjs",
  ExtensionSettingsStore: "resource://gre/modules/ExtensionSettingsStore.sys.mjs",
  NulavioAI: "resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs",
  NulavioGuard: "resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs",
  NulavioLayout: "resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs",
  NulavioPrivacy: "resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs",
  AVATAR_GLYPHS: "resource://builtin-addons/nulavio-shell/modules/NulavioAvatars.sys.mjs",
  SPECIAL_GLYPHS: "resource://builtin-addons/nulavio-shell/modules/NulavioAvatars.sys.mjs",
  profileInitial: "resource://builtin-addons/nulavio-shell/modules/NulavioAvatars.sys.mjs",
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  NulavioRouting: "resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs",
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
});
const sheets = Cc["@mozilla.org/content/style-sheet-service;1"].getService(Ci.nsIStyleSheetService);
const sidebarFocus = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/sidebar-focus.css");
const bandSheet = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/window-band.css");
// UX3F A2: the engine's internal pages (Settings, add-ons, home) in Nulavio's colours. Scoped by exact
// about: URLs inside the sheet, so web pages never see it.
const inContent = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/in-content.css");
const AREA = "nulavio-band";
// The engine calls NulavioWindow.prepareWindow(window) from this category for each new browser
// window, before CustomizableUI handles it (browser-init.js onDOMContentLoaded).
const EARLY_WINDOW = "browser-window-domcontentloaded-before-tabbrowser";
const EARLY_ENTRY = "resource://builtin-addons/nulavio-shell/modules/NulavioWindow.sys.mjs#band";
const WIDGET = "nulavio-band-widget";
const QUICK_ACTION = "nulavio-assistant"; // the address bar quick action (UX5-H)
// UX6 (D8): Nulavio's other quick actions after ">". None of them unlocks, resumes, grants or turns
// anything off (tests/unit/test_personalisation.py); lock and AI actions have their own places.
const QUICK_ACTIONS = Object.freeze([QUICK_ACTION, "nulavio-settings", "nulavio-focus"]);
const SHELL = "shell@nulavio.net";
const HTML = "http://www.w3.org/1999/xhtml";
// nulavio-ai-agent-files-changed: the driving agent's registry or the emergency stop changed (NulavioAI).
const TOPICS = ["browser-delayed-startup-finished", "nulavio-ai-window-changed", "nulavio-guard-changed",
  "nulavio-ai-agent-files-changed", "nulavio-ai-activity-changed"];
// Fixed paths only. Query strings, fragments, titles and page text never name a trusted surface.
const SURFACES = Object.freeze({
  "/newtab/newtab.html": "newtabTitle",
  "/settings/settings.html": "settingsTitle",
  "/profiles/popup.html": "profilesButton",
  "/vault/unlock.html": "bandSurfaceUnlock",
  "/vault/create.html": "vaultCreateTitle",
  "/vault/phone.html": "bandSurfacePhone",
  "/vault/methods.html": "bandSurfaceMethods",
  "/guard/review.html": "bandSurfaceGuard",
  "/ai/request.html": "bandSurfacePermission",
  "/routing/ask.html": "bandSurfaceRouting",
  "/routing/blocked.html": "bandSurfaceRouting",
  "/warning/warning.html": "bandSurfaceDownload",
  "/passwords/lookalike.html": "bandSurfacePassword",
});
// UX3H A-1: ordinary Shell pages. Their name is on the tab, so in the navigation row
// (window-band.css) the band does not repeat it. Every other surface asks for trust
// and keeps its name in a full band row ([nv-named]).
const PLAIN_SURFACES = Object.freeze(new Set(["newtabTitle", "settingsTitle", "profilesButton"]));
// ADR 0009: the toolbar and the tab list hide; the band stays and carries the origin.
const PREF_IMMERSIVE = "nulavio.layout.immersive";
// The first run owns the window (ADR 0010): the same pref the new tab's sequence writes.
const PREF_FIRSTRUN = "nulavio.firstrun.done";

function policy() {
  return WebExtensionPolicy.getByID(SHELL);
}

function t(key, subs = []) {
  return policy()?.extension?.localizeMessage(key, subs) || key;
}

function element(doc, tag, className = "") {
  const node = doc.createElementNS(HTML, tag);
  node.className = className;
  return node;
}

function button(doc, className, action) {
  const node = element(doc, "button", className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

// The band repaints on every refresh tick (1.5 s) in every window. In browser.xhtml a
// textContent write always replaces the text node (the document has mutation observers),
// which reconstructs frames, reflows the toolbox and fires accessibility events. So the
// band writes only what changed: the result is the same DOM, by construction.
const SVG = "http://www.w3.org/2000/svg";

/** The profile's solid glyph (NulavioAvatars) in the band's 16 px tile, redrawn only when it changes. */
function showGlyph(node, d) {
  if (node.firstElementChild?.dataset?.d === d) {
    return;
  }
  const doc = node.ownerDocument;
  const svg = doc.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "nv-band-glyph-avatar");
  svg.dataset.d = d;
  const path = doc.createElementNS(SVG, "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "currentColor");
  path.setAttribute("fill-rule", "evenodd");
  svg.append(path);
  node.replaceChildren(svg);
}

function setText(node, text) {
  if (node.textContent !== text) {
    node.textContent = text;
  }
}

function setAttr(node, name, value) {
  if (node.getAttribute(name) !== value) {
    node.setAttribute(name, value);
  }
}

function named(node, text) {
  setText(node, text);
  setAttr(node, "aria-label", text);
  setAttr(node, "title", text);
}

class WindowUI {
  #started = false;
  #windows = new Map();
  #sheets = new WeakMap(); // window → its band sheet: null (loaded by windowUtils) or the fallback <link>
  #unsubscribe = null;
  #profile = null;
  #profileUnavailable = false;
  #temporary = false;
  #protection = "unknown";
  #protectionUnavailable = false; // the last read failed (not "not read yet": the first frame stays neutral)
  #refreshing = null;
  #generation = 0;
  #timer = null;
  #agent = null;
  #agentRevision = 0;
  #agentUnavailable = false;
  #guardCount = 0;
  #connected = []; // agents connected through the bridge now (UX5-I2)
  #actionError = false;
  #startPageChecked = false;

  start() {
    if (this.#started) {
      return;
    }
    this.#started = true;
    this.#generation++;
    for (const uri of [sidebarFocus, inContent]) {
      if (!sheets.sheetRegistered(uri, sheets.AGENT_SHEET)) {
        sheets.loadAndRegisterSheet(uri, sheets.AGENT_SHEET);
      }
    }
    const cui = lazy.CustomizableUI;
    cui.registerArea(AREA, { type: cui.TYPE_TOOLBAR, defaultPlacements: [WIDGET], defaultCollapsed: false });
    // Review 2026-11-09 F2: CustomizableUI builds every registered toolbar area when a window's
    // DOM has loaded. Without the band's toolbar in it by then, its handler threw and skipped the
    // rest of its work (the vertical tab strip's setup) in every window after the first.
    Services.catMan.addCategoryEntry(EARLY_WINDOW, EARLY_ENTRY, "NulavioWindow.prepareWindow", false, true);
    cui.createWidget({
      id: WIDGET, type: "custom", defaultArea: AREA, removable: false, overflows: false,
      localized: false, label: "Nulavio", onBuild: doc => {
        // Gecko custom widgets accept a XUL node. An hbox is deliberately not a
        // draggable CustomizeMode toolbaritem: its stop/review buttons keep receiving input.
        const item = doc.createXULElement("hbox");
        item.id = WIDGET;
        item.append(this.#build(doc));
        return item;
      },
    });
    cui.addListener(this);
    this.#addQuickAction();
    for (const topic of TOPICS) {
      Services.obs.addObserver(this, topic);
    }
    Services.prefs.addObserver(PREF_IMMERSIVE, this);
    Services.prefs.addObserver(PREF_FIRSTRUN, this);
    this.#unsubscribe = lazy.NulavioProfiles.subscribe(() => this.refresh());
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (win.gBrowserInit?.delayedStartupFinished) {
        this.#attach(win);
      }
    }
    this.#confirmOwnNewTab();
    this.#timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#timer.initWithCallback(() => this.refresh(), 1500, Ci.nsITimer.TYPE_REPEATING_SLACK);
    this.refresh();
  }

  observe(win, topic) {
    if (topic === "nsPref:changed") {
      for (const window of this.#windows.keys()) {
        this.#header(window);
        this.#paint(window);
      }
      return;
    }
    if (topic === "browser-delayed-startup-finished") {
      this.#attach(win);
    } else if (topic === "nulavio-ai-activity-changed") {
      // The assistant's task shows in every normal window (Q10); memory only: nothing is read or started.
      for (const window of this.#windows.keys()) {
        this.#paint(window);
      }
    } else {
      if (topic === "nulavio-ai-window-changed") {
        this.#agentRevision++;
        const warning = lazy.NulavioAI.windowWarning();
        if (warning) {
          this.#agent = this.#agent?.id === warning.id
            ? { ...this.#agent, ...warning, raw: this.#agent.raw || warning.raw }
            : { ...warning, name: warning.id, autonomy: null };
          for (const window of this.#windows.keys()) {
            this.#paint(window);
          }
        }
      }
      if (topic === "nulavio-ai-agent-files-changed") {
        // A refresh already under way may have read the agent's state before the change.
        this.refresh().finally(() => this.refresh());
        return;
      }
      this.refresh();
    }
  }

  #open(win, path) {
    const url = policy()?.getURL(path);
    if (url && !win.closed) {
      win.openTrustedLinkIn(url, "tab", { inBackground: false });
    }
  }

  /** The settings page at the pane that holds `section` ("profiles", "routing"), in this window (ADR 0011). */
  #settings(win, section) {
    try {
      ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings.openFor(win, section);
    } catch (e) {
      console.error(e);
    }
  }

  #profiles(win) {
    const action = lazy.ExtensionParent.apiManager.global.browserActionFor?.(policy()?.extension);
    const placement = lazy.CustomizableUI.getPlacementOfWidget("shell_nulavio_net-browser-action");
    if (action && placement && action.widget.forWindow(win).node) {
      action.triggerAction(win); // existing selector, including activeTab, keyboard and locked-profile routing
    } else {
      // A user can remove the original action without removing identity/safety.
      // Reuse the real selector as a Shell tab; never restore their customization.
      this.#open(win, "profiles/popup.html");
    }
  }

  #build(doc, compact = false) {
    const win = doc.defaultView;
    const row = element(doc, "div", "nv-band-row");
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", t("bandLabel"));
    if (compact) {
      row.id = "nulavio-fullscreen-notice";
    }
    const identity = button(doc, "nv-band-identity", () => this.#profiles(win));
    identity.append(element(doc, "span", "nv-band-flag"), element(doc, "span", "nv-band-name"));
    const protection = button(doc, "nv-band-protection", () => this.#settings(win, "profiles"));
    // D-UX19: next to the profile, while this tab shows a site one of the group's rules sent here.
    const route = button(doc, "nv-band-route", () => this.#settings(win, "routing"));
    route.hidden = true;
    const header = element(doc, "span", "nv-band-header");
    // ADR 0009: the site of this tab, from the engine's own state, shown while the address bar is
    // out of view (Immersive). Pressing it brings the address bar back with the keyboard in it.
    const origin = button(doc, "nv-band-origin", () => win.document.getElementById("Browser:OpenLocation")?.doCommand());
    origin.append(element(doc, "span", "nv-band-origin-state"), element(doc, "span", "nv-band-origin-sub"), element(doc, "span", "nv-band-origin-host"));
    origin.hidden = true;
    row.append(identity, protection, route, header, origin);
    const seals = element(doc, "div", "nv-band-seals");
    for (const kind of ["temporary", "private", "agent", "raw", "status", "activity"]) {
      const seal = element(doc, "span", `nv-band-seal nv-band-${kind}`);
      seal.hidden = true;
      seals.append(seal);
    }
    const guard = button(doc, "nv-band-seal nv-band-guard", () => this.#open(win, "guard/review.html"));
    // UX5-I2: an agent connected through the bridge, acting in its own AI Workspace (Settings say more).
    const connected = button(doc, "nv-band-seal nv-band-connected", () => this.#open(win, "settings/settings.html#ai"));
    const pause = button(doc, "nv-band-pause", () => this.#agentAction("pause"));
    const stop = button(doc, "nv-band-stop", () => this.#agentAction("stop"));
    // UX5-I (Q10): the assistant's task in this window. These only tighten; resuming stays in Settings.
    const taskStop = button(doc, "nv-band-task-stop", () => lazy.NulavioAI.assistantStopTask(win));
    const assistantPause = button(doc, "nv-band-assistant-pause", () => lazy.NulavioAI.pauseAssistant().catch(console.error));
    for (const control of [guard, connected, pause, stop, taskStop, assistantPause]) {
      control.hidden = true;
    }
    seals.append(guard, connected, pause, stop, taskStop, assistantPause);
    row.append(seals);
    return row;
  }

  async #agentAction(action) {
    try {
      if (action === "stop") {
        await lazy.NulavioAI.setStopped(true); // GLOBAL: the accessible and visible label says so
      } else if (this.#agent) {
        await lazy.NulavioAI.change(this.#agent.id, "pause", { paused: true });
      }
      this.#actionError = false;
    } catch (e) {
      this.#actionError = true;
      console.error(e);
    }
    await this.refresh();
  }

  // CSS filters the native radio group, but cannot change this default getter.
  // Override only the editor instance. Explicit/restored colours remain native.
  #groupPalette(win) {
    const editor = win.document.getElementById("tab-group-editor");
    if (!editor) {
      return () => {};
    }
    const own = Object.getOwnPropertyDescriptor(editor, "nextUnusedColor");
    const native = own?.get || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(editor), "nextUnusedColor").get;
    const get = () => {
      if (!Services.prefs.getBoolPref("nulavio.horizon.enabled", true)
          || win.document.documentElement.hasAttribute("lwtheme")
          || win.matchMedia("(forced-colors), (prefers-contrast)").matches) {
        return native.call(editor);
      }
      const colors = editor.constructor.COLORS.filter(color => !["orange", "purple", "red"].includes(color));
      const used = new Set(win.gBrowser.getAllTabGroups().map(group => group.color));
      return colors.find(color => !used.has(color)) || colors[Math.floor(Math.random() * colors.length)];
    };
    Object.defineProperty(editor, "nextUnusedColor", { configurable: true, get });
    return () => {
      if (Object.getOwnPropertyDescriptor(editor, "nextUnusedColor")?.get === get) {
        if (own) {
          Object.defineProperty(editor, "nextUnusedColor", own);
        } else {
          delete editor.nextUnusedColor;
        }
      }
    };
  }

  // ADR 0011: the Shell's pages are the browser's own interface (unlock, the Guard's review, the new tab), so
  // the address bar names them as it names the engine's internal pages ("Nulavio") instead of "Extensão
  // (Nulavio Shell)". Only the identity label, its icon and what its panel calls the page change: the pages
  // stay unprivileged, the address stays, and every other extension keeps the engine's label. The Shell is
  // known by its id and by being shipped with the application, never by a name a page or an add-on can give.
  // Done here and not as an engine patch: it is what a built-in add-on can do (browser/patches/series).
  #ownPagesIdentity(win) {
    const handler = win.gIdentityHandler;
    const refresh = handler?._refreshIdentityIcons;
    const connection = handler?.getConnectionSecurityInformation;
    if (typeof refresh !== "function" || typeof connection !== "function") {
      return () => {}; // the engine changed shape: its own label stays
    }
    const own = () => {
      const policy = handler._pageExtensionPolicy;
      return policy?.id === SHELL && !!policy.extension?.isAppProvided;
    };
    const named = function () {
      refresh.call(this);
      if (!own()) {
        return;
      }
      const box = win.document.getElementById("identity-box");
      const label = win.document.getElementById("identity-icon-label");
      const brand = win.document.getElementById("bundle_brand")?.getString("brandShorterName");
      if (!box || !label || !brand) {
        return;
      }
      box.className = "chromeUI";
      label.setAttribute("value", brand);
      label.collapsed = false;
      win.document.getElementById("identity-icon")?.setAttribute("tooltiptext", "");
    };
    const said = function () {
      return own() ? "chrome" : connection.call(this);
    };
    handler._refreshIdentityIcons = named;
    handler.getConnectionSecurityInformation = said;
    handler.refreshIdentityBlock?.();
    return () => {
      if (handler._refreshIdentityIcons === named) {
        handler._refreshIdentityIcons = refresh;
      }
      if (handler.getConnectionSecurityInformation === said) {
        handler.getConnectionSecurityInformation = connection;
      }
      if (!win.closed) {
        handler.refreshIdentityBlock?.();
      }
    };
  }

  /** For each new browser window, before CustomizableUI builds its toolbars: the band's toolbar. */
  prepareWindow(win) {
    const doc = win.document;
    if (this.#started && doc.documentElement.getAttribute("windowtype") === "navigator:browser" && !doc.getElementById(AREA)) {
      // The sheet before the toolbar, as in #attach: the band's first frame is its final one.
      this.#loadSheet(win);
      this.#insertToolbar(doc);
    }
  }

  /*
   * UX3H (QA M-2): load the band's sheet synchronously, before the band exists, so the band's
   * first frame is already its final one. A <link> loads asynchronously: on the first launch the
   * band showed for ~100 ms as a separate row (+54 px) before it joined the navigation row. The
   * <link> stays only as a fallback. Once per window: prepareWindow or #attach, whichever is first.
   */
  #loadSheet(win) {
    if (this.#sheets.has(win)) {
      return this.#sheets.get(win);
    }
    let sheet = null;
    try {
      win.windowUtils.loadSheetUsingURIString(bandSheet.spec, win.windowUtils.AUTHOR_SHEET);
    } catch (e) {
      console.error(e);
      sheet = element(win.document, "link");
      sheet.rel = "stylesheet";
      sheet.href = bandSheet.spec;
      win.document.head.append(sheet);
    }
    this.#sheets.set(win, sheet);
    return sheet;
  }

  #insertToolbar(doc) {
    const bar = doc.createXULElement("toolbar");
    bar.id = AREA;
    bar.setAttribute("customizable", "true");
    bar.setAttribute("mode", "icons");
    bar.setAttribute("defaultset", WIDGET);
    bar.setAttribute("toolbarname", "Nulavio");
    // Above both tab orientations; insertion leaves every native node in place.
    doc.getElementById("navigator-toolbox").insertBefore(bar, doc.getElementById("TabsToolbar"));
    return bar;
  }

  #attach(win) {
    if (!this.#started || this.#windows.has(win) || !win.gBrowser || win.closed) {
      return;
    }
    const doc = win.document;
    const sheet = this.#loadSheet(win);
    // The toolbar is usually there already (prepareWindow); a window that was open before the
    // Shell started gets it now. Registering a toolbar CustomizableUI already built does nothing.
    const bar = doc.getElementById(AREA) ?? this.#insertToolbar(doc);
    lazy.CustomizableUI.registerToolbarNode(bar);
    const compact = this.#build(doc, true);
    const fullscreen = element(doc, "div");
    fullscreen.id = "nulavio-fullscreen";
    fullscreen.tabIndex = 0;
    fullscreen.setAttribute("role", "group");
    fullscreen.setAttribute("aria-label", t("bandLabel"));
    const line = element(doc, "div", "nv-fullscreen-line");
    line.setAttribute("aria-hidden", "true");
    for (const kind of ["normal", "temporary", "private", "agent", "raw", "guard", "activity"]) {
      const segment = element(doc, "span", `nv-fullscreen-${kind}`);
      segment.hidden = kind !== "normal";
      line.append(segment);
    }
    fullscreen.append(line, compact);
    doc.getElementById("browser").before(fullscreen);
    const header = () => {
      this.#noticeHold(win); // another tab, another page: its own notification bar, or none
      this.#header(win);
    };
    const progress = {
      onLocationChange: header,
      onSecurityChange: header,
      onStateChange: (_progress, _request, flags) => {
        if (flags & Ci.nsIWebProgressListener.STATE_START) {
          // Clear synchronously before a new principal commits. The current principal
          // is consulted again on location/stop; no async label can win a tab race.
          for (const node of this.#rows(win)) {
            named(node.querySelector(".nv-band-header"), "");
          }
          this.#windows.get(win)?.bar.removeAttribute("nv-named");
          this.#markOwnPagePending(win);
        } else if (flags & Ci.nsIWebProgressListener.STATE_STOP) {
          header();
        }
      },
      QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]),
    };
    // ADR 0009: where the pointer brings the tab list back in Immersive (window-band.css).
    const edge = element(doc, "div");
    edge.id = "nulavio-immersive-edge";
    edge.setAttribute("aria-hidden", "true");
    doc.getElementById("browser").prepend(edge);
    win.gBrowser.addProgressListener(progress);
    win.gBrowser.tabContainer.addEventListener("TabSelect", header);
    // ADR 0009: a panel or a menu anchored on the toolbar or on the tab list keeps it shown for its whole life.
    const popup = event => this.#popupHold(win, event);
    for (const type of ["popupshowing", "popupshown", "popuphidden"]) {
      win.addEventListener(type, popup, true);
    }
    // ...and a device that starts or stops being shared in any tab is decided at once.
    const sharing = event => event.detail?.changed?.includes("sharing") && this.#applyImmersive(win);
    win.gBrowser.tabContainer.addEventListener("TabAttrModified", sharing);
    // ...as is a prompt that opens or closes on a tab (the engine's tab dialogs), once more after the event
    // because the dialog is still listed while "dialogclose" is dispatched.
    const dialog = () => {
      this.#applyImmersive(win);
      win.setTimeout(() => this.#windows.has(win) && this.#applyImmersive(win), 0);
    };
    for (const type of ["dialogopen", "dialogclose"]) {
      win.addEventListener(type, dialog, true);
    }
    // ...and a download that needs attention, which only marks its button.
    const downloads = new win.MutationObserver(() => this.#downloadHold(win));
    const downloadsButton = doc.getElementById("downloads-button");
    if (downloadsButton) {
      downloads.observe(downloadsButton, { attributes: true, attributeFilter: ["attention"] });
    }
    // ...and a notification bar: the engine's (a blocked pop-up, a page opened past a Safe Browsing warning, a
    // sign-in network) and Nulavio's own (the Guard's). They live in a toolbar of their own, which would go out
    // of view with the others.
    const notices = new win.MutationObserver(() => this.#noticeHold(win));
    const noticesBar = doc.getElementById("notifications-toolbar");
    if (noticesBar) {
      notices.observe(noticesBar, { childList: true, subtree: true });
    }
    // ADR 0009, #238: how tall the toolbars that hang below the band are, so the tab list starts under them while
    // they are shown instead of under the band, where they covered its top (window-band.css).
    const toolbarSize = () => {
      const bars = doc.querySelectorAll("#navigator-toolbox > toolbar:not(#nulavio-band)");
      const height = [...bars].reduce((sum, each) => sum + each.getBoundingClientRect().height, 0);
      doc.documentElement.style.setProperty("--nulavio-immersive-toolbar-size", `${Math.ceil(height)}px`);
    };
    const sizes = new win.ResizeObserver(toolbarSize);
    for (const each of doc.querySelectorAll("#navigator-toolbox > toolbar:not(#nulavio-band)")) {
      sizes.observe(each);
    }
    // ADR 0009, #239: in Immersive the toolbar stays while the keyboard is in it. The engine leaves the focus in the
    // address bar after a click on something that takes none (the tab list, the band, an in-process page such as
    // Settings); with the mode off that changes nothing on screen, with it on the toolbar stayed over the page.
    // A click outside the toolbar, with nothing anchored on it open, gives the focus to the page instead, as a
    // click on a web page does. The window root also sees the clicks inside in-process pages.
    const outside = event => {
      const root = doc.documentElement;
      if (!event.isTrusted || event.button !== 0 || !root.hasAttribute("nulavio-immersive") || root.hasAttribute("nulavio-immersive-hold")) {
        return;
      }
      const toolbox = doc.getElementById("navigator-toolbox");
      const target = event.composedTarget ?? event.target;
      const inChrome = target?.ownerDocument === doc;
      if (inChrome && ((toolbox?.contains(target) && !bar.contains(target)) || target.closest?.("panel, menupopup"))) {
        return; // the toolbar itself, or a popup
      }
      if (inChrome && bar.contains(target) && target.closest?.("button, toolbarbutton, [role=button], a")) {
        return; // a control of the band: it decides where the keyboard goes
      }
      if (!toolbox?.matches(":focus-within")) {
        return;
      }
      // After the engine has handled the click (a tab it selects, a page it focuses), only if the keyboard is still there.
      win.setTimeout(() => {
        if (this.#windows.has(win) && toolbox.matches(":focus-within") && root.hasAttribute("nulavio-immersive")) {
          win.gBrowser.selectedBrowser.focus();
        }
      }, 0);
    };
    win.windowRoot.addEventListener("mousedown", outside, true);
    const unload = () => this.#detach(win);
    win.addEventListener("unload", unload, { once: true });
    const reveal = () => this.#showNotice(win);
    const pointer = event => {
      if (event.isTrusted && event.clientY <= 3) {
        reveal();
      }
    };
    fullscreen.addEventListener("focusin", reveal);
    fullscreen.addEventListener("focusout", reveal);
    win.addEventListener("mousemove", pointer, true);
    const screenObserver = new win.MutationObserver(reveal);
    screenObserver.observe(doc.documentElement, { attributes: true, attributeFilter: ["inFullscreen", "inDOMFullscreen"] });
    // ADR 0009: the band's origin follows the engine's identity verdict as soon as it changes.
    const identityObserver = new win.MutationObserver(header);
    const identityBox = doc.getElementById("identity-box");
    if (identityBox) {
      identityObserver.observe(identityBox, { attributes: true, attributeFilter: ["class"] });
    }
    this.#windows.set(win, { bar, compact, fullscreen, line, sheet, progress, header, unload, pointer, screenObserver, identityObserver, edge,
      popup, sharing, dialog, downloads, notices, sizes, outside, holds: new Map(), named: false, noticeTimer: null, safety: null, restoreGroupPalette: this.#groupPalette(win),
      restoreIdentity: this.#ownPagesIdentity(win) });
    this.#downloadHold(win);
    this.#noticeHold(win);
    this.#paint(win);
    this.#unifyStartPage(win);
  }

  // QA M-2 (UX3E; UX3F A3): the Shell's new tab is the browser's own, so the engine's "Your new tab has
  // changed" notice must not cover it. This records, for the Shell's id only, the same
  // confirmation the notice's "Keep changes" button writes (ExtensionControlledPopup,
  // type "newTabNotification"); the notice re-checks it before opening. Any other add-on
  // that takes over the new tab still gets the notice, and nothing else is affected.
  #confirmOwnNewTab() {
    const store = lazy.ExtensionSettingsStore;
    store.initialize().then(() => {
      if (this.#started && !store.getSetting("newTabNotification", SHELL)?.value) {
        return store.addSetting(SHELL, "newTabNotification", SHELL, true, () => false);
      }
      return null;
    }).catch(console.error);
  }

  // QA M-2 (UX3E; UX3F A3): one new tab. The session's first window, when it starts on the
  // engine's default home page, shows the Shell's new tab in that same tab, so the
  // first window of a new profile already offers the one-time choices, and startup
  // and Ctrl+T look the same. Only the first window, and only an untouched start:
  // a single tab, no history, the home page pref at its default, the Shell's page
  // still the new tab, a non-private window. Later windows (Ctrl+N), links from
  // other apps, session restore and a home page the person set are left alone,
  // and the address bar stays empty (the new tab is an initial page).
  #unifyStartPage(win) {
    if (this.#startPageChecked) {
      return;
    }
    this.#startPageChecked = true;
    const url = policy()?.getURL("newtab/newtab.html");
    if (!url || lazy.PrivateBrowsingUtils.isWindowPrivate(win)
        || Services.prefs.prefHasUserValue("browser.startup.homepage")) {
      return;
    }
    Promise.resolve(win.gBrowserInit?.uriToLoadPromise).then(uri => {
      const start = Array.isArray(uri) ? (uri.length === 1 ? uri[0] : null) : uri;
      const browser = win.gBrowser?.selectedBrowser;
      // UX3G N-4 (provisional): only new profiles; profiles from earlier builds keep about:home.
      if (start !== "about:home" || win.closed || !this.#windows.has(win) || win.gBrowser.tabs.length !== 1
          || !lazy.NulavioLayout.startsOnShellTab()
          || lazy.AboutNewTab.newTabURL !== url || browser.canGoBack || browser.canGoForward
          || !["about:home", "about:blank"].includes(browser.currentURI?.spec)) {
        return;
      }
      // Least privilege: the Shell page loads with the Shell's own principal, not the system's.
      const principal = policy()?.extension?.principal;
      if (!principal) {
        return;
      }
      browser.fixupAndLoadURIString(url, {
        triggeringPrincipal: principal,
        loadFlags: Ci.nsIWebNavigation.LOAD_FLAGS_REPLACE_HISTORY,
      });
    }).catch(console.error);
  }

  #showNotice(win) {
    const state = this.#windows.get(win);
    if (!state || !win.document.documentElement.matches("[inFullscreen], [inDOMFullscreen]")) {
      return;
    }
    win.clearTimeout(state.noticeTimer);
    state.fullscreen.setAttribute("notice", "");
    const hide = () => {
      // A keyboard user keeps the controls until focus leaves, without a moving target.
      if (!state.fullscreen.contains(win.document.activeElement)) {
        state.fullscreen.removeAttribute("notice");
      }
      state.noticeTimer = null;
    };
    state.noticeTimer = win.setTimeout(hide, 4000);
  }

  #rows(win) {
    return [win.document.getElementById(WIDGET)?.firstElementChild, this.#windows.get(win)?.compact].filter(Boolean);
  }

  #header(win) {
    let text = "";
    let trust = false;
    let stage = false;
    try {
      const browser = win.gBrowser.selectedBrowser;
      const global = browser.browsingContext.currentWindowGlobal;
      const principal = global?.documentPrincipal;
      if (!browser.webProgress.isLoadingDocument && principal?.addonPolicy?.id === SHELL) {
        const url = new URL(global.documentURI.spec);
        const key = SURFACES[url.pathname];
        if (key && url.protocol === "moz-extension:" && url.host === new URL(policy().getURL("")).host
            && browser.currentURI.spec === global.documentURI.spec) {
          text = t("bandSystemPage", [t(key)]);
          trust = !PLAIN_SURFACES.has(key);
          // The first run's welcome is the Shell's own new tab in a genuinely new profile: while it is the
          // selected tab the window shows the band and that page only (the band still names it).
          stage = key === "newtabTitle" && !lazy.PrivateBrowsingUtils.isWindowPrivate(win) && lazy.NulavioPrivacy.firstRun().active;
          if (stage) {
            text = t("bandSystemPage", [t("bandSurfaceWelcome")]);
          }
        }
      }
    } catch {
      // Uncommitted/destroyed globals are never trusted.
    }
    for (const row of this.#rows(win)) {
      named(row.querySelector(".nv-band-header"), text);
    }
    const state = this.#windows.get(win);
    state?.bar.toggleAttribute("nv-named", trust);
    const staged = Boolean(state && state.stage !== stage);
    if (staged) {
      state.stage = stage;
      win.document.documentElement.toggleAttribute("nulavio-stage", stage);
    }
    this.#origin(win, Boolean(text));
    if (staged) {
      state.bar.toggleAttribute("nv-neutral", this.#neutral(win));
      if (stage && !state.stageFocused) {
        // The stage's question is in the page: the keyboard starts there, not in an address field that is out of
        // view. Once per window: a tab the person opens later (Ctrl+T) keeps the keyboard in the address field,
        // which shows the toolbar, so what they type goes where they meant it.
        state.stageFocused = true;
        win.gBrowser.selectedBrowser.focus();
      }
    }
    this.#markOwnPagePending(win);
    this.#routeNotice(win);
  }

  /** Immersive (ADR 0009): the mode is on for this window (the person's switch, or the first run's stage). */
  #immersiveWanted(win) {
    return Services.prefs.getBoolPref(PREF_IMMERSIVE, false) || Boolean(this.#windows.get(win)?.stage);
  }

  /**
   * Why a window that wants Immersive shows its full chrome anyway (ADR 0009, decision 6): the first
   * reason that applies, or "". Whenever something must be seen in full, or the band cannot vouch
   * for the page, the toolbar stays.
   */
  #immersiveBlock(win) {
    if (this.#agent) {
      return "agent"; // an AI Workspace, raw automation included
    }
    if (!win.toolbar.visible) {
      return "popup"; // a pop-up or any window without the full toolbar
    }
    // A camera, a microphone or a screen shared from any tab of this window, paused or not: the engine's own
    // indicators are the cue, so the toolbar stays. Read from what those indicators are drawn from (the
    // browser's sharing state; the tab's attribute goes away while a capture is paused).
    if ([...win.gBrowser.tabs].some(tab => tab.linkedBrowser?._sharingState?.webRTC?.sharing || tab.hasAttribute("sharing"))) {
      return "sharing";
    }
    // A prompt on the selected tab (HTTP authentication, alert, confirm, before-unload). For a cross-site
    // authentication request the engine rewrites the address bar and the tab's label to the site that asks
    // (currentAuthPromptURI): that must be seen, and the band's site would be the wrong one.
    try {
      const browser = win.gBrowser.selectedBrowser;
      const box = browser.tabDialogBox;
      if (browser.currentAuthPromptURI || box?._tabDialogManager?.hasDialogs || box?._contentDialogManager?.hasDialogs) {
        return "prompt";
      }
    } catch (e) {
      console.error("Nulavio band: prompt state", e);
      return "prompt"; // not known: as if one were open
    }
    if (!this.#windows.get(win)?.named) {
      return "page"; // a document the band has no defined name for (about:blank, data:, blob:, view-source:)
    }
    if (!this.#documentIsThere(win)) {
      return "page"; // the address is shown before its document: a tab being restored, an error page
    }
    return "";
  }

  /**
   * Whether the document in the selected tab is the one its address names. The band names the address the
   * engine shows, as the address bar does, and a tab being restored shows its address before its document is
   * there (the page is still about:blank, for as long as the site takes to answer). An error page keeps the
   * address of what failed. Until the document is that site's, the toolbar stays (ADR 0009, decision 6).
   */
  #documentIsThere(win) {
    try {
      const browser = win.gBrowser.selectedBrowser;
      const shown = browser.currentURI;
      const there = browser.browsingContext?.currentWindowGlobal?.documentURI;
      if (!shown || !there) {
        return false;
      }
      if (shown.schemeIs("http") || shown.schemeIs("https")) {
        return there.scheme === shown.scheme && there.hostPort === shown.hostPort;
      }
      return there.spec.split(/[?#]/)[0] === shown.spec.split(/[?#]/)[0];
    } catch {
      return false; // not known: as if it were not there
    }
  }

  #immersive(win) {
    return this.#immersiveWanted(win) && !this.#immersiveBlock(win);
  }

  /** Draw the decision on the window: the mode, why it is held back, and what keeps the chrome shown. */
  #applyImmersive(win) {
    const state = this.#windows.get(win);
    if (!state) {
      return;
    }
    const root = win.document.documentElement;
    const wanted = this.#immersiveWanted(win);
    const block = wanted ? this.#immersiveBlock(win) : "";
    root.toggleAttribute("nulavio-immersive", wanted && !block);
    const mark = (name, value) => (value ? setAttr(root, name, value) : root.removeAttribute(name));
    mark("nulavio-immersive-off", block);
    for (const [node] of state.holds) {
      if (!node.isConnected || node.state === "closed") {
        state.holds.delete(node); // a popup that never opened, or went away without its event
      }
    }
    mark("nulavio-immersive-hold", [...new Set(state.holds.values())].sort().join(" "));
    const neutral = this.#neutral(win);
    if (state.bar.hasAttribute("nv-neutral") !== neutral) {
      state.bar.toggleAttribute("nv-neutral", neutral);
    }
  }

  /** A panel or menu anchored on the toolbar or on the tab list: that part stays shown from before the
      engine positions it until it is gone. A menu on the page (no anchor in the chrome) holds nothing. */
  #popupHold(win, event) {
    const state = this.#windows.get(win);
    const node = event.target;
    if (!state || event.currentTarget !== win || !["panel", "menupopup"].includes(node?.localName)) {
      return;
    }
    if (event.type === "popuphidden") {
      if (state.holds.delete(node)) {
        this.#applyImmersive(win);
      }
      return;
    }
    const anchor = node.anchorNode ?? node.triggerNode ?? node.parentNode;
    const doc = win.document;
    const part = doc.getElementById("navigator-toolbox")?.contains(anchor) ? "toolbar"
      : doc.getElementById("sidebar-container")?.contains(anchor) ? "tabs" : "";
    if (part && state.holds.get(node) !== part) {
      state.holds.set(node, part);
      this.#applyImmersive(win);
      // A popup whose opening was cancelled sends no "popuphidden": look again once this event is over.
      win.setTimeout(() => this.#windows.has(win) && this.#applyImmersive(win), 0);
    }
  }

  /** A notification bar in this window or on the selected tab: the toolbar stays shown, and the bar with it,
      until it is closed. A bar on a tab in the background holds nothing until that tab is selected. */
  #noticeHold(win) {
    const state = this.#windows.get(win);
    const bar = win.document.getElementById("notifications-toolbar");
    if (!state || !bar) {
      return;
    }
    let shown;
    try {
      const boxes = [win.gNotificationBox, win.gBrowser.readNotificationBox(win.gBrowser.selectedBrowser)];
      shown = boxes.some(box => box?.allNotifications.length);
    } catch (e) {
      console.error("Nulavio band: notification bars", e);
      shown = true; // not known: as if one were shown
    }
    if (shown !== state.holds.has(bar)) {
      if (shown) {
        state.holds.set(bar, "toolbar");
      } else {
        state.holds.delete(bar);
      }
      this.#applyImmersive(win);
    }
  }

  /** A download that needs the person's attention (blocked, or flagged as dangerous) marks its toolbar button
      and opens nothing: the toolbar stays shown until the mark is gone (the person opened the downloads). */
  #downloadHold(win) {
    const state = this.#windows.get(win);
    const button = win.document.getElementById("downloads-button");
    if (!state || !button) {
      return;
    }
    const needs = ["warning", "severe"].includes(button.getAttribute("attention"));
    if (needs !== state.holds.has(button)) {
      if (needs) {
        state.holds.set(button, "toolbar");
      } else {
        state.holds.delete(button);
      }
      this.#applyImmersive(win);
    }
  }

  /** The selected tab's site for the band: the committed document's host as the engine displays it
      (IDN rules included), its registrable part apart, and the connection state in words when it
      is not secure. Never from the page; nothing while a load is committing; Nulavio's own pages
      have the band's trusted name instead. */
  #origin(win, ownPage) {
    let sub = "";
    let host = "";
    let state = "";
    try {
      const browser = win.gBrowser.selectedBrowser;
      const uri = browser.currentURI;
      if (!ownPage && uri) {
        if (uri.schemeIs("http") || uri.schemeIs("https")) {
          host = uri.displayHost;
          try {
            const base = Services.eTLD.getBaseDomainFromHost(host);
            if (host.endsWith(base) && host.length > base.length) {
              sub = host.slice(0, host.length - base.length);
              host = base;
            }
          } catch {
            // An IP address or a single label: the whole host is the site.
          }
          // An IPv6 address is shown between brackets, as in an address: without them its last group and a
          // port could not be told apart.
          if (host.includes(":")) {
            host = `[${host}]`;
          }
          // A port that is not the scheme's own is part of what the site is: never left out.
          if (uri.port !== -1) {
            host += `:${uri.port}`;
          }
          // The verdict is the engine's own: the classes its identity handler puts on the address
          // bar's identity box (verified, local, or anything else), never a second opinion. A certificate the
          // person accepted with an exception is "verified" there with a second class, a warning on its padlock
          // and "connection not secure" in its panel: not fine here either.
          const identity = win.document.getElementById("identity-box")?.classList;
          const fine = (identity?.contains("verifiedDomain") && !identity.contains("certUserOverridden"))
            || identity?.contains("localResource");
          state = fine ? "" : t("bandOriginNotSecure");
        } else if (uri.schemeIs("file")) {
          host = t("bandOriginFile");
        } else if (uri.schemeIs("about") && uri.spec.split(/[?#]/)[0] !== "about:blank") {
          // "about:blank#x" and "about:blank?x" are about:blank too (a document that inherits its opener).
          host = uri.spec.split(/[?#]/)[0];
        }
        // Anything else (about:blank, data:, blob:, view-source:) has no defined name: full chrome.
      }
    } catch {
      sub = host = state = ""; // an uncommitted or destroyed tab names no site
    }
    for (const row of this.#rows(win)) {
      const node = row.querySelector(".nv-band-origin");
      setText(node.querySelector(".nv-band-origin-state"), state);
      setText(node.querySelector(".nv-band-origin-sub"), sub);
      setText(node.querySelector(".nv-band-origin-host"), host);
      const label = host ? t(state ? "bandOriginNamedNotSecure" : "bandOriginNamed", [sub + host]) : "";
      setAttr(node, "aria-label", label);
      setAttr(node, "title", label);
      setAttr(node, "data-secure", state ? "false" : "true");
      if (node.hidden !== !host) {
        node.hidden = !host;
      }
    }
    const window = this.#windows.get(win);
    if (window) {
      window.named = ownPage || Boolean(host);
      this.#applyImmersive(win);
    }
  }

  /** A window with no alert may carry the band inside the navigation row (UX3G A1). A routing notice
      also gives it back its own row, so the notice never squeezes the profile out (review F16). So does
      a failed read of the profile or of its protection: "Identidade do perfil indisponível" and
      "Proteção desconhecida" are shown whole, not cut to the column (audit 2026-11 W-02). */
  #neutral(win) {
    return !this.#immersive(win) && !this.#temporary && !lazy.PrivateBrowsingUtils.isWindowPrivate(win) && !this.#agent
      && this.#guardCount === 0 && !this.#actionError && !this.#windows.get(win)?.routed
      && !this.#profileUnavailable && !this.#protectionUnavailable
      && !lazy.NulavioAI.activityState(win) && !this.#connected.some(c => c.agent !== this.#agent?.id);
  }

  /** "Aberto pela sua regra · Mudar" (D-UX19): only what the group's own rules say about this tab. */
  #routeNotice(win) {
    let ruleId = null;
    try {
      ruleId = lazy.PrivateBrowsingUtils.isWindowPrivate(win) ? null : lazy.NulavioRouting.arrivedBy(win.gBrowser.selectedBrowser);
    } catch (e) {
      console.error(e);
    }
    const state = this.#windows.get(win);
    if (state && state.routed !== Boolean(ruleId)) {
      state.routed = Boolean(ruleId);
      state.bar.toggleAttribute("nv-neutral", this.#neutral(win));
    }
    // UX6: a link the default destination sent says that, not "your rule".
    const name = this.#profile?.name || t("bandProfileDefault");
    const label = ruleId === "default" ? t("bandRoutedDefaultNamed", [name]) : ruleId ? t("bandRoutedNamed", [name]) : "";
    for (const row of this.#rows(win)) {
      const node = row.querySelector(".nv-band-route");
      if (node.hidden !== !ruleId) {
        node.hidden = !ruleId;
      }
      setText(node, ruleId === "default" ? t("bandRoutedDefault") : ruleId ? t("bandRouted") : "");
      setAttr(node, "aria-label", label);
      setAttr(node, "title", label);
    }
  }

  // UX3G: for a moment after Ctrl+T the address bar already holds the Shell's new tab URL
  // while the tab still shows its initial, empty about:blank, and the identity box calls
  // that "Not Secure". Mark only that state: the Shell's exact URL over an initial empty
  // document with no web origin. Any committed page (web, error or the Shell's own) clears
  // it, so a web page's security indicator is never affected (window-band.css).
  #markOwnPagePending(win) {
    let pending = false;
    try {
      const browser = win.gBrowser.selectedBrowser;
      const global = browser.browsingContext.currentWindowGlobal;
      const own = policy()?.getURL("newtab/newtab.html");
      pending = Boolean(own && global) && browser.currentURI?.spec === own
        && global.isInitialDocument && global.documentURI?.spec === "about:blank"
        && global.documentPrincipal?.addonPolicy?.id !== SHELL;
    } catch {
      pending = false;
    }
    win.document.documentElement.toggleAttribute("nulavio-own-page-pending", pending);
  }

  #paint(win) {
    const profile = this.#profile;
    const agent = this.#agent;
    const workspace = agent?.target.kind === "workspace";
    const name = this.#temporary ? t("profilesTemporaryShort") : workspace ? agent.name
      : this.#profileUnavailable && profile?.name ? `? ${profile.name}`
        : profile?.name || agent?.target.profile
          // No registered profile is the ordinary default profile; only a failed read is "unavailable".
          || t(this.#profileUnavailable ? "bandProfileUnavailable" : "bandProfileDefault");
    const protection = t(this.#protection === "unlocked" ? "bandProtected" : this.#protection === "plain" ? "bandUnprotected" : "bandProtectionUnknown");
    const privateWindow = lazy.PrivateBrowsingUtils.isWindowPrivate(win);
    const root = win.document.documentElement;
    root.toggleAttribute("nulavio-window-agent", Boolean(agent));
    root.toggleAttribute("nulavio-window-raw", Boolean(agent?.raw));
    this.#applyImmersive(win);
    const state = this.#windows.get(win);
    const activity = lazy.NulavioAI.activityState(win);
    const kinds = { normal: true, temporary: this.#temporary, private: privateWindow,
      agent: Boolean(agent), raw: Boolean(agent?.raw), guard: this.#guardCount > 0, activity: Boolean(activity) };
    for (const [kind, visible] of Object.entries(kinds)) {
      state.line.querySelector(`.nv-fullscreen-${kind}`).hidden = !visible;
    }
    // UX3G A1: a window with no alert (not private, temporary, agent, Guard or a failed
    // action) may carry the band inside the navigation row (window-band.css); any alert
    // gives it back its own strong row at once.
    state.bar.toggleAttribute("nv-neutral", this.#neutral(win));
    const safety = JSON.stringify([name, this.#protection, privateWindow, this.#temporary, agent, this.#guardCount, this.#actionError]);
    if (state.safety !== safety) {
      state.safety = safety;
      this.#showNotice(win);
    }
    for (const row of this.#rows(win)) {
      row.dataset.temporary = String(this.#temporary);
      row.dataset.private = String(privateWindow);
      row.dataset.agent = String(Boolean(agent));
      row.dataset.workspace = String(Boolean(workspace));
      row.dataset.raw = String(Boolean(agent?.raw));
      // Which outline glyph the protection and the agent status draw (window-band.css); words stay the cue.
      row.dataset.protection = this.#protection === "unlocked" ? "unlocked" : this.#protection === "plain" ? "plain" : "unknown";
      row.dataset.agentStatus = this.#actionError ? "failed" : this.#agentUnavailable ? "unknown"
        : agent?.stopped ? "stopped" : agent?.revoked ? "revoked" : "paused";
      const identity = row.querySelector(".nv-band-identity");
      const color = profile?.color ?? "slate";
      const fill = workspace ? "var(--nv-color-security-agent-ink)" : `var(--nv-color-identity-${color})`;
      if (identity.style.getPropertyValue("--profile-fill") !== fill) {
        identity.style.setProperty("--profile-fill", fill);
        // Calmaria: the neutral row draws the soft tile; alert rows keep the strong fill above.
        identity.style.setProperty("--profile-tile", `var(--nv-color-identityTile-${color})`);
        identity.style.setProperty("--profile-glyph", `var(--nv-color-identityGlyph-${color})`);
      }
      setAttr(identity, "aria-label", t("profilesButtonNamed", [name]));
      setAttr(identity, "title", name);
      const glyph = row.querySelector(".nv-band-flag");
      // The profile's own glyph, the hourglass of a temporary profile or the AI Workspace's; else its
      // initial, and the person glyph for a name with no letter (never "?": that means unknown).
      const d = workspace ? lazy.SPECIAL_GLYPHS.workspace
        : this.#temporary ? lazy.SPECIAL_GLYPHS.temporary : lazy.AVATAR_GLYPHS[profile?.avatar] ?? null;
      const letter = d ? null : lazy.profileInitial(name);
      if (d || !letter) {
        showGlyph(glyph, d ?? lazy.SPECIAL_GLYPHS.person);
      } else if (glyph.firstElementChild || glyph.textContent !== letter) {
        glyph.textContent = letter;
      }
      setAttr(glyph, "aria-hidden", "true");
      setText(row.querySelector(".nv-band-name"), name);
      // "Protegido" fits the Lateral column; the whole "Protegido · desbloqueado" is its name and title.
      const protectionNode = row.querySelector(".nv-band-protection");
      setText(protectionNode, this.#protection === "unlocked" ? t("bandProtectedShort") : protection);
      setAttr(protectionNode, "aria-label", protection);
      setAttr(protectionNode, "title", protection);
      const seal = (kind, visible, text) => {
        const node = row.querySelector(`.nv-band-${kind}`);
        const hadFocus = node === win.document.activeElement;
        if (node.hidden !== !visible) {
          node.hidden = !visible;
        }
        named(node, text);
        if (!visible && hadFocus) {
          row.querySelector(".nv-band-stop").focus();
        }
      };
      seal("temporary", this.#temporary, t("bandTemporary"));
      seal("private", privateWindow, t("bandPrivate"));
      const level = agent?.autonomy ? t(`aiLevel_${agent.autonomy}`) : t("bandLevelUnknown");
      const agentName = agent?.name ?? "";
      const agentText = agent?.target.kind === "profile"
        ? t("bandAgentProfile", [agentName, agent.target.profile || name, level])
        : t("bandAgentWorkspace", [agentName, level]);
      seal("agent", Boolean(agent), agentText);
      seal("raw", Boolean(agent?.raw), t("bandRaw"));
      seal("status", Boolean(agent && (agent.paused || agent.stopped || agent.revoked || this.#agentUnavailable || this.#actionError)),
        t(this.#actionError ? "bandStopFailed" : this.#agentUnavailable ? "bandAgentUnknown" : agent?.stopped ? "aiStoppedNow" : agent?.revoked ? "aiRevoked" : "aiPaused"));
      seal("guard", this.#guardCount > 0, t("bandGuard", [String(this.#guardCount)]));
      seal("pause", Boolean(agent && !agent.paused && !agent.stopped && !agent.revoked), t("bandPauseAgent", [agentName]));
      seal("stop", Boolean(agent), t("bandStopAll"));
      // A count only once an action ran: never "0 ações" (refused or stopped calls are not actions).
      const acting = !activity?.steps ? t("bandAssistantActingNone")
        : activity.steps === 1 ? t("bandAssistantActingOne") : t("bandAssistantActing", [String(activity.steps)]);  // prettier-ignore
      seal("activity", Boolean(activity), activity?.stopping ? t("bandAssistantStopping") : activity?.waiting ? t("bandAssistantWaiting") : acting);
      row.dataset.activity = String(Boolean(activity));
      // Not where an agent drives this window: it would learn which other agents are connected (review UX5-I F5).
      const others = privateWindow || agent ? [] : this.#connected.filter(c => c.agent !== agent?.id);
      seal("connected", others.length > 0, others.length === 1 ? t("bandAgentConnected", [others[0].name])
        : t("bandAgentsConnected", [String(others.length)]));  // prettier-ignore
      seal("task-stop", Boolean(activity && !activity.stopping), t("bandTaskStop"));
      seal("assistant-pause", Boolean(activity && !activity.stopping), t("bandAssistantPause"));
    }
    this.#header(win);
  }

  refresh() {
    if (!this.#started) {
      return Promise.resolve();
    }
    if (this.#refreshing) {
      return this.#refreshing;
    }
    const generation = this.#generation;
    const agentRevision = this.#agentRevision;
    const refresh = (async () => {
      const [profile, temporary, protection, agent] = await Promise.allSettled([
        lazy.NulavioProfiles.currentForBand(), lazy.NulavioProfiles.temporaryState(),
        lazy.profileLockState(Services.dirsvc.get("ProfD", Ci.nsIFile).path),
        lazy.NulavioAI.windowState(),
      ]);
      const connected = await lazy.NulavioAI.connectedAgents().catch(() => []);
      if (!this.#started || generation !== this.#generation) {
        return;
      }
      if (profile.status === "fulfilled") {
        this.#profile = profile.value;
      }
      this.#profileUnavailable = profile.status === "rejected";
      if (temporary.status === "fulfilled") {
        this.#temporary = temporary.value.temporary;
      }
      this.#protection = protection.status === "fulfilled" ? protection.value : "unknown";
      this.#protectionUnavailable = protection.status === "rejected";
      // An idle snapshot taken before markWorkspace/raw cannot erase its newer warning.
      if (agentRevision === this.#agentRevision) {
        this.#agentUnavailable = agent.status === "rejected" || Boolean(agent.value?.unavailable);
      }
      if (agentRevision === this.#agentRevision && agent.status === "fulfilled") {
        const next = agent.value;
        const raw = this.#agent?.id === next?.id && this.#agent?.raw;
        this.#agent = next?.unavailable && this.#agent?.id === next.id
          ? { ...this.#agent, ...next, name: this.#agent.name, autonomy: this.#agent.autonomy, raw: next.raw || this.#agent.raw }
          : next;
        if (this.#agent && next) {
          this.#agent.raw ||= raw;
        }
      }
      this.#guardCount = lazy.NulavioGuard.findings().length;
      this.#connected = connected;
      for (const win of this.#windows.keys()) {
        this.#paint(win);
      }
    })().catch(console.error).finally(() => {
      if (this.#refreshing === refresh) {
        this.#refreshing = null;
      }
    });
    this.#refreshing = refresh;
    return refresh;
  }

  // Only our widget's placement is invariant; all other customization is retained.
  onWidgetMoved(id, area) {
    if (id === WIDGET && area !== AREA) {
      lazy.CustomizableUI.addWidgetToArea(WIDGET, AREA, 0);
    }
  }

  onAreaReset() {
    for (const win of this.#windows.keys()) {
      this.#paint(win);
    }
  }

  #detach(win) {
    const state = this.#windows.get(win);
    if (!state) {
      return;
    }
    this.#windows.delete(win);
    state.restoreGroupPalette();
    state.restoreIdentity();
    win.gBrowser.removeProgressListener(state.progress);
    win.gBrowser.tabContainer.removeEventListener("TabSelect", state.header);
    win.removeEventListener("unload", state.unload);
    win.removeEventListener("mousemove", state.pointer, true);
    for (const type of ["popupshowing", "popupshown", "popuphidden"]) {
      win.removeEventListener(type, state.popup, true);
    }
    win.gBrowser.tabContainer.removeEventListener("TabAttrModified", state.sharing);
    for (const type of ["dialogopen", "dialogclose"]) {
      win.removeEventListener(type, state.dialog, true);
    }
    state.downloads.disconnect();
    state.notices.disconnect();
    win.clearTimeout(state.noticeTimer);
    state.screenObserver.disconnect();
    state.identityObserver.disconnect();
    state.sizes.disconnect();
    win.windowRoot?.removeEventListener("mousedown", state.outside, true);
    win.document.documentElement.style.removeProperty("--nulavio-immersive-toolbar-size");
    state.bar.remove();
    state.fullscreen.remove();
    state.edge.remove();
    for (const name of ["nulavio-immersive", "nulavio-immersive-off", "nulavio-immersive-hold", "nulavio-stage"]) {
      win.document.documentElement.removeAttribute(name);
    }
    if (state.sheet) {
      state.sheet.remove();
    } else {
      try {
        win.windowUtils.removeSheetUsingURIString(bandSheet.spec, win.windowUtils.AUTHOR_SHEET);
      } catch {
        // The window is already gone.
      }
    }
    this.#sheets.delete(win); // a restarted Shell loads it again
    win.document.documentElement.removeAttribute("nulavio-window-agent");
    win.document.documentElement.removeAttribute("nulavio-window-raw");
  }

  /** "Perguntar ao assistente sobre esta página" in the address bar (UX5-H, Q6): typing one of its words, or
      the actions list, offers it; picking it puts this tab's page in the panel's next message and opens the
      panel. Nothing is sent. Not offered in private windows or where an agent drives the browser. */
  #addQuickAction() {
    const top = () => Services.wm.getMostRecentBrowserWindow();
    try {
      lazy.ActionsProviderQuickActions.addAction(QUICK_ACTION, {
        commands: ["assistente", "perguntar ao assistente", "assistant", "ask the assistant"],
        icon: WebExtensionPolicy.getByID(SHELL)?.getURL("shared/nulavio-symbol-mono.svg") ?? "",
        label: "nulavio-quickaction-assistant",
        isUnsupported: () => {
          const win = top();
          return !win || lazy.PrivateBrowsingUtils.isWindowPrivate(win) || Boolean(Services.prefs.getStringPref("nulavio.ai.workspace", ""));
        },
        onPick: (_queryContext, controller) => {
          const win = controller?.browserWindow ?? top();
          if (!win || lazy.PrivateBrowsingUtils.isWindowPrivate(win)) {
            return null;
          }
          const tabId = lazy.ExtensionParent.apiManager.global.tabTracker.getId(win.gBrowser.selectedTab);
          lazy.NulavioAI.assistantOffer({ kind: "page" }, tabId).catch(console.error);
          return null;
        },
      });
      const workspace = () => Boolean(Services.prefs.getStringPref("nulavio.ai.workspace", ""));
      lazy.ActionsProviderQuickActions.addAction("nulavio-settings", {
        commands: ["nulavio", "configurações do nulavio", "nulavio settings"],
        icon: WebExtensionPolicy.getByID(SHELL)?.getURL("shared/nulavio-symbol-mono.svg") ?? "",
        label: "nulavio-quickaction-settings",
        isUnsupported: workspace, // an agent's window has no Nulavio settings to open
        onPick: (_queryContext, controller) => {
          const win = controller?.browserWindow ?? top();
          if (win) {
            // One settings page (ADR 0008): the browser's own, with Nulavio's options in it.
            ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings.open(win, "");
          }
          return null;
        },
      });
      lazy.ActionsProviderQuickActions.addAction("nulavio-focus", {
        commands: ["foco", "modo foco", "focus", "focus mode"],
        icon: WebExtensionPolicy.getByID(SHELL)?.getURL("shared/nulavio-symbol-mono.svg") ?? "",
        label: "nulavio-quickaction-focus",
        isUnsupported: () => workspace() || !Services.prefs.getBoolPref("sidebar.revamp", false),
        onPick: (_queryContext, controller) => {
          const win = controller?.browserWindow ?? top();
          if (win) {
            const extension = WebExtensionPolicy.getByID(SHELL)?.extension;
            const say = key => win.A11yUtils?.announce({ raw: extension?.localizeMessage(key) ?? key }).catch(() => {});
            lazy.NulavioLayout.toggleFocus(win, say).catch(() => {}); // announced in the window
          }
          return null;
        },
      });
    } catch (e) {
      console.error("Nulavio: quick action", e); // an engine without this API: the other entry points remain
    }
  }

  stop() {
    if (!this.#started) {
      return;
    }
    this.#started = false;
    this.#generation++;
    this.#refreshing = null;
    this.#timer?.cancel();
    this.#timer = null;
    this.#unsubscribe?.();
    this.#unsubscribe = null;
    for (const topic of TOPICS) {
      Services.obs.removeObserver(this, topic);
    }
    Services.prefs.removeObserver(PREF_IMMERSIVE, this);
    Services.prefs.removeObserver(PREF_FIRSTRUN, this);
    lazy.CustomizableUI.removeListener(this);
    for (const action of QUICK_ACTIONS) {
      try {
        lazy.ActionsProviderQuickActions.removeAction(action);
      } catch (e) {
        console.error("Nulavio: quick action", e);
      }
    }
    for (const win of this.#windows.keys()) {
      this.#detach(win);
    }
    Services.catMan.deleteCategoryEntry(EARLY_WINDOW, EARLY_ENTRY, false);
    lazy.CustomizableUI.destroyWidget(WIDGET);
    lazy.CustomizableUI.unregisterArea(AREA);
    for (const uri of [sidebarFocus, inContent]) {
      if (sheets.sheetRegistered(uri, sheets.AGENT_SHEET)) {
        sheets.unregisterSheet(uri, sheets.AGENT_SHEET);
      }
    }
  }
}

export const NulavioWindow = new WindowUI();
