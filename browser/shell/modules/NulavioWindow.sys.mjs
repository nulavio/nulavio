/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Farol is privileged chrome, independent of the cosmetic Horizon preference.
   Native controls remain in their own toolbars. Only our area/widget is repaired
   after customization; no reset of the user's placements or preferences. */
const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  CustomizableUI: "moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs",
  ExtensionParent: "resource://gre/modules/ExtensionParent.sys.mjs",
  NulavioAI: "resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs",
  NulavioGuard: "resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs",
  AVATARS: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  NulavioProfiles: "resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs",
  PrivateBrowsingUtils: "resource://gre/modules/PrivateBrowsingUtils.sys.mjs",
  profileLockState: "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs",
});
const sheets = Cc["@mozilla.org/content/style-sheet-service;1"].getService(Ci.nsIStyleSheetService);
const sidebarFocus = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/sidebar-focus.css");
const bandSheet = Services.io.newURI("resource://builtin-addons/nulavio-shell/shared/window-band.css");
const AREA = "nulavio-band";
const WIDGET = "nulavio-band-widget";
const SHELL = "shell@nulavio.net";
const HTML = "http://www.w3.org/1999/xhtml";
const TOPICS = ["browser-delayed-startup-finished", "nulavio-ai-window-changed", "nulavio-guard-changed"];
// Fixed paths only. Query strings, fragments, titles and page text never name a trusted surface.
const SURFACES = Object.freeze({
  "/newtab/newtab.html": "newtabTitle",
  "/settings/settings.html": "settingsTitle",
  "/profiles/popup.html": "profilesButton",
  "/vault/unlock.html": "bandSurfaceUnlock",
  "/vault/create.html": "vaultNewProtected",
  "/vault/phone.html": "bandSurfacePhone",
  "/guard/review.html": "bandSurfaceGuard",
  "/ai/request.html": "bandSurfacePermission",
  "/routing/ask.html": "bandSurfaceRouting",
  "/routing/blocked.html": "bandSurfaceRouting",
  "/warning/warning.html": "bandSurfaceDownload",
  "/passwords/lookalike.html": "bandSurfacePassword",
});

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

function named(node, text) {
  node.textContent = text;
  node.setAttribute("aria-label", text);
  node.title = text;
}

class WindowUI {
  #started = false;
  #windows = new Map();
  #unsubscribe = null;
  #profile = null;
  #profileUnavailable = false;
  #temporary = false;
  #protection = "unknown";
  #refreshing = null;
  #generation = 0;
  #timer = null;
  #agent = null;
  #agentRevision = 0;
  #agentUnavailable = false;
  #guardCount = 0;
  #actionError = false;

