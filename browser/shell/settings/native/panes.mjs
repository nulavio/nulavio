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

  // The Shell's own modules, from the shared system global, each loaded when first used. Each address is written
  // out: privileged code never loads a module from an address it put together (the project's own scanner rule).
  const shell = {
    get NulavioAI() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI;
    },
    get NulavioGuard() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard;
    },
    get NulavioLayout() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout;
    },
    get NulavioPasswords() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs").NulavioPasswords;
    },
    get NulavioPersonalise() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise;
    },
    get NulavioPrivacy() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy;
    },
    get NulavioProfiles() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;
    },
    get NulavioRouting() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs").NulavioRouting;
    },
    get NulavioSearch() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSearch.sys.mjs").NulavioSearch;
    },
    get NulavioSettings() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings;
    },
    get NulavioVault() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs").NulavioVault;
    },
  };
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
  // The engine hands getControlConfig the config it returned the time before, so words chosen for one state
  // would stay when a later state returns the config as it came ("Sem tecla" after a key was set, "desligado"
  // after it was turned on again). Every call here starts from the control's first config instead.
  const FIRST = Symbol("the control's config as the group declared it");
  const fromFirst = getControlConfig =>
    function (config, ...rest) {
      const first = config?.[FIRST] ?? config;
      return { ...getControlConfig.call(this, first, ...rest), [FIRST]: first };
    };
  const setting = declared => {
    added.settings.push(declared.id);
    const config = declared.getControlConfig ? { ...declared, getControlConfig: fromFirst(declared.getControlConfig) } : declared;
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
    let layoutFailed = "";
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
        layoutFailed = "";
        Promise.resolve()
          .then(() => shell.NulavioLayout.apply(tab(), value))
          .then(layout.refresh, e => {
          // The change did not happen: the picker goes back to what the window has, and the group says why.
          const code = String(e?.code ?? "layout-failed").replace(/[^a-z_-]/gi, "").replaceAll("-", "_");
          layoutFailed = msg(`err_${code}`) || msg("err_layout_failed");
          layout.refresh();
        });
      },
      disabled: () => !layoutOpen(),
    });
    // Why the arrangement cannot be chosen (an administrator's lock, or no sidebar in this window), and what the
    // last choice answered when it could not be applied. Both in words, next to the picker they are about.
    const layoutNote = (id, type, text) => {
      setting({
        id,
        setup: layout.watch,
        visible: () => Boolean(text()),
        getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, type, message: text() } }),
      });
      return { id, control: "moz-message-bar" };
    };
    // While the first-run choice is still open, the arrangement in use can be kept from here too, so the question
    // is never out of reach (the new tab may have been handed to another page). Choosing another one answers it as well.
    const PRESETS = ["lateral", "top", "focus"];
    const layoutPending = () => layoutOpen() && Boolean(layout.state.value.choicePending);
    setting({
      id: "nulavio-layout-keep",
      setup: layout.watch,
      visible: layoutPending,
      onUserClick(event) {
        event.preventDefault();
        try {
          shell.NulavioLayout.dismissChoice();
        } catch (e) {
          console.error(e);
        }
        layout.refresh();
      },
      getControlConfig(config) {
        const preset = layout.state.value?.preset;
        const label = msg(PRESETS.includes(preset) ? `layoutChoiceKeep_${preset}` : "layoutChoiceDone");
        return { ...config, controlAttrs: { ...config.controlAttrs, label, title: msg("layoutPendingHint") } };
      },
    });
    const layoutNotes = [
      layoutNote("nulavio-layout-why", "info", () =>
        !layout.state.ready || layoutOpen() ? "" : msg(layout.state.value.available ? "layoutLocked" : "layoutUnavailable")
      ),
      layoutNote("nulavio-layout-error", "error", () => layoutFailed),
    ];

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
    const lookNow = () => (look.state.ready ? look.state.value : null);
    const lookLocked = option => Boolean(lookNow()?.locked?.[option]);
    const lookSetting = (id, option, toValue = v => v, special = {}) =>
      setting({
        id,
        setup: look.watch,
        get: () => (look.state.ready ? toValue(look.state.value[option]) : toValue(undefined)),
        set(value) {
          shell.NulavioPersonalise.set(option, toValue(value)).then(look.refresh, look.refresh);
        },
        visible: () => look.state.ready,
        disabled: () => lookLocked(option),
        ...special,
      });
    // What the system already asks for is shown as in effect, with its reason, never as a switch that changes nothing.
    const contrastBySystem = () => Boolean(lookNow()?.system.moreContrast || lookNow()?.system.forcedColors);
    // Why the new tab's cards are solid already or cannot be anything else: the system asks, "Mais contraste" does it,
    // or nothing is transparent (the soft background is off).
    const solidBy = () => {
      const now = lookNow();
      if (!now) {
        return null;
      }
      return now.system.reducedTransparency ? "system" : now.moreContrast || contrastBySystem() ? "contrast" : now.newtabAmbience ? null : "idle";
    };
    lookSetting("nulavio-accent", "accent", value => value ?? "");
    lookSetting("nulavio-more-contrast", "moreContrast", Boolean, {
      get: () => Boolean(lookNow()?.moreContrast) || contrastBySystem(),
      disabled: () => contrastBySystem() || lookLocked("moreContrast"),
      getControlConfig: config => (contrastBySystem() ? { ...config, l10nId: "nulavio-more-contrast-system" } : config),
    });
    lookSetting("nulavio-newtab-ambience", "newtabAmbience", Boolean);
    lookSetting("nulavio-reduce-transparency", "reduceTransparency", Boolean, {
      get: () => Boolean(lookNow()?.reduceTransparency) || ["system", "contrast"].includes(solidBy()),
      disabled: () => Boolean(solidBy()) || lookLocked("reduceTransparency"),
      getControlConfig: config => (solidBy() ? { ...config, l10nId: `nulavio-reduce-transparency-${solidBy()}` } : config),
    });
    // An option an administrator set cannot be changed here: said once, for the group.
    const LOOK = ["accent", "moreContrast", "newtabAmbience", "reduceTransparency"];
    setting({ id: "nulavio-look-locked", setup: look.watch, visible: () => LOOK.some(lookLocked) });
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

    // -- every profile of the group: what it is now and what can be done with it (ADR 0011). Drawn the
    // way the engine draws its own lists (containers, home pages): one setting whose rows come from
    // getControlConfig, made of the engine's rows, buttons and fields. The words of the actions, the
    // confirmations and the errors are the Shell's own messages, the ones the band and the menu use;
    // every change goes through NulavioProfiles and NulavioVault, which check it as they always did. --
    const extension = WebExtensionPolicy.getByID(SHELL)?.extension;
    const msg = (key, ...subs) => extension?.localizeMessage(key, subs) ?? "";
    const pageOf = path => WebExtensionPolicy.getByID(SHELL)?.getURL(path);
    const { freeName, TEMPLATE_NAMES, templateHintKey } = ChromeUtils.importESModule(
      "resource://builtin-addons/nulavio-shell/lib/names.js",
      here
    );
    const profileList = source(() => shell.NulavioProfiles.list());
    const profilesNow = () => (profileList.state.ready ? (profileList.state.value?.profiles ?? []) : []);
    const profilesUsable = () => profileList.state.ready && Boolean(profileList.state.value?.available);
    const keyOf = profile => String(profile.id ?? "");
    /**
     * What this page holds about a list while the person works on it (a row being edited, a new row being
     * typed, what the last action said), and one action at a time on it. None of it is the list's own
     * state: that is only ever what the Shell's module answered. An error is said in the Shell's words for
     * its code; the list is read again after every action, whether it worked or not. What an action said
     * stays until the list changes again: "Trabalho está bloqueado." must not outlive its unlocking elsewhere.
     * While an action runs, the list's buttons are disabled (`state.busy`): a click is never dropped unseen.
     */
    // A row of a list is the engine's box item, which keeps the name and the buttons on one line and wraps neither:
    // in a narrow page the name was left a few pixels and broke letter by letter (issue #128). There the buttons
    // go in a row of their own, under the name. A row with more than three buttons needs the room sooner.
    const narrowPage = window.matchMedia("(max-width: 500px)");
    const tightPage = window.matchMedia("(max-width: 650px)");
    const stacked = row => {
      const kind = row.options ? "options" : "items"; // a row's buttons are options; a switch with a setting of its own is an item
      const actions = (row[kind] ?? []).filter(each => each.slot === "actions");
      // `below`: the words a control shows only under the name (a switch beside a name needs none of its own).
      const beside = ({ below, ...control }) => control;
      if (!actions.length || !(narrowPage.matches || (actions.length > 3 && tightPage.matches))) {
        return [row[kind] ? { ...row, [kind]: row[kind].map(beside) } : row];
      }
      const under = ({ slot, below, ...control }) => (below ? { ...control, controlAttrs: { ...control.controlAttrs, label: below } } : control);
      return [
        { ...row, [kind]: row[kind].filter(each => each.slot !== "actions").map(beside) },
        { key: `${row.key}-actions`, control: "moz-box-item", controlAttrs: { class: "nulavio-row-actions" }, [kind]: actions.map(under) },
      ];
    };
    const workbench = (initial, list) => {
      const state = { ...initial, error: "", said: "", busy: false };
      const listeners = new Set();
      // The lists are drawn again when the page becomes narrow or wide: their rows change shape (`stacked`).
      const redraw = () => listeners.forEach(emit => emit());
      for (const page of [narrowPage, tightPage]) {
        page.addEventListener("change", redraw);
        added.cleanups.push(() => page.removeEventListener("change", redraw));
      }
      let settled = true; // false from an action until the list was read again: that read is the action's own result
      let saidFor = ""; // the list as that read found it; the words stay while it stays like that
      const show = changes => {
        Object.assign(state, changes);
        listeners.forEach(emit => emit());
      };
      const watch = (emit, stops) => {
        listeners.add(emit);
        stops.push(() => listeners.delete(emit));
      };
      const act = async (action, said = "", during = "") => {
        if (state.busy) {
          return false;
        }
        show({ busy: true, error: "", said: during }); // `during`: what is happening, for an action that takes a while
        try {
          const answer = await action();
          show({ busy: false, said: typeof said === "function" ? said(answer) : said });
          return true;
        } catch (e) {
          if (!e?.code) {
            console.error(e);
          }
          const code = String(e?.code ?? "unexpected").replace(/[^a-z_-]/gi, "").replaceAll("-", "_");
          show({ busy: false, error: msg(`err_${code}`) || msg("err_unexpected") });
          return false;
        } finally {
          settled = false;
          list.refresh();
        }
      };
      added.cleanups.push(
        list.listen(() => {
          if (!list.state.ready) {
            return;
          }
          const now = JSON.stringify(list.state.value);
          if (!settled) {
            settled = true;
            saidFor = now;
          } else if (!state.busy && (state.said || state.error) && now !== saidFor) {
            show({ said: "", error: "" });
          }
        })
      );
      /** A message bar of this list: shown while `visible`, saying `text`. */
      const bar = (id, type, text, visible) => {
        setting({
          id,
          setup(emitChange, stops) {
            watch(emitChange, stops);
            stops.push(list.listen(emitChange));
          },
          visible,
          getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, type, message: text() } }),
        });
        return { id, control: "moz-message-bar" };
      };
      return { state, show, watch, act, bar };
    };
    // The profiles' own: the row being edited and its unsaved values, and the new profile being typed.
    const profileBench = workbench({ editing: null, draft: null, original: null, fresh: { name: "", template: "", suggested: "" } }, profileList);
    const { state: view, show, watch: viewWatch, act } = profileBench;
    /** After the list is drawn again, the keyboard goes where the person's action left off (never lost to the page). */
    const focusWhenDrawn = selector => {
      let tries = 0;
      const attempt = () => {
        const target = document.querySelector(selector);
        if (target?.getBoundingClientRect().height > 0) {
          target.focus();
        } else if (++tries < 30) {
          window.requestAnimationFrame(attempt);
        }
      };
      window.requestAnimationFrame(attempt);
    };
    const rowButton$ = (key, action) => `#nulavio-profile-list moz-button[data-action="${action}"][data-profile="${key}"]`;
    /** Close the editor and give the keyboard back to the button that opened it. */
    const closeEditor = (extra = {}) => {
      const key = view.editing;
      show({ editing: null, draft: null, original: null, ...extra });
      if (key !== null) {
        focusWhenDrawn(rowButton$(key, "edit"));
      }
    };
    /** The engine's own prompt with the Shell's words. `danger`: Cancel is the default button, as on the Shell's pages. */
    const ask = async (title, body, confirm, danger) => {
      const prompt = Services.prompt;
      const flags =
        prompt.BUTTON_POS_0 * prompt.BUTTON_TITLE_IS_STRING +
        prompt.BUTTON_POS_1 * prompt.BUTTON_TITLE_CANCEL +
        (danger ? prompt.BUTTON_POS_1_DEFAULT : prompt.BUTTON_POS_0_DEFAULT);
      try {
        const answer = await prompt.asyncConfirmEx(window.browsingContext, prompt.MODAL_TYPE_CONTENT, title, body, flags, confirm, null, null, null, false, {
          useTitle: true,
        });
        return answer.get("buttonNumClicked") === 0;
      } catch (e) {
        console.error(e); // the prompt was taken away (its tab is closing): nothing was confirmed
        return false;
      }
    };
    /** A destructive confirmation: something is deleted, closed or loses a protection. */
    const confirmDanger = (title, body, confirm) => ask(title, body, confirm, true);
    /** A step the person asked for that changes what is installed or in use, said before it is done. */
    const confirmStep = (title, body, confirm) => ask(title, body, confirm, false);

    const PROFILE_ROW = profile => {
      if (profile.temporary) {
        return "nulavio-profile-temporary";
      }
      if (profile.protectionUnknown) {
        return "nulavio-profile-unknown"; // not "No password": it is not known (#142)
      }
      return profile.encrypted ? (profile.locked ? "nulavio-profile-locked" : "nulavio-profile-unlocked") : "nulavio-profile-plain";
    };
    // The engine's own profile icons: a disc (context-fill) and a drawing (context-stroke), which the
    // row colours with the profile's tile and glyph (in-content.css, from the design tokens).
    const avatarIcon = avatar => (/^[a-z-]+$/.test(avatar ?? "") ? `chrome://browser/content/profiles/assets/16_${avatar}.svg` : undefined);
    const rowButton = (action, profile, label, named = label, extra = {}) => ({
      key: `${action}-${keyOf(profile)}`,
      control: "moz-button",
      slot: "actions",
      disabled: view.busy,
      // The accessible name keeps the visible words and adds whose button it is ("Abrir Trabalho").
      controlAttrs: { label, "aria-label": named, "data-action": action, "data-profile": keyOf(profile), ...extra },
    });
    const iconButton = (action, profile, iconSrc, named) => ({
      key: `${action}-${keyOf(profile)}`,
      control: "moz-button",
      slot: "actions",
      iconSrc,
      disabled: view.busy,
      controlAttrs: { title: named, "aria-label": named, "data-action": action, "data-profile": keyOf(profile) },
    });
    const profileRows = profile => {
      const actions = [];
      if (!profile.temporary) {
        const name = profile.name;
        if (!profile.isCurrent) {
          actions.push(
            profile.locked
              ? rowButton("unlock", profile, msg("vaultUnlockButton"), msg("profilesUnlockNamed", name))
              : rowButton("open", profile, msg("profilesOpen"), msg("profilesOpenNamed", name))
          );
        }
        if (profile.encrypted && !profile.locked) {
          actions.push(
            profile.isCurrent
              ? rowButton("lock-here", profile, msg("vaultLockNow"), msg("vaultLockCurrent", name))
              : rowButton("lock", profile, msg("vaultLockNow"), `${msg("vaultLockNow")}: ${name}`)
          );
        }
        if (profile.encrypted) {
          actions.push(iconButton("methods", profile, "chrome://browser/skin/login.svg", msg("methodsNamed", name)));
        }
        actions.push(iconButton("edit", profile, "chrome://global/skin/icons/edit-outline.svg", `${msg("profilesEdit")}: ${name}`));
        actions.push(
          iconButton(
            profile.isCurrent ? "delete-here" : "delete",
            profile,
            "chrome://global/skin/icons/delete.svg",
            profile.isCurrent ? msg("profilesDeleteCurrent") : `${msg("profilesDelete")} ${name}`
          )
        );
      }
      const row = {
        key: `profile-${keyOf(profile)}`,
        control: "moz-box-item",
        l10nId: PROFILE_ROW(profile),
        // The name is the person's own text: it goes in as a Fluent argument, never as markup.
        // `kind` is what the profile's own files say ("sensitive": cleared when it closes); a locked one cannot be read, and says nothing.
        l10nArgs: { name: profile.name || "", here: profile.isCurrent ? "yes" : "no", kind: profile.kind === "sensitive" ? "sensitive" : "plain" },
        iconSrc: avatarIcon(profile.avatar),
        controlAttrs: { class: `nulavio-profile nulavio-profile-${profile.color}`, layout: "medium-icon", "data-profile": keyOf(profile) },
        options: actions,
      };
      if (view.editing !== keyOf(profile) || profile.id === null) {
        return stacked(row);
      }
      // The editor opens under its row: the same three things the Shell's page edited, saved together.
      const editor = {
        key: `editor-${keyOf(profile)}`,
        control: "moz-box-item",
        controlAttrs: { class: "nulavio-profile-editor", "data-editor": keyOf(profile) },
        items: [
          { id: "nulavio-profile-name", control: "moz-input-text" },
          { id: "nulavio-profile-avatar", control: "moz-visual-picker" },
          { id: "nulavio-profile-color", control: "moz-visual-picker" },
          { id: "nulavio-profile-editor-buttons", control: "moz-button-group" },
        ],
      };
      return [...stacked(row), editor];
    };
    // "Novo perfil", the last row of the list: a template only fills the name; nothing exists before "Criar perfil".
    const newProfileRow = () => ({
      key: "new-profile",
      control: "moz-box-item",
      slot: "footer",
      controlAttrs: { class: "nulavio-profile-new" },
      items: [
        { id: "nulavio-profile-new-name", control: "moz-input-text" },
        { id: "nulavio-profile-new-template", control: "moz-select" },
        { id: "nulavio-profile-new-create", control: "moz-button" },
      ],
    });
    const profileAction = async (action, key) => {
      const profile = profilesNow().find(each => keyOf(each) === key);
      if (!profile) {
        return;
      }
      const name = profile.name;
      switch (action) {
        case "open":
          await act(() => shell.NulavioProfiles.switchTo(profile.id), msg("profilesOpening", name));
          break;
        case "unlock": // the unlock page is the Vault's own (a page of the Shell, never this one)
          await act(() => shell.NulavioVault.openUnlockPage(profile.id, null, "selector"));
          break;
        case "lock":
          await act(() => shell.NulavioVault.lock(profile.id), msg("vaultLockedNow", name));
          break;
        case "lock-here": // closes every window of this profile, so it asks first
          if (await confirmDanger(msg("vaultLockCurrentTitle", name), msg("vaultLockCurrentBody"), msg("vaultLockCurrentConfirm"))) {
            await act(
              () => shell.NulavioVault.lockCurrent(),
              answer => msg(answer?.quit ? "vaultLockCurrentClosing" : "vaultLockCurrentKept")
            );
          }
          break;
        case "methods": {
          const url = pageOf("vault/methods.html");
          if (url) {
            top().openTrustedLinkIn(`${url}?p=${Number(profile.id)}`, "tab");
          }
          break;
        }
        case "edit":
          if (profile.id === null) {
            // Not in the group's store yet: the engine's own page edits it.
            await act(() => shell.NulavioProfiles.openCurrentPage("edit"));
          } else if (view.editing === key) {
            closeEditor();
          } else {
            const now = { name, avatar: profile.avatar, color: profile.color };
            show({ editing: key, draft: { ...now }, original: now, error: "", said: "" });
            focusWhenDrawn("#nulavio-profile-name");
          }
          break;
        case "delete-here": // the engine's own page deletes the profile in use: it closes this instance safely
          await act(() => shell.NulavioProfiles.openCurrentPage("delete"));
          break;
        case "delete":
          if (await confirmDanger(msg("profilesDeleteTitle", name), msg("profilesDeleteBody"), msg("profilesDeleteConfirm"))) {
            // Its row goes away with it: the keyboard moves to the profile before it in the list.
            // (By its key: the list may have been read again while the prompt was open.)
            const before = profilesNow()[Math.max(0, profilesNow().findIndex(each => keyOf(each) === key) - 1)];
            if ((await act(() => shell.NulavioProfiles.remove(profile.id), msg("profilesDeleted"))) && before) {
              focusWhenDrawn(rowButton$(keyOf(before), "edit"));
            }
          }
          break;
      }
    };
    setting({
      id: "nulavio-profile-list",
      setup(emitChange, stops) {
        stops.push(profileList.listen(emitChange));
        viewWatch(emitChange, stops);
        profileList.refresh();
        try {
          stops.push(shell.NulavioProfiles.subscribe(profileList.refresh)); // created, renamed, locked or removed elsewhere
        } catch (e) {
          console.error(e);
        }
      },
      visible: () => profilesNow().length > 0,
      getControlConfig(config) {
        const rows = profilesNow().flatMap(profileRows);
        return { ...config, options: profilesUsable() ? [...rows, newProfileRow()] : rows };
      },
      onUserClick(event) {
        const button = event.target.closest?.("[data-action]");
        if (button) {
          profileAction(button.dataset.action, button.dataset.profile);
        }
      },
    });

    // The editor's fields hold the unsaved values of the row being edited; nothing is written before "Salvar".
    const editing = () => profilesNow().find(each => keyOf(each) === view.editing) ?? null;
    // The profile being edited changed elsewhere: a field the person did not touch follows it (the editor
    // never shows an old name as the current one); one they changed keeps what they typed. Gone: the editor closes.
    added.cleanups.push(
      profileList.listen(() => {
        if (view.editing === null || !view.draft || !profileList.state.ready) {
          return;
        }
        const profile = editing();
        if (!profile) {
          show({ editing: null, draft: null, original: null });
          return;
        }
        const draft = { ...view.draft };
        const original = { ...view.original };
        for (const field of Object.keys(original)) {
          if (profile[field] !== original[field] && draft[field] === original[field]) {
            draft[field] = original[field] = profile[field];
          }
        }
        if (Object.keys(original).some(field => original[field] !== view.original[field])) {
          show({ draft, original });
        }
      })
    );
    const choice = (value, label, iconSrc) => ({ value, controlAttrs: { label, ...(iconSrc ? { iconsrc: iconSrc } : {}) } });
    const options = shell.NulavioProfiles.options();
    setting({
      id: "nulavio-profile-name",
      setup: viewWatch,
      get: () => view.draft?.name ?? "",
      set(value) {
        if (view.draft) {
          view.draft.name = value;
        }
      },
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("profilesNameLabel") } }),
    });
    // Icon and colour are chosen by looking at them: the engine's picker, with the profile's icon in
    // each choice. A choice is named for someone who cannot see it (its name is also its tooltip).
    const chip = (value, name, avatar, color) => ({
      value,
      controlAttrs: { imagesrc: avatarIcon(avatar), "aria-label": name, title: name, class: `nulavio-chip nulavio-profile-${color}` },
    });
    const draftSetting = (id, field, label, choices) =>
      setting({
        id,
        setup: viewWatch,
        get: () => view.draft?.[field] ?? "",
        set(value) {
          if (view.draft) {
            show({ draft: { ...view.draft, [field]: value } }); // the other picker follows: the icon in the new colour
          }
        },
        getControlConfig: config => ({
          ...config,
          controlAttrs: { ...config.controlAttrs, label: msg(label), class: "nulavio-chips" },
          options: view.draft ? choices(view.draft) : [],
        }),
      });
    draftSetting("nulavio-profile-avatar", "avatar", "profilesIconLabel", draft => {
      // An icon the engine gave the profile and Nulavio does not offer stays listed, so saving a new name keeps it.
      const now = editing()?.avatar;
      const names = now && !options.avatars.includes(now) ? [now, ...options.avatars] : options.avatars;
      return names.map(name => chip(name, msg(`avatar_${name.replaceAll("-", "_")}`) || msg("profilesIconCurrent"), name, draft.color));
    });
    draftSetting("nulavio-profile-color", "color", "profilesColorLabel", draft =>
      options.colors.map(color => chip(color, msg(`color_${color}`), draft.avatar, color))
    );
    // "Salvar" and "Cancelar" are the engine's button pair: it puts them in the order of the desktop.
    setting({
      id: "nulavio-profile-editor-buttons",
      setup: viewWatch,
      async onUserClick(event) {
        const action = event.target.closest?.("[data-action]")?.dataset.action;
        const profile = editing();
        if (action === "cancel" || !profile || !view.draft) {
          closeEditor({ error: "" });
          return;
        }
        if (action !== "save") {
          return;
        }
        // Only what the person changed since the editor opened is written: a name changed elsewhere meanwhile
        // is not put back, and an untouched icon or colour is never sent to be checked again.
        const key = view.editing;
        const changed = Object.fromEntries(Object.entries(view.draft).filter(([field, value]) => value !== view.original[field]));
        if (!Object.keys(changed).length || (await act(() => shell.NulavioProfiles.update(profile.id, changed), msg("doneSaved")))) {
          if (view.editing === key) {
            closeEditor(); // another row's editor, opened while this one was being saved, stays open
          }
        }
      },
      getControlConfig: config => ({
        ...config,
        options: [
          { key: "cancel", control: "moz-button", controlAttrs: { label: msg("confirmCancel"), "data-action": "cancel" } },
          { key: "save", control: "moz-button", disabled: view.busy, controlAttrs: { label: msg("profilesSave"), type: "primary", "data-action": "save" } },
        ],
      }),
    });

    // A new profile: a template fills the name with one that is free ("Trabalho 2"); the person can change it.
    setting({
      id: "nulavio-profile-new-template",
      setup: viewWatch,
      get: () => view.fresh.template,
      set(value) {
        const fresh = { ...view.fresh, template: value };
        if (!fresh.name.trim() || fresh.name === fresh.suggested) {
          fresh.suggested = value ? freeName(msg(TEMPLATE_NAMES[value]), profilesNow().map(each => each.name)) : "";
          fresh.name = fresh.suggested;
        }
        show({ fresh });
      },
      getControlConfig: config => ({
        ...config,
        controlAttrs: { ...config.controlAttrs, label: msg("profilesTemplates"), description: msg(templateHintKey(view.fresh.template || null)) },
        options: [choice("", msg("profilesTemplateNone")), ...options.templates.map(template => choice(template.id, msg(TEMPLATE_NAMES[template.id])))],
      }),
    });
    setting({
      id: "nulavio-profile-new-name",
      setup: viewWatch,
      get: () => view.fresh.name,
      set(value) {
        view.fresh.name = value;
      },
      // The first field of the row says what the row is for; the placeholder says what to type.
      getControlConfig: config => ({
        ...config,
        controlAttrs: { ...config.controlAttrs, label: msg("profilesNew"), placeholder: msg("profilesNameLabel") },
      }),
    });
    setting({
      id: "nulavio-profile-new-create",
      async onUserClick(event) {
        event.preventDefault();
        const { name, template } = view.fresh;
        const created = await act(() => shell.NulavioProfiles.create({ name, ...(template ? { templateId: template } : {}) }), msg("profilesCreated"));
        if (created) {
          show({ fresh: { name: "", template: "", suggested: "" } });
        }
      },
      setup: viewWatch,
      disabled: () => view.busy,
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("profilesCreateButton") } }),
    });

    // What the last action said, and why the list cannot be used when it cannot.
    const bar = profileBench.bar;
    const profileBars = [
      bar(
        "nulavio-profiles-unavailable",
        "info",
        () => {
          const reason = profileList.state.value?.reason;
          return msg(reason === "temporary" ? "profilesTemporaryBar" : reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
        },
        () => profileList.state.ready && !profilesUsable()
      ),
      // 2026-11: profiles that used the old "menta" colour now use "lima"; said once per profile, next to the list.
      bar(
        "nulavio-profiles-migrated",
        "info",
        () =>
          profilesNow()
            .filter(each => each.colorMigration === "mint-to-lima")
            .map(each => msg("profilesColorMigrated", each.name))
            .join(" "),
        () => profilesNow().some(each => each.colorMigration === "mint-to-lima")
      ),
      bar("nulavio-profile-error", "error", () => view.error, () => Boolean(view.error)),
      bar("nulavio-profile-said", "success", () => view.said, () => Boolean(view.said)),
    ];

    // Around the list: a temporary window, a profile protected from its first day, the engine's own manager.
    const profileDoor = (id, label, description, open) => {
      setting({
        id,
        setup(emitChange, stops) {
          stops.push(profileList.listen(emitChange));
          viewWatch(emitChange, stops);
        },
        visible: () => profilesUsable(),
        disabled: () => view.busy,
        onUserClick(event) {
          event.preventDefault();
          open();
        },
        getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg(label), ...(description ? { description: msg(description) } : {}) } }),
      });
      return { id, control: "moz-box-button" };
    };
    const profileDoors = [
      profileDoor("nulavio-profile-temporary", "profilesTemporaryNew", "profilesTemporaryHint", () =>
        act(() => shell.NulavioProfiles.openTemporary(), msg("profilesTemporaryOpening"))
      ),
      // Creating a protected profile shows its recovery code once: that ceremony is the Vault's own page.
      profileDoor("nulavio-profile-protected", "vaultNewProtected", null, () => {
        const url = pageOf("vault/create.html");
        if (url) {
          top().openTrustedLinkIn(url, "tab");
        }
      }),
      profileDoor("nulavio-profile-manager", "profilesFullManager", null, () => act(() => shell.NulavioProfiles.openManager())),
    ];

    // -- which site opens in which profile (ADR 0003): NulavioRouting owns the rules and checks every one;
    // this is the same kind of list as the profiles above it. -------------------------------------------
    const routes = source(() => shell.NulavioRouting.state());
    const routesNow = () => (routes.state.ready ? routes.state.value : null);
    const routingUsable = () => Boolean(routesNow()?.available);
    const targets = () => profilesNow().filter(each => each.id !== null && !each.temporary);
    // With one profile there is nowhere to send a site: the group says so instead of offering an empty form.
    const routingAlone = () => targets().length < 2 && !routesNow()?.rules.length;
    const routeBench = workbench({ fresh: { site: "", match: "domain", action: "open-in", profileId: "" } }, routes);
    const route = routeBench.state;
    const routeSetup = (emitChange, stops) => {
      stops.push(routes.listen(emitChange), profileList.listen(emitChange));
      routeBench.watch(emitChange, stops);
    };
    const routeSetting = config => setting({ setup: routeSetup, visible: () => routingUsable(), ...config });
    const labelled = (label, description) => config => ({
      ...config,
      controlAttrs: { ...config.controlAttrs, label: msg(label), ...(description ? { description: msg(description) } : {}) },
    });
    routeSetting({
      id: "nulavio-routing-enabled",
      setup(emitChange, stops) {
        routeSetup(emitChange, stops);
        routes.refresh();
        try {
          // A rule added from the profile menu, or a profile created, renamed or deleted anywhere.
          stops.push(shell.NulavioRouting.subscribe(routes.refresh), shell.NulavioProfiles.subscribe(routes.refresh));
        } catch (e) {
          console.error(e);
        }
      },
      get: () => Boolean(routesNow()?.enabled),
      set(value) {
        routeBench.act(() => shell.NulavioRouting.setEnabled(Boolean(value)), msg("doneSaved"));
      },
      disabled: () => routeBench.state.busy, // a click while another change is under way would be dropped
      getControlConfig: labelled("routingEnabledLabel"),
    });
    routeSetting({
      id: "nulavio-routing-in-page",
      get: () => Boolean(routesNow()?.inPage),
      set(value) {
        routeBench.act(() => shell.NulavioRouting.setInPage(Boolean(value)), msg("doneSaved"));
      },
      disabled: () => !routesNow()?.enabled || route.busy,
      getControlConfig: labelled("routingInPageLabel", "routingInPageHint"),
    });
    // Where a link from another app opens when no rule names its site.
    routeSetting({
      id: "nulavio-routing-fallback",
      visible: () => routingUsable() && !routingAlone(),
      disabled: () => !routesNow()?.enabled || route.busy,
      get: () => (routesNow()?.fallback.missing ? "missing" : String(routesNow()?.fallback.profileId || 0)),
      set(value) {
        if (value !== "missing") {
          routeBench.act(() => shell.NulavioRouting.setFallback(Number(value)), msg("doneSaved"));
        }
      },
      getControlConfig: config => ({
        ...labelled("routingFallbackLabel", "routingFallbackHint")(config),
        options: [
          choice("0", msg("routingFallbackLast")),
          ...targets().map(each => choice(keyOf(each), msg(each.encrypted ? "routingFallbackAlwaysProtected" : "routingFallbackAlways", each.name))),
          // A deleted destination keeps its own entry: a profile created later can take the same id, and
          // choosing this entry must never make that profile the destination.
          ...(routesNow()?.fallback.missing ? [{ ...choice("missing", msg("routingFallbackGone")), disabled: true }] : []),
        ],
      }),
    });
    const ruleKey = rule => String(rule.id);
    const ruleRow = rule => {
      const target = rule.action === "stay" ? null : targets().find(each => each.id === rule.profileId);
      // What the rule does, as the Shell's page said it: where it opens and how, or that its profile is gone.
      const does =
        rule.action === "stay"
          ? msg("routingActionStay")
          : rule.missing
            ? msg("routingTargetMissing")
            : `${rule.profileName} · ${msg({ "open-in": "routingActionOpen", ask: "routingActionAsk" }[rule.action] ?? "routingActionOpen")}`;
      return {
        key: `rule-${ruleKey(rule)}`,
        control: "moz-box-item",
        iconSrc: target ? avatarIcon(target.avatar) : undefined,
        controlAttrs: {
          // The site is the person's own text: it is set as the row's label, never parsed.
          label: rule.match === "domain" ? msg("routingScopeDomain", rule.display) : rule.display,
          description: does,
          class: target ? `nulavio-profile nulavio-profile-${target.color}` : "nulavio-rule",
          layout: "medium-icon",
          "data-rule": ruleKey(rule),
        },
        options: [
          {
            key: `remove-${ruleKey(rule)}`,
            control: "moz-button",
            slot: "actions",
            iconSrc: "chrome://global/skin/icons/delete.svg",
            disabled: route.busy,
            controlAttrs: {
              title: `${msg("engineRemove")} ${rule.display}`,
              "aria-label": `${msg("engineRemove")} ${rule.display}`,
              "data-action": "remove",
              "data-rule": ruleKey(rule),
            },
          },
        ],
      };
    };
    routeSetting({
      id: "nulavio-routing-rules",
      visible: () => routingUsable() && !routingAlone(),
      getControlConfig(config) {
        const rules = routesNow()?.rules ?? [];
        const rows = rules.length
          ? rules.flatMap(rule => stacked(ruleRow(rule)))
          : [{ key: "no-rules", control: "moz-box-item", controlAttrs: { label: msg("routingNoRules"), class: "nulavio-rule-none" } }];
        const form = {
          key: "new-rule",
          control: "moz-box-item",
          slot: "footer",
          controlAttrs: { class: "nulavio-profile-new" },
          items: [
            { id: "nulavio-routing-site", control: "moz-input-text" },
            { id: "nulavio-routing-match", control: "moz-select" },
            { id: "nulavio-routing-profile", control: "moz-select" },
            { id: "nulavio-routing-action", control: "moz-select" },
            { id: "nulavio-routing-add", control: "moz-button" },
          ],
        };
        return { ...config, options: [...rows, form] };
      },
      onUserClick(event) {
        const button = event.target.closest?.('[data-action="remove"]');
        const rule = (routesNow()?.rules ?? []).find(each => ruleKey(each) === button?.dataset.rule);
        if (rule) {
          routeBench.act(() => shell.NulavioRouting.removeRule(rule.id), msg("doneRemoved")).then(removed => {
            if (removed) {
              focusWhenDrawn("#nulavio-routing-site"); // its row is gone: the keyboard goes to the next thing to do
            }
          });
        }
      },
    });
    // The new rule's fields hold what was typed; nothing is written before "Adicionar regra".
    const freshRoute = (id, field, extra) =>
      routeSetting({
        id,
        visible: () => routingUsable() && !routingAlone(),
        get: () => route.fresh[field],
        set(value) {
          routeBench.show({ fresh: { ...route.fresh, [field]: value } });
        },
        ...extra,
      });
    freshRoute("nulavio-routing-site", "site", {
      getControlConfig: config => ({
        ...config,
        controlAttrs: { ...config.controlAttrs, label: msg("routingAddHeading"), placeholder: "example.com" },
      }),
    });
    freshRoute("nulavio-routing-match", "match", {
      getControlConfig: config => ({
        ...labelled("routingMatchLabel")(config),
        options: [choice("domain", msg("routingMatchDomain")), choice("host", msg("routingMatchHost"))],
      }),
    });
    freshRoute("nulavio-routing-action", "action", {
      getControlConfig: config => ({
        ...labelled("routingActionLabel")(config),
        options: [
          choice("open-in", msg("routingActionOpen")),
          choice("ask", msg("routingActionAsk")),
          choice("stay", msg("routingActionStay")),
        ],
      }),
    });
    // The profile a rule opens in; "never switch" names no profile, so the choice leaves with it.
    const routeTarget = () => (targets().some(each => keyOf(each) === route.fresh.profileId) ? route.fresh.profileId : keyOf(targets()[0] ?? {}));
    freshRoute("nulavio-routing-profile", "profileId", {
      visible: () => routingUsable() && !routingAlone() && route.fresh.action !== "stay",
      get: routeTarget,
      getControlConfig: config => ({ ...labelled("routingProfileLabel")(config), options: targets().map(each => choice(keyOf(each), each.name)) }),
    });
    routeSetting({
      id: "nulavio-routing-add",
      visible: () => routingUsable() && !routingAlone(),
      async onUserClick(event) {
        event.preventDefault();
        const { site, match, action } = route.fresh;
        const rule = { site, match, action, ...(action === "stay" ? {} : { profileId: Number(routeTarget()) }) };
        if (await routeBench.act(() => shell.NulavioRouting.addRule(rule), msg("doneAdded"))) {
          routeBench.show({ fresh: { ...route.fresh, site: "" } });
        }
      },
      disabled: () => route.busy,
      getControlConfig: labelled("routingAddButton"),
    });
    const routeBar = routeBench.bar;
    const routingBars = [
      routeBar(
        "nulavio-routing-alone",
        "info",
        () => `${msg("routingNeedsTwoTitle")}. ${msg("routingNeedsTwoText")}`,
        () => routingUsable() && profileList.state.ready && routingAlone()
      ),
      // The note says links stop at a warning page: true only while the rules are in use.
      routeBar(
        "nulavio-routing-fallback-missing",
        "warning",
        () => msg("routingFallbackMissing"),
        () => routingUsable() && Boolean(routesNow()?.fallback.missing) && Boolean(routesNow()?.enabled)
      ),
      routeBar("nulavio-routing-error", "error", () => route.error, () => Boolean(route.error)),
      routeBar("nulavio-routing-said", "success", () => route.said, () => Boolean(route.said)),
    ];

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
      // The list below marks the manager in use; this row speaks only when none of the managers Nulavio knows is on.
      visible: () => passwords.state.ready && passwords.state.value?.current === "none",
      getControlConfig: config => ({ ...config, l10nId: "nulavio-passwords-now-none" }),
    });

    // -- who saves and fills passwords in this profile: the browser's own manager or one of the managers
    // Nulavio knows how to install from the official extension (NulavioPasswords pins and checks the file).
    const passwordBench = workbench({}, passwords);
    const providerName = item => (item.key === "builtin" ? msg("passwordsBuiltin") : item.extension.name);
    const providerStatus = item => {
      if (item.key === "builtin") {
        return msg("passwordsBuiltinNote");
      }
      const extension = item.extension;
      const parts = [
        extension.enabled
          ? msg("passwordsInstalled", extension.version)
          : extension.installed
            ? msg("passwordsInstalledOff")
            : msg("passwordsNotInstalled", extension.pinned),
      ];
      if (item.native && !item.native.found) {
        parts.push(msg(item.native.required ? "passwordsNativeMissing" : "passwordsNativeOptional"));
      }
      return parts.join(" ");
    };
    const providerRow = item => {
      const inUse = passwords.state.value.current === item.key;
      const name = providerName(item);
      const button = (action, label) => ({
        key: `${action}-${item.key}`,
        control: "moz-button",
        slot: "actions",
        disabled: passwordBench.state.busy,
        controlAttrs: { label, "aria-label": `${label}: ${name}`, "data-action": action, "data-provider": item.key },
      });
      return {
        key: `provider-${item.key}`,
        control: "moz-box-item",
        controlAttrs: {
          label: inUse ? `${name} (${msg("passwordsInUse")})` : name,
          description: providerStatus(item),
          class: "nulavio-provider",
          "data-provider": item.key,
          "data-in-use": String(inUse),
        },
        // The one in use has nothing to choose; an extension in use can give the job back to the browser.
        options: inUse ? (item.key === "builtin" ? [] : [button("off", msg("passwordsDisableIntegration"))]) : [button("use", msg("passwordsUse"))],
      };
    };
    setting({
      id: "nulavio-passwords-providers",
      setup(emitChange, stops) {
        stops.push(passwords.listen(emitChange));
        passwordBench.watch(emitChange, stops);
      },
      visible: () => passwords.state.ready,
      getControlConfig: config => ({ ...config, options: (passwords.state.value?.providers ?? []).flatMap(item => stacked(providerRow(item))) }),
      async onUserClick(event) {
        const button = event.target.closest?.("[data-action]");
        const item = (passwords.state.value?.providers ?? []).find(each => each.key === button?.dataset.provider);
        if (!item) {
          return;
        }
        const name = providerName(item);
        if (button.dataset.action === "off") {
          if (await confirmStep(msg("passwordsDisableTitle"), msg("passwordsDisableBody", name), msg("passwordsDisableIntegration"))) {
            await passwordBench.act(() => shell.NulavioPasswords.choose("builtin"), msg("passwordsChosen", msg("passwordsBuiltin")));
          }
          return;
        }
        // An extension that is not there yet is installed only after the page said what will be installed, and from where.
        const installs = Boolean(item.extension && !item.extension.installed);
        if (
          installs &&
          !(await confirmStep(msg("passwordsConfirmTitle", name), msg("passwordsConfirmBody", name, item.extension.pinned), msg("passwordsConfirmButton")))
        ) {
          return;
        }
        await passwordBench.act(() => shell.NulavioPasswords.choose(item.key), msg("passwordsChosen", name), installs ? msg("passwordsInstalling", name) : "");
      },
    });
    // How many logins the browser's own manager holds here (a count; they are kept when the manager changes).
    setting({
      id: "nulavio-passwords-logins",
      setup: (emitChange, stops) => stops.push(passwords.listen(emitChange)),
      visible: () => passwords.state.ready,
      getControlConfig(config) {
        const count = passwords.state.value?.engineLogins ?? 0;
        const label = count === 0 ? msg("passwordsEngineLoginsNone") : count === 1 ? msg("passwordsEngineLoginsOne") : msg("passwordsEngineLogins", String(count));
        return { ...config, controlAttrs: { ...config.controlAttrs, label } };
      },
    });
    const passwordBars = [
      passwordBench.bar("nulavio-passwords-error", "error", () => passwordBench.state.error, () => Boolean(passwordBench.state.error)),
      passwordBench.bar("nulavio-passwords-said", "success", () => passwordBench.state.said, () => Boolean(passwordBench.state.said)),
    ];

    // -- look-alike sites the person chose to continue on: each can be removed, and the warning comes back --
    const confirmed = source(async () => shell.NulavioPasswords.listConfirmed());
    const confirmedBench = workbench({}, confirmed);
    setting({
      id: "nulavio-confirmed-sites",
      setup(emitChange, stops) {
        stops.push(confirmed.listen(emitChange));
        confirmedBench.watch(emitChange, stops);
        confirmed.refresh();
      },
      visible: () => confirmed.state.ready,
      getControlConfig(config) {
        const rows = (confirmed.state.value ?? []).flatMap(pair => stacked({
          key: `confirmed-${pair.site} ${pair.similar}`,
          control: "moz-box-item",
          controlAttrs: {
            label: pair.site,
            description: msg("passwordsConfirmedLooksLike", pair.similar),
            class: "nulavio-confirmed",
            "data-site": pair.site,
            "data-similar": pair.similar,
          },
          options: [
            {
              key: `remove-${pair.site} ${pair.similar}`,
              control: "moz-button",
              slot: "actions",
              iconSrc: "chrome://global/skin/icons/delete.svg",
              disabled: confirmedBench.state.busy,
              controlAttrs: {
                title: msg("passwordsConfirmedRemoveNamed", pair.site),
                "aria-label": msg("passwordsConfirmedRemoveNamed", pair.site),
                "data-action": "remove",
                "data-site": pair.site,
                "data-similar": pair.similar,
              },
            },
          ],
        }));
        const none = { key: "none", control: "moz-box-item", controlAttrs: { label: msg("passwordsConfirmedNone"), class: "nulavio-confirmed-none" } };
        return { ...config, options: rows.length ? rows : [none] };
      },
      async onUserClick(event) {
        const button = event.target.closest?.('[data-action="remove"]');
        const pair = (confirmed.state.value ?? []).find(each => each.site === button?.dataset.site && each.similar === button?.dataset.similar);
        if (pair && (await confirmedBench.act(async () => shell.NulavioPasswords.removeConfirmed(pair.site, pair.similar), msg("passwordsConfirmedRemoved", pair.site)))) {
          focusWhenDrawn('#nulavio-confirmed-sites moz-button[data-action="remove"]');
        }
      },
    });
    const confirmedBars = [
      confirmedBench.bar("nulavio-confirmed-error", "error", () => confirmedBench.state.error, () => Boolean(confirmedBench.state.error)),
      confirmedBench.bar("nulavio-confirmed-said", "success", () => confirmedBench.state.said, () => Boolean(confirmedBench.state.said)),
    ];

    // -- search: what Nulavio adds to the engine's own Search pane. Which engines may receive what the person
    // types (suggestions, engine by engine: NulavioSearch keeps that list and the engine's patch reads it), and
    // the engines Nulavio knows how to add. Default engine, aliases and removal are the engine's own controls. --
    const search = source(() => shell.NulavioSearch.state());
    const searchBench = workbench({ fresh: { searxng: "", opensearch: "" } }, search);
    const enginesNow = () => (search.state.ready ? (search.state.value?.engines ?? []) : []);
    const searchSetup = (emitChange, stops) => {
      stops.push(search.listen(emitChange));
      searchBench.watch(emitChange, stops);
    };
    // One switch per engine, registered the first time the engine is seen (the engine's own list does the same).
    const suggestSwitch = engine => {
      const id = `nulavio-suggest-${engine.id}`;
      if (!Preferences.getSetting(id)) {
        setting({
          id,
          setup: searchSetup,
          get: () => Boolean(enginesNow().find(each => each.id === engine.id)?.suggestOptIn),
          set(value) {
            searchBench.act(() => shell.NulavioSearch.setSuggestOptIn(engine.id, Boolean(value)), msg("doneSaved"));
          },
          disabled: () => searchBench.state.busy,
        });
      }
      return id;
    };
    setting({
      id: "nulavio-suggest-engines",
      setup(emitChange, stops) {
        searchSetup(emitChange, stops);
        search.refresh();
        try {
          stops.push(shell.NulavioSearch.subscribe(search.refresh)); // an engine added, removed or switched in the engine's own list
        } catch (e) {
          console.error(e);
        }
      },
      // Only the engines that offer suggestions have something to switch.
      visible: () => enginesNow().some(engine => engine.canSuggest),
      getControlConfig: config => ({
        ...config,
        options: enginesNow()
          .filter(engine => engine.canSuggest)
          .flatMap(engine => stacked({
            key: `suggest-${engine.id}`,
            control: "moz-box-item",
            controlAttrs: {
              label: engine.name,
              // What happens to what is typed, in words: where it goes when on, that nothing goes when off.
              // Allowed here and off in the engine's own "Show search suggestions": nothing goes (#142).
              description: !engine.suggestOptIn
                ? msg("engineSuggestOff")
                : search.state.value?.suggestions
                  ? msg("engineSuggestOn", engine.suggestHost)
                  : msg("engineSuggestPaused"),
              class: "nulavio-engine",
              "data-engine": engine.id,
            },
            items: [
              {
                id: suggestSwitch(engine),
                control: "moz-toggle",
                slot: "actions",
                below: msg("engineSuggestLabel"),
                controlAttrs: { "aria-label": `${msg("engineSuggestLabel")}: ${engine.name}`, "data-engine": engine.id },
              },
            ],
          })),
      }),
    });
    // The providers Nulavio offers by name and the person does not have yet: one click each.
    const missingProviders = () => {
      const have = new Set(enginesNow().map(engine => engine.provider).filter(Boolean));
      return (search.state.value?.providers ?? []).filter(provider => !have.has(provider.key));
    };
    setting({
      id: "nulavio-search-providers",
      setup: searchSetup,
      visible: () => search.state.ready,
      getControlConfig(config) {
        const rows = missingProviders().flatMap(provider => stacked({
          key: `provider-${provider.key}`,
          control: "moz-box-item",
          controlAttrs: {
            label: provider.name,
            ...(provider.key === "kagi" ? { description: msg("addProviderKagiNote") } : {}),
            class: "nulavio-search-provider",
            "data-provider": provider.key,
          },
          options: [
            {
              key: `add-${provider.key}`,
              control: "moz-button",
              slot: "actions",
              disabled: searchBench.state.busy,
              controlAttrs: { label: msg("addProviderButton", provider.name), "data-action": "add", "data-provider": provider.key },
            },
          ],
        }));
        const none = { key: "none", control: "moz-box-item", controlAttrs: { label: msg("addProvidersNone"), class: "nulavio-search-provider-none" } };
        return { ...config, options: rows.length ? rows : [none] };
      },
      onUserClick(event) {
        const key = event.target.closest?.('[data-action="add"]')?.dataset.provider;
        if (missingProviders().some(provider => provider.key === key)) {
          searchBench.act(() => shell.NulavioSearch.addProvider(key), msg("doneAdded"));
        }
      },
    });
    // An instance of the person's own, or a site's own description: an address typed here, added by the module's rules.
    const addByAddress = (name, add, words) => {
      setting({
        id: `nulavio-search-${name}-url`,
        setup: searchSetup,
        visible: () => search.state.ready,
        get: () => searchBench.state.fresh[name],
        set(value) {
          searchBench.state.fresh[name] = value;
        },
        getControlConfig: config => ({
          ...config,
          controlAttrs: { ...config.controlAttrs, label: msg(words.label), description: msg(words.note), placeholder: words.placeholder },
        }),
      });
      setting({
        id: `nulavio-search-${name}-add`,
        setup: searchSetup,
        visible: () => search.state.ready,
        disabled: () => searchBench.state.busy,
        async onUserClick(event) {
          event.preventDefault();
          if (await searchBench.act(() => add(searchBench.state.fresh[name]), msg("doneAdded"))) {
            searchBench.show({ fresh: { ...searchBench.state.fresh, [name]: "" } });
          }
        },
        getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg(words.button) } }),
      });
      return [
        { id: `nulavio-search-${name}-url`, control: "moz-input-text" },
        { id: `nulavio-search-${name}-add`, control: "moz-button" },
      ];
    };
    const searchForms = [
      ...addByAddress("searxng", url => shell.NulavioSearch.addSearxng({ url }), {
        label: "addSearxngLabel",
        note: "addSearxngNote",
        button: "addSearxngButton",
        placeholder: "https://searx.example.org/",
      }),
      ...addByAddress("opensearch", url => shell.NulavioSearch.addOpenSearch({ url }), {
        label: "addOpenSearchLabel",
        note: "addOpenSearchNote",
        button: "addOpenSearchButton",
        placeholder: "https://example.org/opensearch.xml",
      }),
    ];
    const searchBars = [
      searchBench.bar("nulavio-search-error", "error", () => searchBench.state.error, () => Boolean(searchBench.state.error)),
      searchBench.bar("nulavio-search-said", "success", () => searchBench.state.said, () => Boolean(searchBench.state.said)),
    ];

    // -- what the content filter blocks: uBlock Origin's own lists, on its own page. Nulavio reads whether it
    // is on and whether a cookie-notice list is switched on, and writes nothing there: lists change on its page. --
    const filter = source(async () => ({ ...shell.NulavioPrivacy.filter(), lists: await shell.NulavioPrivacy.filterLists() }));
    setting({
      id: "nulavio-filter-lists",
      setup(emitChange, stops) {
        stops.push(filter.listen(emitChange));
        filter.refresh();
        const { AddonManager } = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
        const changed = () => filter.refresh();
        const listener = { onInstalled: changed, onUninstalled: changed, onEnabled: changed, onDisabled: changed };
        AddonManager.addAddonListener(listener);
        stops.push(() => AddonManager.removeAddonListener(listener));
      },
      visible: () => filter.state.ready,
      onUserClick(event) {
        event.preventDefault();
        if (filter.state.value?.active) {
          shell.NulavioPrivacy.openFilterLists(top()); // in this window, not the one used last
        } else {
          top().BrowserAddonUI.openAddonsMgr("addons://list/extension"); // where it is turned on, or seen to be missing
        }
      },
      // Whether cookie notices are hidden is said only when it was read; otherwise the row says what depends on the lists.
      getControlConfig(config) {
        const now = filter.state.value;
        if (now?.active === false) {
          return { ...config, l10nId: "nulavio-filter-lists-off" };
        }
        const cookies = now?.lists?.cookieNotices;
        return typeof cookies === "boolean" ? { ...config, l10nId: `nulavio-filter-lists-cookies-${cookies ? "hidden" : "shown"}` } : config;
      },
    });

    // -- site exceptions: where a protection is off or relaxed for one site. NulavioPrivacy reads them from
    // the engine's own permission store; removing one puts the protection back for that site. ------------
    const exceptions = source(() => shell.NulavioPrivacy.exceptions());
    const exceptionsNow = () => (exceptions.state.ready ? (exceptions.state.value ?? []) : []);
    const exceptionBench = workbench({}, exceptions);
    const EXCEPTION_WORDS = {
      trackingprotection: { allow: "exceptionTracking" },
      "trackingprotection-pb": { allow: "exceptionTrackingPrivate" },
      "https-only-load-insecure": { allow: "exceptionHttpsOnly", session: "exceptionHttpsOnlySession" },
      cookie: { allow: "exceptionCookieAllow", deny: "exceptionCookieDeny", session: "exceptionCookieSession" },
      install: { allow: "exceptionInstall" },
      popup: { allow: "exceptionPopup" },
    };
    const exceptionWhat = entry => {
      const key = EXCEPTION_WORDS[entry.type]?.[entry.capability] ?? EXCEPTION_WORDS[entry.type]?.allow;
      return key ? msg(key) : `${entry.type} (${entry.capability})`;
    };
    const exceptionRow = entry => {
      const what = exceptionWhat(entry);
      // What is relaxed, for how long and where, and whether the browser itself put it there.
      const notes = [
        what,
        entry.session ? msg("exceptionUntilClose") : null,
        entry.private ? msg("exceptionPrivate") : null,
        entry.builtIn ? msg("exceptionBuiltInBadge") : null,
      ].filter(Boolean);
      return {
        key: `exception-${entry.type}-${entry.origin}`,
        control: "moz-box-item",
        // The site is set as the row's label, never parsed.
        controlAttrs: { label: entry.site, description: notes.join(" · "), class: "nulavio-exception", "data-type": entry.type, "data-origin": entry.origin },
        options: [
          {
            key: `remove-${entry.type}-${entry.origin}`,
            control: "moz-button",
            slot: "actions",
            iconSrc: "chrome://global/skin/icons/delete.svg",
            disabled: exceptionBench.state.busy,
            controlAttrs: {
              title: `${msg("engineRemove")}: ${entry.site} — ${what}`,
              "aria-label": `${msg("engineRemove")}: ${entry.site} — ${what}`,
              "data-action": "remove",
              // Found again by what it is, never by its place in a list that may have been read again.
              "data-type": entry.type,
              "data-origin": entry.origin,
            },
          },
        ],
      };
    };
    setting({
      id: "nulavio-exceptions",
      setup(emitChange, stops) {
        stops.push(exceptions.listen(emitChange));
        exceptionBench.watch(emitChange, stops);
        exceptions.refresh();
        try {
          stops.push(shell.NulavioPrivacy.subscribe(exceptions.refresh)); // allowed or removed from the site's own panel
        } catch (e) {
          console.error(e);
        }
      },
      visible: () => exceptions.state.ready,
      getControlConfig(config) {
        const rows = exceptionsNow().flatMap(each => stacked(exceptionRow(each)));
        const none = { key: "none", control: "moz-box-item", controlAttrs: { label: msg("exceptionsEmpty"), class: "nulavio-exception-none" } };
        return { ...config, options: rows.length ? rows : [none] };
      },
      async onUserClick(event) {
        const button = event.target.closest?.('[data-action="remove"]');
        const entry = button ? exceptionsNow().find(each => each.type === button.dataset.type && each.origin === button.dataset.origin) : null;
        if (!entry) {
          return;
        }
        const what = exceptionWhat(entry);
        // A browser default is removed only after its consequence is said.
        if (
          entry.builtIn &&
          !(await confirmDanger(msg("exceptionRemoveBuiltInTitle"), msg("exceptionRemoveBuiltInBody", entry.site, what), msg("engineRemove")))
        ) {
          return;
        }
        if (await exceptionBench.act(() => shell.NulavioPrivacy.remove(entry.type, entry.origin), msg("doneRemoved"))) {
          focusWhenDrawn('#nulavio-exceptions moz-button[data-action="remove"]'); // its row is gone with the focus on it
        }
      },
    });
    // uBlock Origin keeps its own list of sites where it does not filter: its page, never its data.
    setting({
      id: "nulavio-filter-trusted",
      setup: (emitChange, stops) => stops.push(filter.listen(emitChange)),
      visible: () => Boolean(filter.state.value?.active),
      onUserClick(event) {
        event.preventDefault();
        shell.NulavioPrivacy.openFilterList();
      },
      getControlConfig: config => ({
        ...config,
        controlAttrs: { ...config.controlAttrs, label: msg("exceptionsFilterOpen"), description: msg("exceptionsFilterOn") },
      }),
    });
    const exceptionBars = [
      exceptionBench.bar("nulavio-exceptions-error", "error", () => exceptionBench.state.error, () => Boolean(exceptionBench.state.error)),
      exceptionBench.bar("nulavio-exceptions-said", "success", () => exceptionBench.state.said, () => Boolean(exceptionBench.state.said)),
    ];

    // -- who answers when this profile looks up a site (DNS). Three choices in plain words, where the engine
    // showed a one-line summary; the engine's own advanced screen stays behind its button. A wrong choice can
    // stop sites from opening, so nothing is written before "Salvar escolha" (NulavioPrivacy.setDns checks it). --
    const dns = source(async () => shell.NulavioPrivacy.dns());
    const dnsBench = workbench({ draft: null }, dns);
    const dnsNow = () => (dns.state.ready ? dns.state.value : null);
    // A policy that locks the resolver: nothing here can change it, so nothing here looks as if it could.
    const dnsLocked = () => Boolean(dnsNow()?.locked);
    const hostOf = address => {
      try {
        return new URL(address).host;
      } catch {
        return msg("dnsCustom");
      }
    };
    // What the form shows: what the person changed and has not saved yet, over what is in effect.
    const dnsForm = () => {
      const now = dnsNow();
      const base = { choice: now?.choice ?? "", provider: now?.provider ?? "cloudflare", uri: now?.provider === "custom" ? now.uri : "" };
      return { ...base, ...(dnsBench.state.draft ?? {}) };
    };
    const dnsChanged = () => {
      const now = dnsNow();
      const form = dnsForm();
      if (!now || !form.choice || form.choice === "default") {
        return false; // "Padrão do navegador (atual)" is what is in effect: nothing to save
      }
      if (form.choice !== now.choice) {
        return true;
      }
      return form.choice !== "system" && (form.provider !== (now.provider ?? "cloudflare") || (form.provider === "custom" && form.uri !== now.uri));
    };
    const dnsProviderName = id => msg(`dns${id[0].toUpperCase()}${id.slice(1)}`);
    const dnsSays = () => {
      const now = dnsNow();
      if (!now) {
        return "";
      }
      if (now.choice === "system") {
        return msg("dnsNowSystem");
      }
      if (now.choice === "default") {
        // What the default does right now, and by which resolver: the engine's word for the one in use.
        if (!now.encryptedNow) {
          return msg("dnsNowDefaultPlain");
        }
        if (!now.resolver) {
          return msg("dnsNowDefaultEncryptedUnnamed"); // encrypted, and the engine did not say by which resolver
        }
        return now.resolver === "cloudflare"
          ? msg("dnsNowDefaultEncrypted")
          : msg("dnsNowDefaultEncryptedBy", now.resolver === "custom" ? hostOf(now.resolverUri) : dnsProviderName(now.resolver));
      }
      return msg(now.choice === "strict" ? "dnsNowStrict" : "dnsNowFallback", now.provider === "custom" ? now.uri : dnsProviderName(now.provider));
    };
    const dnsSetup = (emitChange, stops) => {
      stops.push(dns.listen(emitChange));
      dnsBench.watch(emitChange, stops);
    };
    const dnsDraft = (field, value) => dnsBench.show({ draft: { ...(dnsBench.state.draft ?? {}), [field]: value } });
    setting({
      id: "nulavio-dns-choice",
      setup(emitChange, stops) {
        dnsSetup(emitChange, stops);
        dns.refresh();
        // Changed on the engine's advanced screen, or by a policy.
        for (const pref of ["network.trr.mode", "network.trr.uri"]) {
          Services.prefs.addObserver(pref, dns.refresh);
          stops.push(() => Services.prefs.removeObserver(pref, dns.refresh));
        }
      },
      visible: () => dns.state.ready,
      get: () => dnsForm().choice,
      set(value) {
        dnsDraft("choice", value);
      },
      disabled: () => dnsBench.state.busy || dnsLocked(),
      getControlConfig(config) {
        const option = (value, label, note) => ({ value, controlAttrs: { label: msg(label), description: msg(note) } });
        return {
          ...config,
          controlAttrs: { ...config.controlAttrs, label: msg("dnsChoiceLegend"), description: dnsSays() },
          options: [
            // Listed, and marked, only while nothing was chosen yet: choosing it saves nothing.
            ...(dnsNow()?.choice === "default" ? [option("default", "dnsDefaultOption", "dnsDefaultOptionNote")] : []),
            option("system", "dnsOptionNetwork", "dnsOptionNetworkNote"),
            option("fallback", "dnsOptionService", "dnsOptionServiceNote"),
            option("strict", "dnsStrict", "dnsStrictNote"),
          ],
        };
      },
    });
    const dnsEncrypted = () => ["fallback", "strict"].includes(dnsForm().choice);
    setting({
      id: "nulavio-dns-provider",
      setup: dnsSetup,
      visible: () => dns.state.ready && dnsEncrypted(),
      get: () => dnsForm().provider,
      set(value) {
        dnsDraft("provider", value);
      },
      disabled: () => dnsBench.state.busy || dnsLocked(),
      getControlConfig: config => ({
        ...config,
        // Whoever is chosen sees which sites this profile looks up: said where the choice is made.
        controlAttrs: { ...config.controlAttrs, label: msg("dnsOptionServiceLabel"), description: msg("dnsThirdParty") },
        options: [...(dnsNow()?.providers ?? []).map(provider => choice(provider.id, dnsProviderName(provider.id))), choice("custom", msg("dnsCustom"))],
      }),
    });
    setting({
      id: "nulavio-dns-uri",
      setup: dnsSetup,
      visible: () => dns.state.ready && dnsEncrypted() && dnsForm().provider === "custom",
      get: () => dnsForm().uri,
      set(value) {
        dnsDraft("uri", value);
      },
      disabled: () => dnsBench.state.busy || dnsLocked(),
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("dnsUriLabel"), placeholder: "https://" } }),
    });
    setting({
      id: "nulavio-dns-save",
      setup: dnsSetup,
      visible: () => dns.state.ready,
      // Only when the form says something other than what is in effect.
      disabled: () => dnsBench.state.busy || dnsLocked() || !dnsChanged(),
      async onUserClick(event) {
        event.preventDefault();
        const { choice: chosen, provider, uri } = dnsForm();
        if (await dnsBench.act(async () => shell.NulavioPrivacy.setDns({ choice: chosen, provider, uri }), msg("dnsSaved"))) {
          dnsBench.show({ draft: null });
        }
      },
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("dnsSave"), type: "primary" } }),
    });
    const dnsItems = [
      failureNote("nulavio-dns-failed", dns),
      dnsBench.bar("nulavio-dns-error", "error", () => dnsBench.state.error, () => Boolean(dnsBench.state.error)),
      dnsBench.bar("nulavio-dns-said", "success", () => dnsBench.state.said, () => Boolean(dnsBench.state.said)),
      { id: "nulavio-dns-choice", control: "moz-radio-group" },
      { id: "nulavio-dns-provider", control: "moz-select" },
      { id: "nulavio-dns-uri", control: "moz-input-text" },
      { id: "nulavio-dns-save", control: "moz-button" },
    ];

    // -- assistant and agents: what is a setting is here (the emergency stop, and the service the assistant
    // talks to). Granting an agent its permissions, connecting one and the activity record are moments of
    // consent and a record: they stay the Shell's own page, behind the row at the end. NulavioAI refuses every
    // change asked from a window an agent drives, whoever asks; here such a window shows no control at all. --
    const ai = source(async () => {
      const agent = await shell.NulavioAI.workspaceAgent();
      if (agent) {
        const { agents } = await shell.NulavioAI.overview().catch(() => ({ agents: [] }));
        return { workspace: agents.find(each => each.id === agent)?.name ?? agent };
      }
      const [overview, assistant] = await Promise.all([shell.NulavioAI.overview(), shell.NulavioAI.assistantState(top())]);
      return { workspace: "", stopped: Boolean(overview.stopped), assistant };
    });
    const aiBench = workbench({ draft: null }, ai);
    const aiNow = () => (ai.state.ready ? ai.state.value : null);
    const aiOpen = () => Boolean(aiNow()) && !aiNow().workspace; // read, and not a window an agent drives
    const aiSetup = (emitChange, stops) => {
      stops.push(ai.listen(emitChange));
      aiBench.watch(emitChange, stops);
    };
    const aiSetting = config => setting({ setup: aiSetup, visible: aiOpen, ...config });
    aiSetting({
      id: "nulavio-ai-stop",
      setup(emitChange, stops) {
        aiSetup(emitChange, stops);
        ai.refresh();
      },
      get: () => Boolean(aiNow()?.stopped),
      set(value) {
        aiBench.act(() => shell.NulavioAI.setStopped(Boolean(value)), msg(value ? "aiStoppedNow" : "aiResumedNow"));
      },
      disabled: () => aiBench.state.busy,
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("aiStopLabel"), description: msg("aiStopHint") } }),
    });
    // The assistant's service: what is saved, with what the person changed and has not saved yet on top.
    // The API key is never read back: the field is empty, and an empty field keeps the key there is.
    const assistantNow = () => aiNow()?.assistant ?? null;
    const assistantForm = () => {
      const now = assistantNow();
      const base = { kind: now?.provider?.kind ?? "openai", model: now?.provider?.model ?? "", baseUrl: now?.provider?.base_url ?? "", key: "" };
      return { ...base, ...(aiBench.state.draft ?? {}) };
    };
    const assistantDraft = (field, value) => aiBench.show({ draft: { ...(aiBench.state.draft ?? {}), [field]: value } });
    aiSetting({
      id: "nulavio-assistant-now",
      getControlConfig(config) {
        const now = assistantNow();
        const says = now?.configured
          ? msg("assistantStateConfigured", now.provider.model, now.recipient, msg(now.hasKey ? "assistantKeyStored" : "assistantKeyNone"))
          : msg("assistantStateNone");
        return { ...config, controlAttrs: { ...config.controlAttrs, label: msg("assistantTitle"), description: `${msg("assistantIntro")} ${says}` } };
      },
    });
    const assistantField = (id, field, control, words) => {
      aiSetting({
        id,
        get: () => assistantForm()[field],
        set(value) {
          assistantDraft(field, value);
        },
        disabled: () => aiBench.state.busy,
        getControlConfig: config => ({ ...config, ...words(config) }),
      });
      return { id, control };
    };
    const assistantFields = [
      assistantField("nulavio-assistant-kind", "kind", "moz-select", config => ({
        controlAttrs: { ...config.controlAttrs, label: msg("assistantKindLabel") },
        options: [choice("openai", msg("assistantKindOpenai")), choice("anthropic", msg("assistantKindAnthropic"))],
      })),
      assistantField("nulavio-assistant-model", "model", "moz-input-text", config => ({
        controlAttrs: { ...config.controlAttrs, label: msg("assistantModelLabel") },
      })),
      assistantField("nulavio-assistant-url", "baseUrl", "moz-input-text", config => ({
        controlAttrs: { ...config.controlAttrs, label: msg("assistantUrlLabel"), placeholder: "https://" },
      })),
      assistantField("nulavio-assistant-key", "key", "moz-input-password", config => ({
        controlAttrs: { ...config.controlAttrs, label: msg("assistantKeyLabel"), description: msg("assistantKeyNote") },
      })),
    ];
    aiSetting({
      id: "nulavio-assistant-save",
      disabled: () => aiBench.state.busy,
      async onUserClick(event) {
        event.preventDefault();
        const form = assistantForm();
        const details = { kind: form.kind, baseUrl: form.baseUrl.trim(), model: form.model.trim(), ...(form.key ? { key: form.key } : {}) };
        // The key goes to the system keyring through the Nulavio tools and is dropped from this page at once.
        if (await aiBench.act(() => shell.NulavioAI.assistantConfigure(details), msg("assistantSaved"))) {
          aiBench.show({ draft: null });
        } else {
          assistantDraft("key", "");
        }
      },
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("assistantSave"), type: "primary" } }),
    });
    // Whether this profile may send anything to the service: a switch, saved when it changes; each profile decides for itself.
    aiSetting({
      id: "nulavio-assistant-allowed",
      get: () => Boolean(assistantNow()?.profileAllowed),
      set(value) {
        aiBench.act(() => shell.NulavioAI.assistantAllow(Boolean(value)), msg("doneSaved"));
      },
      disabled: () => aiBench.state.busy,
      getControlConfig: config => ({
        ...config,
        controlAttrs: {
          ...config.controlAttrs,
          label: msg("assistantAllowLabel"),
          description: msg("assistantAllowHint", assistantNow()?.recipient ?? msg("assistantRecipientUnknown")),
        },
      }),
    });
    aiSetting({
      id: "nulavio-assistant-forget",
      visible: () => aiOpen() && Boolean(assistantNow()?.configured),
      disabled: () => aiBench.state.busy,
      async onUserClick(event) {
        event.preventDefault();
        if (await confirmDanger(msg("assistantForgetTitle"), msg("assistantForgetBody"), msg("assistantForget"))) {
          if (await aiBench.act(() => shell.NulavioAI.assistantForget(), msg("doneRemoved"))) {
            aiBench.show({ draft: null });
          }
        }
      },
      getControlConfig: config => ({ ...config, controlAttrs: { ...config.controlAttrs, label: msg("assistantForget") } }),
    });
    const aiItems = [
      failureNote("nulavio-ai-failed", ai),
      // A window an agent drives: said where the controls would be, and none of them is on the page.
      aiBench.bar("nulavio-ai-workspace", "info", () => msg("settingsAiInWorkspace", aiNow()?.workspace ?? ""), () => Boolean(aiNow()?.workspace)),
      aiBench.bar("nulavio-ai-stopped", "warning", () => msg("aiStoppedBanner"), () => aiOpen() && Boolean(aiNow().stopped)),
      aiBench.bar("nulavio-ai-error", "error", () => aiBench.state.error, () => Boolean(aiBench.state.error)),
      aiBench.bar("nulavio-ai-said", "success", () => aiBench.state.said, () => Boolean(aiBench.state.said)),
      { id: "nulavio-ai-stop", control: "moz-toggle" },
      { id: "nulavio-assistant-now", control: "moz-box-item" },
      ...assistantFields,
      { id: "nulavio-assistant-save", control: "moz-button" },
      { id: "nulavio-assistant-allowed", control: "moz-toggle" },
      { id: "nulavio-assistant-forget", control: "moz-button" },
    ];

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
          // Both as plain attributes: a Fluent message that sets only the description would take the label
          // away with it (Fluent clears the attributes a message does not provide), and the row would lose its name.
          return { ...config, controlAttrs: { ...attrs, description: command.shortcut || msg("keyNone") } };
        },
      });
      return { id, control: "moz-box-item" };
    });
    const keyBars = []; // what the reset said, under its button
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
      // #142: the reset says which keys go back to what before it is done, and what it did after.
      const keyBench = workbench({}, keys);
      setting({
        id: "nulavio-keys-reset",
        setup: keys.watch,
        visible: () => changedKeys().length > 0,
        disabled: () => keyBench.state.busy,
        async onUserClick(event) {
          event.preventDefault();
          const changed = changedKeys();
          const line = name => {
            const command = keys.state.value.get(name);
            const original = shortcuts.manifestCommands.get(name)?.shortcut || msg("keyNone");
            return msg("keysResetLine", command?.description || name, command?.shortcut || msg("keyNone"), original);
          };
          const body = `${msg("keysResetBody")}\n\n${changed.map(line).join("\n")}`;
          if (!changed.length || !(await confirmStep(msg("keysResetTitle"), body, msg("keysResetConfirm")))) {
            return;
          }
          let restored = 0;
          await keyBench.act(
            async () => {
              for (const name of changed) {
                const before = keys.state.value.get(name)?.shortcut ?? "";
                try {
                  await shortcuts.resetCommand(name);
                } catch (e) {
                  console.error(e);
                  continue; // nothing changed: not counted, and the list read again shows the key as it is
                }
                restored++;
                // The engine's reset announces nothing; the Shell's background listens to this to rename its button.
                shortcuts.onShortcutChanged?.({ name, newShortcut: shortcuts.manifestCommands.get(name)?.shortcut ?? "", oldShortcut: before });
              }
              if (!restored) {
                throw Object.assign(new Error("not restored"), { code: "unexpected" });
              }
            },
            () => msg("keysResetDone", String(restored))
          );
        },
      });
      keyBars.push(
        keyBench.bar("nulavio-keys-said", "success", () => keyBench.state.said, () => Boolean(keyBench.state.said)),
        keyBench.bar("nulavio-keys-error", "error", () => keyBench.state.error, () => Boolean(keyBench.state.error))
      );
    }

    for (const id of ["nulavio-layout-moved", "nulavio-profiles-box", "nulavio-protections-box"]) {
      setting({ id });
    }

    groups({
      nulavioLayout: {
        l10nId: "nulavio-layout-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-layout-failed", layout),
          ...layoutNotes,
          {
            id: "nulavio-layout",
            control: "moz-visual-picker",
            controlAttrs: { "data-option": "layout" }, // shared/options.json
            options: ["lateral", "top", "focus"].map(value => ({
              value,
              l10nId: `nulavio-layout-${value}`,
              controlAttrs: { id: `nulavio-layout-${value}`, class: "setting-chooser-item", imagesrc: `${IMAGES}layout-${value}.svg` },
            })),
          },
          { id: "nulavio-layout-keep", control: "moz-button" },
          { id: "nulavio-immersive", l10nId: "nulavio-immersive", control: "moz-toggle", controlAttrs: { "data-option": "immersive" } },
        ],
      },
      nulavioLook: {
        l10nId: "nulavio-look-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-look-failed", look),
          { id: "nulavio-look-locked", control: "moz-message-bar", l10nId: "nulavio-look-locked", controlAttrs: { type: "info" } },
          {
            id: "nulavio-accent",
            control: "moz-radio-group",
            l10nId: "nulavio-accent",
            controlAttrs: { "data-option": "accent" }, // shared/options.json
            options: [
              { value: "mint", l10nId: "nulavio-accent-mint" },
              { value: "blue", l10nId: "nulavio-accent-blue" },
            ],
          },
          { id: "nulavio-more-contrast", l10nId: "nulavio-more-contrast", control: "moz-toggle", controlAttrs: { "data-option": "moreContrast" } },
          { id: "nulavio-newtab-ambience", l10nId: "nulavio-newtab-ambience", control: "moz-toggle", controlAttrs: { "data-option": "newtabAmbience" } },
          {
            id: "nulavio-reduce-transparency",
            l10nId: "nulavio-reduce-transparency",
            control: "moz-toggle",
            controlAttrs: { "data-option": "reduceTransparency" },
          },
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
          ...profileBars,
          { id: "nulavio-profile-list", control: "moz-box-group" },
          {
            id: "nulavio-profiles-box",
            control: "moz-box-group",
            items: profileDoors,
          },
        ],
      },
      nulavioRouting: {
        l10nId: "nulavio-routing-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-routing-failed", routes),
          ...routingBars.slice(0, 1),
          ...routingBars.slice(2),
          { id: "nulavio-routing-enabled", control: "moz-toggle" },
          { id: "nulavio-routing-in-page", control: "moz-toggle" },
          { id: "nulavio-routing-fallback", control: "moz-select", controlAttrs: { "data-option": "routingFallback" } }, // shared/options.json
          routingBars[1],
          { id: "nulavio-routing-rules", control: "moz-box-group" },
        ],
      },
      nulavioPasswordManager: {
        l10nId: "nulavio-passwords-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-passwords-failed", passwords),
          { id: "nulavio-passwords-now", control: "moz-box-item" },
          ...passwordBars,
          { id: "nulavio-passwords-providers", control: "moz-box-group" },
          { id: "nulavio-passwords-logins", control: "moz-box-item" },
        ],
      },
      nulavioConfirmedSites: {
        l10nId: "nulavio-confirmed-group",
        headingLevel: 2,
        items: [failureNote("nulavio-confirmed-failed", confirmed), ...confirmedBars, { id: "nulavio-confirmed-sites", control: "moz-box-group" }],
      },
      nulavioProtections: {
        l10nId: "nulavio-protections-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-guard-failed", guard),
          failureNote("nulavio-filter-failed", filter),
          {
            id: "nulavio-protections-box",
            control: "moz-box-group",
            items: [
              { id: "nulavio-filter-lists", l10nId: "nulavio-filter-lists", control: "moz-box-button" },
              { id: "nulavio-guard-review", l10nId: "nulavio-guard-review", control: "moz-box-button" },
            ],
          },
        ],
      },
      nulavioExceptions: {
        l10nId: "nulavio-exceptions-group",
        headingLevel: 2,
        items: [
          failureNote("nulavio-exceptions-failed", exceptions),
          ...exceptionBars,
          { id: "nulavio-exceptions", control: "moz-box-group" },
          { id: "nulavio-filter-trusted", control: "moz-box-button" },
        ],
      },
      nulavioSearch: {
        l10nId: "nulavio-search-group",
        headingLevel: 2,
        items: [failureNote("nulavio-search-failed", search), { id: "nulavio-suggest-engines", control: "moz-box-group" }],
      },
      nulavioSearchAdd: {
        l10nId: "nulavio-search-add-group",
        headingLevel: 2,
        items: [...searchBars, { id: "nulavio-search-providers", control: "moz-box-group" }, ...searchForms],
      },
      nulavioAssistantEntry: {
        l10nId: "nulavio-assistant-group",
        headingLevel: 2,
        items: [...aiItems, detailRow("nulavio-open-assistant", "ai", { setup: aiSetup, visible: aiOpen })],
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
            { id: "nulavio-keys", control: "moz-box-group", items: keyRows, controlAttrs: { "data-option": "shortcuts" } }, // shared/options.json
            { id: "nulavio-keys-change", l10nId: "nulavio-keys-change", control: "moz-box-button" },
            { id: "nulavio-keys-reset", l10nId: "nulavio-keys-reset", control: "moz-button" },
            ...keyBars,
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
      privacy: config => ({ ...config, groupIds: after(config.groupIds, "etpStatus", "nulavioProtections", "nulavioExceptions") }),
      // "Sobre": how many managed policies are in effect and whose they are.
      about: config => ({ ...config, groupIds: [...config.groupIds, "nulavioPolicies"] }),
      passwordsAutofill: config => ({ ...config, groupIds: ["nulavioPasswordManager", ...config.groupIds, "nulavioConfirmedSites"] }),
      // Next to the engine's own groups on the same subject: who receives what is typed after its suggestions
      // group, and the engines Nulavio adds after its list of engines.
      search: config => ({
        ...config,
        groupIds: after(after(config.groupIds, "searchSuggestions", "nulavioSearch"), "searchShortcuts", "nulavioSearchAdd"),
      }),
      tabsBrowsing: config => ({
        ...config,
        groupIds: after(
          config.groupIds.map(id => (id === "browserLayout" ? "nulavioLayoutMoved" : id)),
          "keyboardShortcuts",
          ...(keyRows.length ? ["nulavioShortcuts"] : [])
        ),
      }),
    };
    // -- "Seu navegador está sendo gerenciado pela sua organização" (ADR 0008) ----------------------
    // Nulavio ships three policies of its own, so the engine's line was on every pane for everyone, and it
    // would also be the only sign of a policy somebody else added. It is dropped only while the policies in
    // effect were read and are exactly the build's own; "Sobre" then says how many those are. Anything else
    // (another policy, a read that failed, a state not read yet) leaves the engine's line as the engine shows it.
    const policies = source(() => shell.NulavioGuard.policiesOrigin());
    const managedNotice = document.getElementById("policies-container-content");
    if (managedNotice) {
      let shownByEngine = !managedNotice.hidden;
      let ours = false; // the hidden attribute as this file last set it
      const settle = () => {
        const own = policies.state.ready && policies.state.value.origin === "own";
        ours = true;
        managedNotice.hidden = own || !shownByEngine;
        ours = false;
        root.toggleAttribute("nulavio-own-policies", own);
      };
      // The engine un-hides its line when the page starts, after this file ran: that is the engine's word.
      const watcher = new MutationObserver(() => {
        if (!ours && !managedNotice.hidden) {
          shownByEngine = true;
          settle();
        }
      });
      watcher.observe(managedNotice, { attributes: true, attributeFilter: ["hidden"] });
      const stop = policies.listen(settle);
      added.cleanups.push(() => {
        stop();
        watcher.disconnect();
        managedNotice.hidden = !shownByEngine;
        root.removeAttribute("nulavio-own-policies");
      });
    }
    setting({
      id: "nulavio-policies",
      setup(emitChange, stops) {
        stops.push(policies.listen(emitChange));
        policies.refresh();
      },
      visible: () => policies.state.ready && policies.state.value.origin !== "none",
      onUserClick(event) {
        event.preventDefault();
        top().openTrustedLinkIn("about:policies", "tab");
      },
      getControlConfig(config) {
        const now = policies.state.value;
        if (!now) {
          return config;
        }
        return { ...config, l10nId: now.origin === "own" ? "nulavio-policies-own" : "nulavio-policies-other", l10nArgs: { count: now.count } };
      },
    });
    groups({
      nulavioPolicies: {
        l10nId: "nulavio-policies-group",
        headingLevel: 2,
        items: [failureNote("nulavio-policies-failed", policies), { id: "nulavio-policies", l10nId: "nulavio-policies-own", control: "moz-box-button" }],
      },
    });

    // An engine group is registered when its module loads: with the page for some, when the pane is first
    // opened for others. One of them has a row that only made
    // sense with the engine's own layout picker: "Personalizar layout do navegador", in Aparência, led to
    // the pane whose picker now points back to Aparência. That row goes; the group keeps its other rows.
    const groupEdits = {
      // The engine's one-line summary of DNS gives way to Nulavio's choices in plain words; its box keeps the
      // button to the engine's own advanced screen, which stays as it is.
      dnsOverHttps(config) {
        const items = config.items;
        const box = items?.find(item => item.id === "dohBox");
        const rows = box?.items;
        if (!Array.isArray(rows) || !rows.some(row => row.id === "dohAdvancedButton")) {
          throw new Error("the engine's DNS group has another shape");
        }
        const { l10nId } = config;
        box.items = rows.filter(row => row.id !== "dohModeBoxItem");
        config.items = [...dnsItems, ...items];
        config.l10nId = "nulavio-dns-group"; // what it is for, before what it is called
        undoOnly.push(() => {
          box.items = rows;
          config.items = items;
          config.l10nId = l10nId;
        });
      },
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
      "nulavioRouting",
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
