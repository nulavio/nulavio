/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Runs inside about:preferences (system principal), imported by NulavioSettings before the
   page builds its panes (ADR 0008). It only uses what the engine's own panes use: Preferences
   settings, SettingGroupManager groups and SettingPaneManager panes, drawn by the engine's
   widgets. Words come from l10n/<locale>/nulavio/settings.ftl.

   The contract when something goes wrong (ADR 0008, decision 4):
   - before anything is registered, preflight() checks the shape of the registry; if it is not the
     one this file was written for, nothing is changed;
   - everything this file adds is recorded in `added`, and a throw while adding undoes all of it;
   - an engine pane that gains a Nulavio group is edited as the page registers it; if that edit
     throws, the engine's pane is registered as it was;
   - a value read from a Shell module is not drawn until it was read, and a read that failed says
     so in words. Nothing shows a value it did not read. */

(() => {
  const here = { global: "current" };
  const SHELL = "shell@nulavio.net";
  const MODULES = "resource://builtin-addons/nulavio-shell/modules/";
  const IMAGES = "resource://builtin-addons/nulavio-shell/settings/native/";
  const root = document.documentElement;
  if (root.hasAttribute("nulavio-settings")) {
    return; // this document already has them (the module ran once for it)
  }

  // -- before anything changes ---------------------------------------------------------------------
  /** The registry this file was written for, or a throw that leaves the page as the engine's. */
  function preflight() {
    const { SettingGroupManager } = ChromeUtils.importESModule("chrome://browser/content/preferences/config/SettingGroupManager.mjs", here);
    const { SettingPaneManager } = ChromeUtils.importESModule("chrome://browser/content/preferences/config/SettingPaneManager.mjs", here);
    const { Preferences } = ChromeUtils.importESModule("chrome://global/content/preferences/Preferences.mjs", here);
    const wanted = [
      [SettingGroupManager, ["registerGroups", "has"]],
      [SettingPaneManager, ["registerPane"]],
      [Preferences, ["addSetting", "getSetting"]],
    ];
    for (const [object, names] of wanted) {
      for (const name of names) {
        if (typeof object?.[name] !== "function") {
          throw new Error(`settings registry: ${name} is missing`);
        }
      }
    }
    if (!(SettingGroupManager._data instanceof Map) || !(SettingPaneManager._data instanceof Map) || !(Preferences._settings instanceof Map)) {
      throw new Error("settings registry: its stores have another shape");
    }
    if (SettingPaneManager._data.size) {
      throw new Error("settings registry: the page registered its panes before this module ran");
    }
    const nav = document.getElementById("categories");
    if (!nav || !document.getElementById("mainPrefPane") || typeof window.register_module !== "function") {
      throw new Error("settings page: its navigation or pane container is missing");
    }
    return { SettingGroupManager, SettingPaneManager, Preferences, nav };
  }
  const { SettingGroupManager, SettingPaneManager, Preferences, nav } = preflight();

  // The Shell's own modules, from the shared system global (fixed addresses; loaded when first used).
  const shell = new Proxy(
    {},
    { get: (_target, name) => ChromeUtils.importESModule(`${MODULES}${name}.sys.mjs`)[name] }
  );
  const top = () => window.browsingContext.topChromeWindow;
  // The tab this page is in: the layout module follows it when the tab moves to another window.
  const tab = () => window.browsingContext.top.embedderElement;

  // -- what this file added, so a failure can take it all back --------------------------------------
  const added = { settings: [], groups: [], panes: [], nodes: [], cleanups: [] };
  const undoOnly = []; // what a failure puts back in the engine's own configuration
  const FLUENT = "nulavio/settings.ftl";
  let fluentLink = null;
  const navOrder = [...nav.children];
  const registerPane = SettingPaneManager.registerPane;
  const hadOwnRegisterPane = Object.hasOwn(SettingPaneManager, "registerPane");
  function undo() {
    for (const restore of undoOnly.splice(0)) {
      restore();
    }
    for (const cleanup of added.cleanups.splice(0)) {
      try {
        cleanup();
      } catch (e) {
        console.error(e);
      }
    }
    if (hadOwnRegisterPane) {
      SettingPaneManager.registerPane = registerPane;
    } else {
      delete SettingPaneManager.registerPane;
    }
    for (const { id, view } of added.panes.splice(0)) {
      SettingPaneManager._data.delete(id);
      // What registerPane left in the page: the pane's element and its entries in the page's own maps
      // (the page's search runs the init of every entry it finds there).
      for (const pane of document.querySelectorAll("#mainPrefPane > setting-pane")) {
        if (pane.name === view) {
          pane.remove();
        }
      }
      window.gCategoryInits?.delete?.(view);
      window.gCategoryModules?.delete?.(view);
    }
    if (fluentLink) {
      document.l10n?.removeResourceIds?.([FLUENT]);
      fluentLink.remove();
      fluentLink = null;
    }
    for (const id of added.groups.splice(0)) {
      SettingGroupManager._data.delete(id);
    }
    for (const id of added.settings.splice(0)) {
      try {
        Preferences.getSetting(id)?.destroy?.();
      } catch (e) {
        console.error(e);
      }
      Preferences._settings.delete(id);
    }
    for (const node of added.nodes.splice(0)) {
      node.remove();
    }
    nav.append(...navOrder); // the engine's buttons, back in the engine's order
    root.removeAttribute("nulavio-settings");
  }
  // Each of these notes what it is about to add before it adds it, so a throw inside the registry's
  // own function (after it changed something) is undone too.
  const setting = config => {
    added.settings.push(config.id);
    const { setup } = config;
    if (!setup) {
      Preferences.addSetting(config);
      return;
    }
    Preferences.addSetting({
      ...config,
      // A setup here is setup(emitChange, stops): whatever it starts, it pushes the way to stop it. The
      // engine runs it while it builds the setting; if it throws halfway, what had started is stopped.
      setup(emitChange) {
        const stops = [];
        const stop = () => {
          for (const fn of stops.splice(0)) {
            fn();
          }
        };
        try {
          setup.call(this, emitChange, stops);
        } catch (e) {
          stop();
          throw e;
        }
        return stop;
      },
    });
  };
  const groups = configs => {
    for (const [id, config] of Object.entries(configs)) {
      added.groups.push(id);
      SettingGroupManager.registerGroup(id, config);
    }
  };

  /**
   * A value read from a Shell module. `ready` only after a read answered; `failed` when the last
   * one threw. A read that a later one overtook is dropped, so an old answer never lands on top
   * of a newer one.
   */
  const started = new Set(); // the reads that ran at least once: asked again when the person comes back to this tab
  function source(read) {
    const state = { ready: false, failed: false, value: null };
    const listeners = new Set();
    let turn = 0;
    const refresh = async () => {
      started.add(refresh);
      const mine = ++turn;
      let next;
      try {
        next = { ready: true, failed: false, value: await read() };
      } catch (e) {
        console.error("Nulavio settings: a read failed", e);
        next = { ready: false, failed: true, value: null };
      }
      if (mine === turn && !window.closed) {
        Object.assign(state, next);
        listeners.forEach(emit => emit());
      }
    };
    return {
      state,
      refresh,
      /** Redraw on every read; returns the way to stop. */
      listen(emit) {
        listeners.add(emit);
        return () => listeners.delete(emit);
      },
      /** A setup that only redraws on every read. */
      watch(emit, stops) {
        listeners.add(emit);
        stops.push(() => listeners.delete(emit));
      },
    };
  }
  /** "Could not read this" in a group, shown only while the read behind it failed. */
  const failureNote = (id, from) => {
    setting({ id, setup: from.watch, visible: () => from.state.failed });
    return { id, control: "moz-message-bar", l10nId: "nulavio-read-failed", controlAttrs: { type: "warning" } };
  };
  /** A row that opens a detail page of the Shell in this tab ("back" returns here). */
  const detailRow = (id, section, extra = {}) => {
    setting({
      id,
      onUserClick(event) {
        event.preventDefault();
        const url = shell.NulavioSettings.detail(section);
        if (url) {
          top().openTrustedLinkIn(url, "current");
        }
      },
      ...extra,
    });
    return { id, l10nId: id, control: "moz-box-button" };
  };

  function register() {
    const links = () => [...document.querySelectorAll('link[rel="localization"]')];
    const linksBefore = new Set(links());
    MozXULElement.insertFTLIfNeeded(FLUENT);
    fluentLink = links().find(link => !linksBefore.has(link)) ?? null;
    // Coming back to this tab: what was read is read again (a profile renamed, a manager changed, a key remapped elsewhere).
    const again = () => {
      if (document.visibilityState === "visible") {
        started.forEach(refresh => refresh());
      }
    };
    document.addEventListener("visibilitychange", again);
    added.cleanups.push(() => document.removeEventListener("visibilitychange", again));

    // -- layout: Lateral, Abas no topo, Foco (NulavioLayout owns the change) ---------------------
    const layout = source(() => shell.NulavioLayout.state(tab()));
    const layoutOpen = () => layout.state.ready && !layout.state.value.locked && layout.state.value.available;
    setting({
      id: "nulavio-layout",
      setup(emitChange, stops) {
        stops.push(layout.listen(emitChange));
        layout.refresh();
        try {
          stops.push(shell.NulavioLayout.subscribe(tab(), layout.refresh));
        } catch (e) {
          console.error(e); // no live updates; the value still comes from the read above
        }
      },
      // Nothing is marked until the layout was read; a hand-made arrangement marks none either.
      get: () => (layout.state.ready && layout.state.value.preset !== "custom" ? layout.state.value.preset : ""),
      set(value) {
        shell.NulavioLayout.apply(tab(), value).then(layout.refresh, layout.refresh);
      },
      disabled: () => !layoutOpen(),
    });

    // -- Immersive (ADR 0009): one switch on top of the layout; NulavioLayout is the only writer --
    const PREF_IMMERSIVE = "nulavio.layout.immersive";
    const immersive = source(async () => shell.NulavioLayout.immersive());
    setting({
      id: "nulavio-immersive",
      deps: ["nulavio-layout"],
      setup(emitChange, stops) {
        stops.push(immersive.listen(emitChange));
        immersive.refresh();
        Services.prefs.addObserver(PREF_IMMERSIVE, immersive.refresh); // the key (Ctrl+Alt+I) or another window changed it
        stops.push(() => Services.prefs.removeObserver(PREF_IMMERSIVE, immersive.refresh));
      },
      get: () => Boolean(immersive.state.value?.on),
      set(value) {
        try {
          shell.NulavioLayout.setImmersive(Boolean(value));
        } catch (e) {
          console.error(e); // locked by an administrator: the switch shows what is true
        }
        immersive.refresh();
      },
      visible: () => immersive.state.ready,
      disabled: () => immersive.state.value?.locked || !layoutOpen(),
    });

    // -- look: accent, more contrast, new-tab ambience, less transparency (NulavioPersonalise) ----
    const look = source(() => shell.NulavioPersonalise.state());
    const lookSetting = (id, option, toValue = v => v) =>
      setting({
        id,
        setup: look.watch,
        get: () => (look.state.ready ? toValue(look.state.value[option]) : toValue(undefined)),
        set(value) {
          shell.NulavioPersonalise.set(option, toValue(value)).then(look.refresh, look.refresh);
        },
        visible: () => look.state.ready,
        disabled: () => Boolean(look.state.value?.locked?.[option]),
      });
    lookSetting("nulavio-accent", "accent", value => value ?? "");
    lookSetting("nulavio-more-contrast", "moreContrast", Boolean);
    lookSetting("nulavio-newtab-ambience", "newtabAmbience", Boolean);
    lookSetting("nulavio-reduce-transparency", "reduceTransparency", Boolean);
    look.refresh();
    added.cleanups.push(shell.NulavioPersonalise.subscribe(look.refresh));

    // -- who you are here: this profile and its protection, in the band's own words --------------
    const profile = source(() => shell.NulavioProfiles.here());
    const HERE = { plain: "nulavio-here-plain", unlocked: "nulavio-here-protected" };
    setting({
      id: "nulavio-here",
      setup(emitChange, stops) {
        stops.push(profile.listen(emitChange));
        profile.refresh();
        try {
          stops.push(shell.NulavioProfiles.subscribe(profile.refresh)); // renamed or protected from another tab or window
        } catch (e) {
          console.error(e);
        }
      },
      visible: () => profile.state.ready && Boolean(profile.state.value),
      getControlConfig(config) {
        const now = profile.state.value;
        if (!now) {
          return config;
        }
        const l10nId = now.temporary ? "nulavio-here-temporary" : (HERE[now.protection] ?? "nulavio-here-unknown");
        return { ...config, l10nId, l10nArgs: { name: now.name } };
      },
    });
    // No profile to name (the engine's profile service is off for this start): say so instead of nothing.
    setting({ id: "nulavio-here-none", setup: profile.watch, visible: () => profile.state.ready && !profile.state.value });

    // -- every profile of the group, with its protection as it is now (ADR 0011: a list the registry
    // cannot describe is a custom element; it is built with the engine's rows and the DOM, never from
    // markup, and it renders its words so the page's search finds them) ---------------------------
    const profileList = source(() => shell.NulavioProfiles.list());
    const PROFILE_ROW = profile => {
      if (profile.temporary) {
        return "nulavio-profile-temporary";
      }
      return profile.encrypted ? (profile.locked ? "nulavio-profile-locked" : "nulavio-profile-unlocked") : "nulavio-profile-plain";
    };
    if (!customElements.get("nulavio-profile-list")) {
      customElements.define(
        "nulavio-profile-list",
        class extends HTMLElement {
          #stop = null;
          connectedCallback() {
            this.#stop = profileList.listen(() => this.draw());
            this.draw();
          }
          disconnectedCallback() {
            this.#stop?.();
            this.#stop = null;
          }
          draw() {
            const profiles = profileList.state.ready ? (profileList.state.value?.profiles ?? []) : [];
            const group = document.createElement("moz-box-group");
            for (const profile of profiles) {
              const row = document.createElement("moz-box-item");
              row.dataset.profile = String(profile.id ?? "");
              // The name is the person's own text: it goes in as a Fluent argument, never as markup.
              document.l10n.setAttributes(row, PROFILE_ROW(profile), {
                name: profile.name || "",
                here: profile.isCurrent ? "yes" : "no",
              });
              group.append(row);
            }
            this.replaceChildren(...(profiles.length ? [group] : []));
          }
        }
      );
    }
    setting({
      id: "nulavio-profile-list",
      setup(emitChange, stops) {
        stops.push(profileList.listen(emitChange));
        profileList.refresh();
        try {
          stops.push(shell.NulavioProfiles.subscribe(profileList.refresh)); // created, renamed, locked or removed elsewhere
        } catch (e) {
          console.error(e);
        }
      },
      visible: () => profileList.state.ready && (profileList.state.value?.profiles?.length ?? 0) > 0,
    });

    // -- passwords: which manager is in use now ---------------------------------------------------
    const passwords = source(() => shell.NulavioPasswords.state());
    setting({
      id: "nulavio-passwords-now",
      setup(emitChange, stops) {
        stops.push(passwords.listen(emitChange));
        passwords.refresh();
        // The engine's own checkbox, in the group below this one, changes the answer...
        Services.prefs.addObserver("signon.rememberSignons", passwords.refresh);
        stops.push(() => Services.prefs.removeObserver("signon.rememberSignons", passwords.refresh));
        // ...and so does a manager's extension installed, removed, turned on or off.
        const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
        const changed = () => passwords.refresh();
        const listener = { onInstalled: changed, onUninstalled: changed, onEnabled: changed, onDisabled: changed };
        AddonManager.addAddonListener(listener);
        stops.push(() => AddonManager.removeAddonListener(listener));
      },
      visible: () => passwords.state.ready,
      getControlConfig(config) {
        const now = passwords.state.value;
        if (!now) {
          return config;
        }
        if (now.current === "builtin" || now.current === "none") {
          return { ...config, l10nId: `nulavio-passwords-now-${now.current}` };
        }
        const name = now.providers.find(item => item.key === now.current)?.extension?.name ?? now.current;
        return { ...config, l10nId: "nulavio-passwords-now-extension", l10nArgs: { name } };
      },
    });

    // -- what changed outside Nulavio (the Guard's pending findings; the review is its own page) --
    // The count is read after the Guard's own check of this start (it waits for the windows to be back):
    // before that the Guard has no findings to give, which is not the same as "nothing to review".
    const guard = source(async () => {
      const { state } = await shell.NulavioGuard.check();
      return { watched: state !== "skipped", count: shell.NulavioGuard.findings().length };
    });
    setting({
      id: "nulavio-guard-review",
      setup(emitChange, stops) {
        stops.push(guard.listen(emitChange));
        guard.refresh();
        const changed = () => guard.refresh(); // a finding decided on the review page, or a new one
        Services.obs.addObserver(changed, "nulavio-guard-changed");
        stops.push(() => Services.obs.removeObserver(changed, "nulavio-guard-changed"));
      },
      visible: () => guard.state.ready,
      onUserClick(event) {
        event.preventDefault();
        const url = WebExtensionPolicy.getByID(SHELL)?.getURL("guard/review.html");
        if (url) {
          top().openTrustedLinkIn(url, "current");
        }
      },
      getControlConfig(config) {
        const now = guard.state.value;
        if (!now) {
          return config;
        }
        // A temporary profile and an agent's own profile are not watched: say that, not "nothing to review".
        return now.watched ? { ...config, l10nArgs: { count: now.count } } : { ...config, l10nId: "nulavio-guard-review-unwatched" };
      },
    });

    // -- Nulavio's keys: what each one is now; changing them is the engine's own view -------------
    const shortcuts = WebExtensionPolicy.getByID(SHELL)?.extension?.shortcuts;
    const commandNames = shortcuts?.manifestCommands ? [...shortcuts.manifestCommands.keys()] : [];
    const keys = source(async () => new Map((await shortcuts.allCommands()).map(command => [command.name, command])));
    const changedKeys = () =>
      keys.state.ready
        ? commandNames.filter(name => keys.state.value.get(name)?.shortcut !== (shortcuts.manifestCommands.get(name)?.shortcut ?? ""))
        : [];
    const keyRows = commandNames.map(name => {
      const id = `nulavio-key-${name}`;
      setting({
        id,
        setup: keys.watch,
        visible: () => keys.state.ready && keys.state.value.has(name),
        getControlConfig(config) {
          const command = keys.state.value?.get(name);
          if (!command) {
            return config;
          }
          // The command's name comes from the Shell's own messages, already in the browser's language.
          const attrs = { ...config.controlAttrs, label: command.description || name };
          return command.shortcut
            ? { ...config, controlAttrs: { ...attrs, description: command.shortcut } }
            : { ...config, l10nId: "nulavio-key-none", controlAttrs: attrs };
        },
      });
      return { id, control: "moz-box-item" };
    });
    if (keyRows.length) {
      setting({
        id: "nulavio-keys",
        setup() {
          keys.refresh(); // and again when the person comes back from the engine's view, where a key is changed
        },
      });
      setting({
        id: "nulavio-keys-change",
        onUserClick(event) {
          event.preventDefault();
          top().BrowserAddonUI.openAddonsMgr(`addons://shortcuts/${encodeURIComponent(SHELL)}`);
        },
      });
      setting({
        id: "nulavio-keys-reset",
        setup: keys.watch,
        visible: () => changedKeys().length > 0,
        async onUserClick(event) {
          event.preventDefault();
          for (const name of changedKeys()) {
            const before = keys.state.value.get(name)?.shortcut ?? "";
            try {
              await shortcuts.resetCommand(name);
            } catch (e) {
              console.error(e);
              continue; // nothing changed: nothing is announced, and the list read below shows the key as it is
            }
            // The engine's reset announces nothing; the Shell's background listens to this to rename its button.
            shortcuts.onShortcutChanged?.({ name, newShortcut: shortcuts.manifestCommands.get(name)?.shortcut ?? "", oldShortcut: before });
          }
          keys.refresh();
        },
      });
    }

    for (const id of ["nulavio-layout-moved", "nulavio-profiles-box", "nulavio-passwords-box", "nulavio-protections-box"]) {
      setting({ id });
    }

    groups({
      nulavioLayout: {
        l10nId: "nulavio-layout-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-layout-failed", layout),
          {
            id: "nulavio-layout",
            control: "moz-visual-picker",
            options: ["lateral", "top", "focus"].map(value => ({
              value,
              l10nId: `nulavio-layout-${value}`,
              controlAttrs: { id: `nulavio-layout-${value}`, class: "setting-chooser-item", imagesrc: `${IMAGES}layout-${value}.svg` },
            })),
          },
          { id: "nulavio-immersive", l10nId: "nulavio-immersive", control: "moz-toggle" },
        ],
      },
      nulavioLook: {
        l10nId: "nulavio-look-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-look-failed", look),
          {
            id: "nulavio-accent",
            control: "moz-radio-group",
            l10nId: "nulavio-accent",
            options: [
              { value: "mint", l10nId: "nulavio-accent-mint" },
              { value: "blue", l10nId: "nulavio-accent-blue" },
            ],
          },
          { id: "nulavio-more-contrast", l10nId: "nulavio-more-contrast", control: "moz-toggle" },
          { id: "nulavio-newtab-ambience", l10nId: "nulavio-newtab-ambience", control: "moz-toggle" },
          { id: "nulavio-reduce-transparency", l10nId: "nulavio-reduce-transparency", control: "moz-toggle" },
        ],
      },
      // Where the engine's two-way "Disposição do navegador" was: one arrangement control, in Aparência.
      nulavioLayoutMoved: {
        subcategory: "layout", // the engine's old addresses for its picker (#general-layout) land on this pointer
        l10nId: "nulavio-layout-moved-group",
        headingLevel: 2,
        items: [{ id: "nulavio-layout-moved", l10nId: "nulavio-layout-moved", control: "moz-box-button", loadPane: "appearance" }],
      },
      nulavioHere: {
        l10nId: "nulavio-here-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-here-failed", profile),
          { id: "nulavio-here", control: "moz-box-item" },
          { id: "nulavio-here-none", l10nId: "nulavio-here-none", control: "moz-box-item" },
        ],
      },
      nulavioProfilesManage: {
        l10nId: "nulavio-profiles-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-profile-list-failed", profileList),
          { id: "nulavio-profile-list", control: "nulavio-profile-list" },
          {
            id: "nulavio-profiles-box",
            control: "moz-box-group",
            items: [detailRow("nulavio-open-profiles", "profiles"), detailRow("nulavio-open-routing", "routing")],
          },
        ],
      },
      nulavioPasswordManager: {
        l10nId: "nulavio-passwords-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-passwords-failed", passwords),
          {
            id: "nulavio-passwords-box",
            control: "moz-box-group",
            items: [{ id: "nulavio-passwords-now", control: "moz-box-item" }, detailRow("nulavio-open-passwords", "passwords")],
          },
        ],
      },
      nulavioProtections: {
        l10nId: "nulavio-protections-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-guard-failed", guard),
          {
            id: "nulavio-protections-box",
            control: "moz-box-group",
            items: [
              detailRow("nulavio-open-exceptions", "exceptions"),
              { id: "nulavio-guard-review", l10nId: "nulavio-guard-review", control: "moz-box-button" },
            ],
          },
        ],
      },
      nulavioSearch: {
        l10nId: "nulavio-search-group",
        headingLevel: 2,
        items: [detailRow("nulavio-open-search", "search")],
      },
      nulavioAssistantEntry: {
        l10nId: "nulavio-assistant-group",
        headingLevel: 2,
        items: [detailRow("nulavio-open-assistant", "ai")],
      },
      nulavioIntegrationsEntry: {
        l10nId: "nulavio-integrations-group",
        headingLevel: 2,
        items: [detailRow("nulavio-open-integrations", "integrations")],
      },
    });
    if (keyRows.length) {
      groups({
        nulavioShortcuts: {
          l10nId: "nulavio-shortcuts-group",
          headingLevel: 2,
          items: [
            failureNote("nulavio-keys-failed", keys),
            { id: "nulavio-keys", control: "moz-box-group", items: keyRows },
            { id: "nulavio-keys-change", l10nId: "nulavio-keys-change", control: "moz-box-button" },
            { id: "nulavio-keys-reset", l10nId: "nulavio-keys-reset", control: "moz-button" },
          ],
        },
      });
    }

    // -- one page, ordered by what the person is doing ---------------------------------------------
    // The page registers its own panes right after this module (its DOMContentLoaded listener comes
    // second), so an engine pane is edited as it is registered: the one seam into the page's code.
    // Engine groups keep their order; a Nulavio group is put next to the one it belongs with.
    const accountsOff = () => !Services.prefs.getBoolPref("identity.fxaccounts.enabled", false);
    const before = (ids, anchor, ...ours) => {
      const at = ids.indexOf(anchor);
      return at === -1 ? [...ours, ...ids] : [...ids.slice(0, at), ...ours, ...ids.slice(at)];
    };
    const after = (ids, anchor, ...ours) => {
      const at = ids.indexOf(anchor);
      return at === -1 ? [...ids, ...ours] : [...ids.slice(0, at + 1), ...ours, ...ids.slice(at + 1)];
    };
    const edits = {
      appearance: config => ({
        ...config,
        groupIds: ["nulavioLayout", ...before(config.groupIds, "relatedSettings", "nulavioLook")],
      }),
      // The engine's first pane holds the default browser, import and backup. With accounts turned
      // off (read now, not assumed) "Conta e sincronização" names nothing the person can use: the
      // pane is called "Geral". Its account group stays, last, and says accounts are unavailable. The
      // engine's own "Perfis" group leaves it: profiles have their pane, with their protection.
      sync(config) {
        let groupIds = config.groupIds.filter(id => id !== "profiles");
        if (!accountsOff()) {
          return { ...config, groupIds };
        }
        // What can be done here comes first; "accounts are unavailable" goes last.
        groupIds = [...groupIds.filter(id => id !== "accountDisabled"), ...groupIds.filter(id => id === "accountDisabled")];
        const iconSrc = "chrome://browser/skin/preferences/category-general.svg";
        const edited = { ...config, groupIds, l10nId: "nulavio-pane-general", iconSrc };
        // The button last, once nothing above can throw: the pane and its entry are renamed together or not at all.
        const button = document.getElementById("category-sync");
        if (button) {
          button.setAttribute("data-l10n-id", "nulavio-pane-general-nav");
          button.iconSrc = iconSrc;
        }
        return edited;
      },
      // The engine's AI controls and Nulavio's assistant are one subject: one pane, "Assistente e IA", with
      // the assistant first. The engine's opening card (a promise of "more controls soon", with the engine
      // maker's mascot) gives way; every control of the pane stays.
      ai(config) {
        const edited = {
          ...config,
          l10nId: "nulavio-pane-assistant",
          groupIds: ["nulavioAssistantEntry", ...config.groupIds.filter(id => id !== "aiControlsDescription")],
        };
        document.getElementById("category-ai-features")?.setAttribute("data-l10n-id", "nulavio-pane-assistant-nav");
        return edited;
      },
      privacy: config => ({ ...config, groupIds: after(config.groupIds, "etpStatus", "nulavioProtections") }),
      passwordsAutofill: config => ({ ...config, groupIds: ["nulavioPasswordManager", ...config.groupIds] }),
      search: config => ({ ...config, groupIds: after(config.groupIds, "defaultEngine", "nulavioSearch") }),
      tabsBrowsing: config => ({
        ...config,
        groupIds: after(
          config.groupIds.map(id => (id === "browserLayout" ? "nulavioLayoutMoved" : id)),
          "keyboardShortcuts",
          ...(keyRows.length ? ["nulavioShortcuts"] : [])
        ),
      }),
    };
    // An engine group is registered when its module loads: with the page for some, when the pane is first
    // opened for others. One of them has a row that only made
    // sense with the engine's own layout picker: "Personalizar layout do navegador", in Aparência, led to
    // the pane whose picker now points back to Aparência. That row goes; the group keeps its other rows.
    const groupEdits = {
      relatedSettings(config) {
        for (const item of config.items ?? []) {
          if (Array.isArray(item.items)) {
            const rows = item.items;
            item.items = rows.filter(row => row.id !== "related-settings-tabs-browsing-link");
            undoOnly.push(() => (item.items = rows));
          }
        }
      },
    };
    const editGroup = id => {
      try {
        groupEdits[id](SettingGroupManager.get(id));
      } catch (e) {
        console.error(`Nulavio settings: the engine's "${id}" group is shown as it is`, e);
      }
    };
    for (const id of Object.keys(groupEdits).filter(id => SettingGroupManager.has(id))) {
      editGroup(id);
    }
    if (typeof SettingGroupManager.onRegister === "function") {
      added.cleanups.push(SettingGroupManager.onRegister(id => Object.hasOwn(groupEdits, id) && editGroup(id)));
    }
    SettingPaneManager.registerPane = function (id, config) {
      let edited = config;
      if (Object.hasOwn(edits, id)) {
        try {
          edited = edits[id](config);
        } catch (e) {
          console.error(`Nulavio settings: the engine's "${id}" pane is shown as it is`, e);
        }
      }
      return registerPane.call(this, id, edited);
    };

    const pane = (id, view, navId, icon, groupIds) => {
      added.panes.push({ id, view });
      registerPane.call(SettingPaneManager, id, { l10nId: `nulavio-pane-${navId}`, iconSrc: icon, groupIds });
      const button = document.createElement("moz-page-nav-button");
      button.id = `category-nulavio-${navId}`;
      button.setAttribute("view", view);
      button.setAttribute("iconsrc", icon);
      button.setAttribute("data-l10n-id", `nulavio-pane-${navId}-nav`);
      added.nodes.push(button);
      return button;
    };
    const profilesButton = pane("nulavioProfiles", "paneNulavioProfiles", "profiles", "chrome://browser/skin/fxa/avatar-empty.svg", [
      "nulavioHere",
      "nulavioProfilesManage",
    ]);
    // The assistant has a pane of its own only where the engine shows no AI pane to put it in (read now).
    const engineAiPane = Services.prefs.getBoolPref("browser.preferences.aiControls", false);
    if (!engineAiPane) {
      delete edits.ai;
    }
    const assistantButton = engineAiPane
      ? document.getElementById("category-ai-features")
      : pane("nulavioAssistant", "paneNulavioAssistant", "assistant", "chrome://browser/content/firefoxview/view-chats.svg", [
          "nulavioAssistantEntry",
        ]);
    const integrationsButton = pane("nulavioIntegrations", "paneNulavioIntegrations", "integrations", "chrome://global/skin/icons/plugin.svg", [
      "nulavioIntegrationsEntry",
    ]);

    // The navigation, in the order of the journey: settle in (default browser, import), how it
    // looks, who you are, what protects you, what helps you, how you browse. The engine's buttons
    // only move; a button this list does not know stays after them, in the engine's order.
    const byId = id => document.getElementById(id);
    const journey = [
      byId("category-sync"),
      byId("category-appearance"),
      profilesButton,
      byId("category-privacy"),
      byId("category-passwords-autofill"),
      byId("category-search"),
      assistantButton,
      byId("category-tabs-browsing"),
      byId("category-home"),
      byId("category-downloads"),
    ].filter(Boolean);
    nav.prepend(...journey);
    (byId("category-about-firefox") ?? nav.lastElementChild).before(integrationsButton);

    root.setAttribute("nulavio-settings", "1");
  }

  try {
    register();
  } catch (e) {
    undo();
    throw e;
  }
  window.addEventListener(
    "unload",
    () => {
      for (const cleanup of added.cleanups.splice(0)) {
        cleanup();
      }
    },
    { once: true }
  );
})();