  start() {
    if (this.#started) {
      return;
    }
    this.#started = true;
    this.#generation++;
    for (const uri of [sidebarFocus]) {
      if (!sheets.sheetRegistered(uri, sheets.AGENT_SHEET)) {
        sheets.loadAndRegisterSheet(uri, sheets.AGENT_SHEET);
      }
    }
    const cui = lazy.CustomizableUI;
    cui.registerArea(AREA, { type: cui.TYPE_TOOLBAR, defaultPlacements: [WIDGET], defaultCollapsed: false });
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
    for (const topic of TOPICS) {
      Services.obs.addObserver(this, topic);
    }
    this.#unsubscribe = lazy.NulavioProfiles.subscribe(() => this.refresh());
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      if (win.gBrowserInit?.delayedStartupFinished) {
        this.#attach(win);
      }
    }
    this.#timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    this.#timer.initWithCallback(() => this.refresh(), 1500, Ci.nsITimer.TYPE_REPEATING_SLACK);
    this.refresh();
  }

  observe(win, topic) {
    if (topic === "browser-delayed-startup-finished") {
      this.#attach(win);
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
      this.refresh();
    }
  }

  #open(win, path) {
    const url = policy()?.getURL(path);
    if (url && !win.closed) {
      win.openTrustedLinkIn(url, "tab", { inBackground: false });
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
    const protection = button(doc, "nv-band-protection", () => this.#open(win, "settings/settings.html#profiles"));
    const header = element(doc, "span", "nv-band-header");
    row.append(identity, protection, header);
    const seals = element(doc, "div", "nv-band-seals");
    for (const kind of ["temporary", "private", "agent", "raw", "status"]) {
      const seal = element(doc, "span", `nv-band-seal nv-band-${kind}`);
      seal.hidden = true;
      seals.append(seal);
    }
    const guard = button(doc, "nv-band-seal nv-band-guard", () => this.#open(win, "guard/review.html"));
    const pause = button(doc, "nv-band-pause", () => this.#agentAction("pause"));
    const stop = button(doc, "nv-band-stop", () => this.#agentAction("stop"));
    for (const control of [guard, pause, stop]) {
      control.hidden = true;
    }
    seals.append(guard, pause, stop);
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

  #attach(win) {
    if (!this.#started || this.#windows.has(win) || !win.gBrowser || win.closed) {
      return;
    }
    const doc = win.document;
    const sheet = element(doc, "link");
    sheet.rel = "stylesheet";
    sheet.href = bandSheet.spec;
    doc.head.append(sheet);
    const bar = doc.createXULElement("toolbar");
    bar.id = AREA;
    bar.setAttribute("customizable", "true");
    bar.setAttribute("mode", "icons");
    bar.setAttribute("defaultset", WIDGET);
    bar.setAttribute("toolbarname", "Nulavio");
    // Above both tab orientations; insertion leaves every native node in place.
    win.gNavToolbox.insertBefore(bar, doc.getElementById("TabsToolbar"));
    lazy.CustomizableUI.registerToolbarNode(bar);
    const compact = this.#build(doc, true);
    const fullscreen = element(doc, "div");
    fullscreen.id = "nulavio-fullscreen";
    fullscreen.tabIndex = 0;
    fullscreen.setAttribute("role", "group");
    fullscreen.setAttribute("aria-label", t("bandLabel"));
    const line = element(doc, "div", "nv-fullscreen-line");
    line.setAttribute("aria-hidden", "true");
    for (const kind of ["normal", "temporary", "private", "agent", "raw", "guard"]) {
      const segment = element(doc, "span", `nv-fullscreen-${kind}`);
      segment.hidden = kind !== "normal";
      line.append(segment);
    }
    fullscreen.append(line, compact);
    doc.getElementById("browser").before(fullscreen);
    const header = () => this.#header(win);
    const progress = {
      onLocationChange: header,
      onStateChange: (_progress, _request, flags) => {
        if (flags & Ci.nsIWebProgressListener.STATE_START) {
          // Clear synchronously before a new principal commits. The current principal
          // is consulted again on location/stop; no async label can win a tab race.
          for (const node of this.#rows(win)) {
            named(node.querySelector(".nv-band-header"), "");
          }
        } else if (flags & Ci.nsIWebProgressListener.STATE_STOP) {
          header();
        }
      },
      QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"]),
    };
    win.gBrowser.addProgressListener(progress);
    win.gBrowser.tabContainer.addEventListener("TabSelect", header);
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
    this.#windows.set(win, { bar, compact, fullscreen, line, sheet, progress, header, unload, pointer, screenObserver,
      noticeTimer: null, safety: null, restoreGroupPalette: this.#groupPalette(win) });
    this.#paint(win);
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
        }
      }
    } catch {
      // Uncommitted/destroyed globals are never trusted.
    }
    for (const row of this.#rows(win)) {
      named(row.querySelector(".nv-band-header"), text);
    }
  }

  #paint(win) {
    const profile = this.#profile;
    const agent = this.#agent;
    const workspace = agent?.target.kind === "workspace";
    const name = this.#temporary ? t("profilesTemporaryShort") : workspace ? agent.name
      : this.#profileUnavailable && profile?.name ? `? ${profile.name}`
        : profile?.name || agent?.target.profile || t("bandProfileUnavailable");
    const protection = t(this.#protection === "unlocked" ? "bandProtected" : this.#protection === "plain" ? "bandUnprotected" : "bandProtectionUnknown");
    const privateWindow = lazy.PrivateBrowsingUtils.isWindowPrivate(win);
    const root = win.document.documentElement;
    root.toggleAttribute("nulavio-window-agent", Boolean(agent));
    root.toggleAttribute("nulavio-window-raw", Boolean(agent?.raw));
    const state = this.#windows.get(win);
    const kinds = { normal: true, temporary: this.#temporary, private: privateWindow,
      agent: Boolean(agent), raw: Boolean(agent?.raw), guard: this.#guardCount > 0 };
    for (const [kind, visible] of Object.entries(kinds)) {
      state.line.querySelector(`.nv-fullscreen-${kind}`).hidden = !visible;
    }
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
      const identity = row.querySelector(".nv-band-identity");
      identity.style.setProperty("--profile-fill", workspace
        ? "var(--nv-color-security-agent-ink)" : `var(--nv-color-identity-${profile?.color ?? "slate"})`);
      identity.setAttribute("aria-label", t("profilesButtonNamed", [name]));
      identity.title = name;
      const glyph = row.querySelector(".nv-band-flag");
      if (!workspace && !this.#temporary && lazy.AVATARS.includes(profile?.avatar)) {
        const image = element(win.document, "img", "nv-band-avatar");
        image.src = `chrome://browser/content/profiles/assets/16_${profile.avatar}.svg`;
        image.alt = "";
        glyph.replaceChildren(image);
      } else {
        glyph.textContent = workspace ? "▤" : [...name][0]?.toLocaleUpperCase() || "?";
      }
      glyph.setAttribute("aria-hidden", "true");
      row.querySelector(".nv-band-name").textContent = name;
      named(row.querySelector(".nv-band-protection"), protection);
      const seal = (kind, visible, text) => {
        const node = row.querySelector(`.nv-band-${kind}`);
        const hadFocus = node === win.document.activeElement;
        node.hidden = !visible;
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
        lazy.NulavioProfiles.current(), lazy.NulavioProfiles.temporaryState(),
        lazy.profileLockState(Services.dirsvc.get("ProfD", Ci.nsIFile).path),
        lazy.NulavioAI.windowState(),
      ]);
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
    win.gBrowser.removeProgressListener(state.progress);
    win.gBrowser.tabContainer.removeEventListener("TabSelect", state.header);
    win.removeEventListener("unload", state.unload);
    win.removeEventListener("mousemove", state.pointer, true);
    win.clearTimeout(state.noticeTimer);
    state.screenObserver.disconnect();
    state.bar.remove();
    state.fullscreen.remove();
    state.sheet.remove();
    win.document.documentElement.removeAttribute("nulavio-window-agent");
    win.document.documentElement.removeAttribute("nulavio-window-raw");
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
    lazy.CustomizableUI.removeListener(this);
    for (const win of this.#windows.keys()) {
      this.#detach(win);
    }
    lazy.CustomizableUI.destroyWidget(WIDGET);
    lazy.CustomizableUI.unregisterArea(AREA);
    for (const uri of [sidebarFocus]) {
      if (sheets.sheetRegistered(uri, sheets.AGENT_SHEET)) {
        sheets.unregisterSheet(uri, sheets.AGENT_SHEET);
      }
    }
  }
}

export const NulavioWindow = new WindowUI();
