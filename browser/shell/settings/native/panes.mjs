/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Runs inside about:preferences (system principal), imported by NulavioSettings before the
   page builds its panes (ADR 0008). It only uses what the engine's own panes use: Preferences
   settings, SettingGroupManager groups and SettingPaneManager panes, drawn by the engine's
   widgets. Words come from l10n/<locale>/nulavio/settings.ftl. */

(() => {
  const here = { global: "current" };
  const { SettingGroupManager } = ChromeUtils.importESModule("chrome://browser/content/preferences/config/SettingGroupManager.mjs", here);
  const { SettingPaneManager } = ChromeUtils.importESModule("chrome://browser/content/preferences/config/SettingPaneManager.mjs", here);
  const { Preferences } = ChromeUtils.importESModule("chrome://global/content/preferences/Preferences.mjs", here);
  // The Shell's own modules, from the shared system global (fixed addresses; loaded when first used).
  const shell = {
    get NulavioLayout() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout;
    },
    get NulavioPersonalise() {
      return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise;
    },
  };
  const top = () => window.browsingContext.topChromeWindow;
  const IMAGES = "resource://builtin-addons/nulavio-shell/settings/native/";

  MozXULElement.insertFTLIfNeeded("nulavio/settings.ftl");

  // -- layout: Lateral, Abas no topo, Foco (NulavioLayout owns the change) -----------------------
  const layout = { preset: "lateral", locked: false, available: true };
  let layoutChanged = () => {};
  const readLayout = () =>
    shell.NulavioLayout.state(top()).then(state => {
      Object.assign(layout, state);
      layoutChanged();
    }, console.error);

  Preferences.addSetting({
    id: "nulavio-layout",
    setup(emitChange) {
      layoutChanged = emitChange;
      readLayout();
      let unsubscribe = () => {};
      try {
        unsubscribe = shell.NulavioLayout.subscribe(top(), readLayout);
      } catch (e) {
        console.error(e);
      }
      return () => unsubscribe();
    },
    get: () => (layout.preset === "custom" ? "" : layout.preset),
    set(value) {
      shell.NulavioLayout.apply(top(), value).then(readLayout, readLayout);
    },
    disabled: () => layout.locked || !layout.available,
  });

  // -- Immersive (ADR 0009): one switch on top of the layout; NulavioLayout is the only writer ----
  const PREF_IMMERSIVE = "nulavio.layout.immersive";
  const immersive = { on: false, locked: false };
  let immersiveChanged = () => {};
  const readImmersive = () => {
    Object.assign(immersive, shell.NulavioLayout.immersive());
    immersiveChanged();
  };
  Preferences.addSetting({
    id: "nulavio-immersive",
    setup(emitChange) {
      immersiveChanged = emitChange;
      readImmersive();
      Services.prefs.addObserver(PREF_IMMERSIVE, readImmersive); // the key (Ctrl+Alt+I) or the other page changed it
      return () => Services.prefs.removeObserver(PREF_IMMERSIVE, readImmersive);
    },
    get: () => immersive.on,
    set(value) {
      try {
        shell.NulavioLayout.setImmersive(Boolean(value));
      } catch (e) {
        console.error(e); // locked by an administrator: the switch shows what is true
      }
      readImmersive();
    },
    disabled: () => immersive.locked || layout.locked || !layout.available,
  });

  // -- look: accent, more contrast, new-tab ambience (NulavioPersonalise owns the prefs) ----------
  const look = { accent: "mint", moreContrast: false, newtabAmbience: false, locked: {} };
  const lookListeners = new Set();
  const readLook = () =>
    shell.NulavioPersonalise.state().then(state => {
      Object.assign(look, state);
      lookListeners.forEach(emit => emit());
    }, console.error);
  const lookSetting = (id, option, toValue = v => v, fromValue = v => v) =>
    Preferences.addSetting({
      id,
      setup(emitChange) {
        lookListeners.add(emitChange);
        return () => lookListeners.delete(emitChange);
      },
      get: () => fromValue(look[option]),
      set(value) {
        shell.NulavioPersonalise.set(option, toValue(value)).then(readLook, readLook);
      },
      disabled: () => Boolean(look.locked?.[option]),
    });
  lookSetting("nulavio-accent", "accent");
  lookSetting("nulavio-more-contrast", "moreContrast", Boolean, Boolean);
  lookSetting("nulavio-newtab-ambience", "newtabAmbience", Boolean, Boolean);
  readLook();
  const unsubscribeLook = shell.NulavioPersonalise.subscribe(readLook);
  window.addEventListener("unload", () => unsubscribeLook?.(), { once: true });

  Preferences.addSetting({
    id: "nulavio-open-profiles",
    onUserClick(event) {
      event.preventDefault();
      const policy = WebExtensionPolicy.getByID("shell@nulavio.net");
      top().openTrustedLinkIn(policy.getURL("settings/settings.html#profiles"), "tab");
    },
  });

  SettingGroupManager.registerGroups({
    nulavioLayout: {
      l10nId: "nulavio-layout-group",
      headingLevel: 2,
      items: [
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
      ],
    },
    nulavioProfilesEntry: {
      l10nId: "nulavio-profiles-group",
      headingLevel: 2,
      items: [{ id: "nulavio-open-profiles", l10nId: "nulavio-open-profiles", control: "moz-box-link" }],
    },
  });

  // -- one page, ordered by what the person is doing ----------------------------------------------
  // Appearance: how the window is arranged comes first, then the engine's theme and density,
  // then Nulavio's colours. One pane, whoever wrote the option.
  // The page registers its own panes right after this script (its DOMContentLoaded listener comes
  // second), so the engine's pane is edited as it is registered: the one seam into the page's code.
  const edits = {
    appearance: config => ({
      ...config,
      groupIds: ["nulavioLayout", ...config.groupIds.filter(id => id !== "relatedSettings"), "nulavioLook", "relatedSettings"],
    }),
  };
  const registerPane = SettingPaneManager.registerPane;
  SettingPaneManager.registerPane = function (id, config) {
    return registerPane.call(this, id, edits[id] ? edits[id](config) : config);
  };

  SettingPaneManager.registerPane("nulavioProfiles", {
    l10nId: "nulavio-pane-profiles",
    iconSrc: "chrome://browser/skin/preferences/category-sync.svg",
    groupIds: ["nulavioProfilesEntry"],
  });
  const nav = document.getElementById("categories");
  const button = document.createElement("moz-page-nav-button");
  button.id = "category-nulavio-profiles";
  button.setAttribute("view", "paneNulavioProfiles");
  button.setAttribute("iconsrc", "chrome://browser/skin/preferences/category-sync.svg");
  button.setAttribute("data-l10n-id", "nulavio-pane-profiles-nav");
  // Journey order: look first, then who you are, then the engine's panes as they were.
  const appearanceButton = document.getElementById("category-appearance");
  nav.insertBefore(appearanceButton, nav.firstElementChild);
  appearanceButton.after(button);

  document.documentElement.setAttribute("nulavio-settings", "1");
})();
