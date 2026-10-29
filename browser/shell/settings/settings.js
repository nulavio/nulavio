/* Nulavio settings: search engines and profiles. Every change goes through
   the engine's own services (Search Service, profile service) via the
   Shell's privileged APIs; this page keeps no state of its own. */

import { localize, t } from "../lib/i18n.js";
import { TEMPLATE_NAMES, freeName } from "../lib/names.js";
import { announce, chip, confirmDialog, errorText, h, rerender, temporaryStorageText } from "../lib/ui.js";
import { setUpAI } from "./ai.js";
import { setUpLayout } from "./layout.js";

const search = browser.nulavioSearch;
const profiles = browser.nulavioProfiles;

function debounce(fn, ms = 60) {
  let timer = null;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, ms);
  };
}

/** Run an action; show errors next to the form (or in the status line). */
async function run(action, { form = null, done = null } = {}) {
  const error = form?.querySelector(".form-error");
  if (error) {
    error.textContent = "";
  }
  try {
    const result = await action();
    if (done) {
      announce(done);
    }
    return result;
  } catch (e) {
    if (error) {
      error.textContent = errorText(e);
    } else {
      announce(errorText(e), "error");
    }
    return undefined;
  }
}

// -- search ---------------------------------------------------------------

function engineOptions(select, engines, selected) {
  select.replaceChildren(...engines.map(e => h("option", { value: e.id, selected: e.id === selected, text: e.name })));
}

function engineRow(engine) {
  const badges = [
    engine.isDefault ? h("span", { class: "badge", text: t("engineDefaultBadge") }) : null,
    engine.isDefaultPrivate ? h("span", { class: "badge badge--quiet", text: t("enginePrivateBadge") }) : null,
  ];
  const meta = [engine.host, ...engine.aliases].filter(Boolean).join(" · ");

  const aliasForm = h(
    "form",
    { class: "inline-form", novalidate: true },
    h(
      "label",
      { class: "field field--inline" },
      h("span", { class: "visually-hidden", text: t("engineAliasLabel", [engine.name]) }),
      h("input", {
        class: "input input--short",
        name: "alias",
        value: engine.alias,
        autocomplete: "off",
        spellcheck: "false",
        maxlength: "21",
        placeholder: "@alias",
        "data-focus-key": `alias-${engine.id}`,
      })
    ),
    h("button", { class: "button button--quiet", type: "submit", text: t("engineAliasSave"), "data-focus-key": `alias-save-${engine.id}` }),
    h("p", { class: "form-error", role: "alert" })
  );
  aliasForm.addEventListener("submit", event => {
    event.preventDefault();
    run(() => search.setAlias(engine.id, aliasForm.elements.alias.value), { form: aliasForm, done: t("doneSaved") });
  });

  let suggest;
  if (engine.canSuggest) {
    const hintId = `suggest-hint-${engine.id}`;
    const box = h("input", {
      type: "checkbox",
      role: "switch",
      checked: engine.suggestOptIn,
      "aria-describedby": hintId,
      "data-focus-key": `suggest-${engine.id}`,
    });
    box.addEventListener("change", () => run(() => search.setSuggestOptIn(engine.id, box.checked), { done: t("doneSaved") }));
    suggest = h(
      "div",
      { class: "suggest" },
      h("label", { class: "check check--switch" }, box, h("span", { text: t("engineSuggestLabel") })),
      h("p", {
        class: `hint${engine.suggestOptIn ? " hint--on" : ""}`,
        id: hintId,
        text: engine.suggestOptIn ? t("engineSuggestOn", [engine.suggestHost]) : t("engineSuggestOff"),
      })
    );
  } else {
    suggest = h("p", { class: "hint", text: t("engineSuggestNone") });
  }

  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    disabled: !engine.removable,
    text: t("engineRemove"),
    "aria-label": `${t("engineRemove")} ${engine.name}`,
    "data-focus-key": `remove-${engine.id}`,
  });
  remove.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: t("engineRemoveTitle", [engine.name]),
      body: t("engineRemoveBody"),
      confirm: t("engineRemove"),
      danger: true,
    });
    if (ok) {
      await run(() => search.remove(engine.id), { done: t("doneRemoved") });
    }
  });

  return h(
    "li",
    { class: "row row--engine", dataset: { engineId: engine.id } },
    h("span", { class: "chip chip--md chip--neutral", "aria-hidden": "true", text: engine.name.slice(0, 1).toLocaleUpperCase() }),
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title" }, h("span", { text: engine.name }), ...badges),
      h("p", { class: "row__meta", text: meta }),
      suggest,
      h(
        "details",
        { class: "more", "data-open-key": `alias-${engine.id}` },
        h("summary", { text: t("engineAliasEdit") }),
        aliasForm
      )
    ),
    h("div", { class: "row__end" }, remove)
  );
}

async function renderSearch() {
  const state = await run(() => search.state());
  if (!state) {
    return;
  }
  const normal = state.engines.find(e => e.isDefault)?.id;
  const privateDefault = state.engines.find(e => e.isDefaultPrivate)?.id;
  engineOptions(document.getElementById("default-engine"), state.engines, normal);
  engineOptions(document.getElementById("default-private-engine"), state.engines, privateDefault);
  document.getElementById("private-default-field").hidden = !state.separatePrivateDefault;

  const anyOptIn = state.engines.some(e => e.suggestOptIn);
  rerender(document.getElementById("engines"), () => state.engines.map(engineRow));

  const privateBox = document.getElementById("suggest-private");
  privateBox.checked = state.suggestionsPrivate;
  privateBox.disabled = !anyOptIn;

  const present = new Set(state.engines.map(e => e.provider).filter(Boolean));
  const missing = state.providers.filter(p => !present.has(p.key));
  rerender(document.getElementById("providers"), () =>
    missing.length
      ? missing.map(p => {
          const button = h("button", {
            class: "button button--secondary",
            type: "button",
            text: t("addProviderButton", [p.name]),
            "data-focus-key": `provider-${p.key}`,
          });
          button.addEventListener("click", () => run(() => search.addProvider(p.key), { done: t("doneAdded") }));
          return button;
        })
      : h("p", { class: "hint", text: t("addProvidersNone") })
  );
}

function setUpSearch() {
  document.getElementById("search").hidden = false;
  document.getElementById("default-engine").addEventListener("change", event =>
    run(() => search.setDefault(event.target.value), { done: t("doneSaved") })
  );
  document.getElementById("default-private-engine").addEventListener("change", event =>
    run(() => search.setDefault(event.target.value, { private: true }), { done: t("doneSaved") })
  );
  document.getElementById("suggest-private").addEventListener("change", event =>
    run(() => search.setSuggestPrivate(event.target.checked), { done: t("doneSaved") })
  );

  const submit = (id, action) => {
    const form = document.getElementById(id);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      const added = await run(() => action(values), { form, done: t("doneAdded") });
      if (added !== undefined) {
        form.reset();
      }
    });
  };
  submit("add-searxng", ({ url }) => search.addSearxng({ url }));
  submit("add-custom", ({ name, url, alias, suggestUrl }) =>
    search.addCustom({ name, url, ...(alias ? { alias } : {}), ...(suggestUrl ? { suggestUrl } : {}) })
  );
  submit("add-opensearch", ({ url }) => search.addOpenSearch({ url }));

  search.onChanged.addListener(debounce(renderSearch));
  return renderSearch();
}

// -- profiles -------------------------------------------------------------

let profileOptions = null;

function colorPicker(profile) {
  return h(
    "fieldset",
    { class: "swatches" },
    h("legend", { class: "field__label", text: t("profilesColorLabel") }),
    profileOptions.colors.map(color =>
      h(
        "label",
        { class: "swatch", title: t(`color_${color}`) },
        h("input", {
          type: "radio",
          name: "color",
          value: color,
          checked: color === profile.color,
          "data-focus-key": `color-${profile.id}-${color}`,
        }),
        h("span", { class: "swatch__fill", style: `--chip: var(--nv-color-identity-${color})`, "aria-hidden": "true" }),
        h("span", { class: "visually-hidden", text: t(`color_${color}`) })
      )
    )
  );
}

function avatarSelect(profile) {
  const avatars = profileOptions.avatars.includes(profile.avatar) ? profileOptions.avatars : [profile.avatar, ...profileOptions.avatars];
  return h(
    "label",
    { class: "field" },
    h("span", { class: "field__label", text: t("profilesIconLabel") }),
    h(
      "select",
      { class: "select", name: "avatar", "data-focus-key": `avatar-${profile.id}` },
      avatars.map(a =>
        h("option", { value: a, selected: a === profile.avatar, text: browser.i18n.getMessage(`avatar_${a.replaceAll("-", "_")}`) || a })
      )
    )
  );
}

function profileRow(profile) {
  const form = h(
    "form",
    { class: "stack stack--tight", novalidate: true },
    h(
      "div",
      { class: "field-row" },
      h(
        "label",
        { class: "field" },
        h("span", { class: "field__label", text: t("profilesNameLabel") }),
        h("input", {
          class: "input",
          name: "name",
          value: profile.name,
          maxlength: "60",
          autocomplete: "off",
          "data-focus-key": `name-${profile.id}`,
        })
      ),
      avatarSelect(profile)
    ),
    colorPicker(profile),
    profile.kind === "sensitive" ? h("p", { class: "hint", "data-kind": "sensitive", text: t("profilesSensitiveHint") }) : null,
    h("p", { class: "form-error", role: "alert" }),
    h("div", { class: "actions" }, h("button", { class: "button button--secondary", type: "submit", text: t("profilesSave"), "data-focus-key": `save-${profile.id}` }))
  );
  form.addEventListener("submit", event => {
    event.preventDefault();
    const { name, avatar, color } = Object.fromEntries(new FormData(form));
    run(() => profiles.update(profile.id, { name, avatar, color }), { form, done: t("doneSaved") });
  });

  const migration = profile.colorMigration === "mint-to-lima"
    ? h("div", { "data-color-migration": "mint-to-lima" }, h("p", { class: "row__note", text: t("profilesColorMigrated", [profile.name]) }))
    : null;
  if (migration) {
    const change = h("button", {
      class: "button button--quiet",
      type: "button",
      text: t("profilesChangeColor"),
      "aria-label": t("profilesChangeColorNamed", [profile.name]),
      "data-focus-key": `change-color-${profile.id}`,
    });
    change.addEventListener("click", () => {
      form.closest("details").open = true;
      form.querySelector('input[name="color"]:checked')?.focus();
    });
    migration.append(change);
  }

  const end = [];
  if (profile.isCurrent) {
    const del = h("button", { class: "button button--quiet", type: "button", text: t("profilesDeleteCurrent") });
    del.addEventListener("click", () => run(() => profiles.openCurrentPage("delete")));
    end.push(del);
  } else {
    // The accessible name keeps the visible words and the state (SPA-10, SB-17): "Abrir Pessoal",
    // or "Bancos, bloqueado, desbloquear…" next to the visible "Desbloquear…".
    const open = h("button", {
      class: "button button--secondary",
      type: "button",
      text: t("profilesOpen"),
      "aria-label": t(profile.locked ? "profilesUnlockNamed" : "profilesOpenNamed", [profile.name]),
      "data-focus-key": `open-${profile.id}`,
    });
    open.addEventListener("click", () =>
      profile.locked
        ? run(() => browser.nulavioVault.openUnlockPage(profile.id))
        : run(() => profiles.switchTo(profile.id), { done: t("profilesOpening", [profile.name]) })
    );
    if (profile.locked) {
      open.textContent = t("vaultUnlockButton");
    }
    const del = h("button", {
      class: "button button--quiet",
      type: "button",
      text: t("profilesDelete"),
      "aria-label": `${t("profilesDelete")} ${profile.name}`,
      "data-focus-key": `delete-${profile.id}`,
    });
    del.addEventListener("click", async () => {
      const ok = await confirmDialog({
        title: t("profilesDeleteTitle", [profile.name]),
        body: t("profilesDeleteBody"),
        confirm: t("profilesDeleteConfirm"),
        danger: true,
      });
      if (ok) {
        await run(() => profiles.remove(profile.id), { done: t("profilesDeleted") });
      }
    });
    end.push(open);
    if (profile.encrypted && !profile.locked) {
      const lock = h("button", { class: "button button--quiet", type: "button", text: t("vaultLockNow"), "data-focus-key": `lock-${profile.id}` });
      lock.addEventListener("click", () =>
        run(() => browser.nulavioVault.lock(profile.id).then(() => renderProfiles()), { done: t("vaultLockedNow", [profile.name]) })
      );
      end.push(lock);
    }
    end.push(del);
  }
  if (profile.encrypted) {
    const phones = h("button", { class: "button button--quiet", type: "button", text: t("vaultPhones"), "data-focus-key": `phones-${profile.id}` });
    phones.addEventListener("click", () => run(() => browser.nulavioVault.openPhonePage(profile.id)));
    end.push(phones);
  }

  return h(
    "li",
    { class: "row row--profile", dataset: { profileId: String(profile.id ?? "") } },
    chip(profile, "lg"),
    h(
      "div",
      { class: "row__main" },
      h(
        "p",
        { class: "row__title" },
        h("span", { text: profile.name }),
        profile.isCurrent ? h("span", { class: "badge", text: t("profilesCurrent") }) : null,
        profile.locked ? h("span", { class: "badge badge--quiet", text: t("profilesLocked") }) : null
      ),
      // When an open protected profile locks again (SB-14), next to "Bloquear agora".
      profile.encrypted && !profile.locked ? h("p", { class: "row__note", "data-relock": "", text: t("vaultRelocksWhenClosed") }) : null,
      migration,
      profile.id === null
        ? null
        : h(
            "details",
            { class: "more", "data-open-key": `profile-${profile.id}` },
            h("summary", { text: t("profilesEdit") }),
            form
          )
    ),
    h("div", { class: "row__end" }, end)
  );
}

async function renderProfiles() {
  const state = await run(() => profiles.list());
  if (!state) {
    return;
  }
  const unavailable = document.getElementById("profiles-unavailable");
  const usable = state.available;
  unavailable.hidden = usable;
  unavailable.textContent = usable
    ? ""
    : state.reason === "temporary"
      ? `${t("profilesTemporaryBar")} ${temporaryStorageText(state.temporary)}`
      : t(state.reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
  for (const id of ["profiles-card", "profiles-new"]) {
    document.getElementById(id).hidden = !usable;
  }
  if (!usable) {
    return;
  }
  rerender(document.getElementById("profile-list"), () => state.profiles.map(profileRow));
  rerender(document.getElementById("templates"), () =>
    profileOptions.templates.map(template => {
      const name = t(TEMPLATE_NAMES[template.id]);
      const button = h("button", { class: "button button--secondary button--with-chip", type: "button", "data-focus-key": `template-${template.id}` });
      button.append(chip({ name, avatar: template.avatar, color: template.color }, "sm"), h("span", { text: name }));
      button.addEventListener("click", () =>
        run(
          () =>
            profiles.create({
              templateId: template.id,
              name: freeName(name, state.profiles.map(p => p.name)),
            }),
          { done: t("profilesCreated") }
        )
      );
      return button;
    })
  );
}

async function setUpProfiles() {
  document.getElementById("profiles").hidden = false;
  profileOptions = await profiles.options();
  document.getElementById("open-manager").addEventListener("click", () => run(() => profiles.openManager()));
  document
    .getElementById("open-temporary")
    .addEventListener("click", () => run(() => profiles.openTemporary(), { done: t("profilesTemporaryOpening") }));
  const form = document.getElementById("create-profile");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const created = await run(() => profiles.create({ name: form.elements.name.value }), { form, done: t("profilesCreated") });
    if (created !== undefined) {
      form.reset();
    }
  });
  profiles.onChanged.addListener(debounce(renderProfiles));
  return renderProfiles();
}

// -- smart profile routing --------------------------------------------------

const routing = browser.nulavioRouting;
const ACTION_KEYS = { "open-in": "routingActionOpen", ask: "routingActionAsk", stay: "routingActionStay" };

function ruleRow(rule) {
  const scope = rule.match === "domain" ? t("routingScopeDomain", [rule.display]) : rule.display;
  const where =
    rule.action === "stay"
      ? t("routingActionStay")
      : rule.missing
        ? t("routingTargetMissing")
        : `${rule.profileName} · ${t(ACTION_KEYS[rule.action])}`;
  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("engineRemove"),
    "aria-label": `${t("engineRemove")} ${rule.display}`,
    "data-focus-key": `rule-remove-${rule.id}`,
  });
  remove.addEventListener("click", () => run(() => routing.removeRule(rule.id), { done: t("doneRemoved") }));
  const lead = rule.profileName
    ? chip({ name: rule.profileName, color: rule.profileColor, avatar: null }, "md")
    : h("span", { class: "chip chip--md chip--neutral", "aria-hidden": "true", text: "–" });
  return h(
    "li",
    { class: "row", dataset: { ruleId: rule.id } },
    lead,
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title", text: scope }),
      h("p", { class: `hint${rule.missing ? " form-error" : ""}`, text: where })
    ),
    h("div", { class: "row__end" }, remove)
  );
}

async function renderRouting() {
  const [state, people] = await Promise.all([run(() => routing.state()), run(() => profiles.list())]);
  if (!state || !people) {
    return;
  }
  const card = document.getElementById("routing");
  card.hidden = !state.available;
  if (!state.available) {
    return;
  }
  document.getElementById("routing-enabled").checked = state.enabled;
  const inPage = document.getElementById("routing-in-page");
  inPage.checked = state.inPage;
  inPage.disabled = !state.enabled;
  rerender(document.getElementById("rules"), () =>
    state.rules.length ? state.rules.map(ruleRow) : h("li", { class: "hint", text: t("routingNoRules") })
  );
  const select = document.getElementById("rule-profile");
  const chosen = select.value;
  select.replaceChildren(
    ...people.profiles
      .filter(p => p.id !== null)
      .map(p => h("option", { value: String(p.id), selected: String(p.id) === chosen, text: p.name }))
  );
}

function setUpRouting() {
  document.getElementById("routing-enabled").addEventListener("change", event =>
    run(() => routing.setEnabled(event.target.checked), { done: t("doneSaved") })
  );
  document.getElementById("routing-in-page").addEventListener("change", event =>
    run(() => routing.setInPage(event.target.checked), { done: t("doneSaved") })
  );
  const form = document.getElementById("add-rule");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const { site, match, action, profileId } = Object.fromEntries(new FormData(form));
    const rule = { site, match, action, ...(action === "stay" ? {} : { profileId: Number(profileId) }) };
    const added = await run(() => routing.addRule(rule), { form, done: t("doneAdded") });
    if (added !== undefined) {
      form.elements.site.value = "";
    }
  });
  routing.onChanged.addListener(debounce(renderRouting));
  profiles.onChanged.addListener(debounce(renderRouting));
  return renderRouting();
}

// -- integrations (Nulavio Connect) -----------------------------------------

const connect = browser.nulavioConnect;
const STATE_KEYS = {
  enabled: "connectStateEnabled",
  available: "connectStateAvailable",
  unavailable: "connectStateUnavailable",
  error: "connectStateError",
  unknown: "connectStateUnknown",
};

function integrationText(item) {
  const key = `connect_${item.id}_${item.reason}`.replaceAll("-", "_");
  const substitutions =
    {
      "secret-service": [item.params.provider ?? ""],
      "default-browser": [item.params.name || t("connectNoBrowser")],
      "xdg-portals": [t(`connectPicker_${item.params.picker ?? "automatic"}`)],
      "plasma-browser-integration": [item.params.dir ?? ""],
      "kde-connect": [item.params.devices ?? ""],
    }[item.id] ?? [];
  return browser.i18n.getMessage(key, substitutions) || t("connectCheckFailed");
}

function integrationActions(item) {
  const actions = [];
  if (item.id === "plasma-browser-integration" && item.reason === "ready" && /^https:\/\//.test(item.params.page ?? "")) {
    actions.push(h("a", { class: "button button--secondary", href: item.params.page, target: "_blank", rel: "noreferrer", text: t("connectInstallExtension") }));
  }
  if (item.id === "default-browser" && item.reason === "other") {
    const make = h("button", { class: "button button--secondary", type: "button", text: t("connectMakeDefault"), "data-focus-key": "make-default" });
    make.addEventListener("click", async () => {
      const ok = await confirmDialog({
        title: t("connectMakeDefaultTitle"),
        body: t("connectMakeDefaultBody"),
        confirm: t("connectMakeDefaultConfirm"),
      });
      if (ok && (await run(() => connect.setDefaultBrowser(), { done: t("connectDefaultSet") })) !== undefined) {
        renderIntegrations();
      }
    });
    actions.push(make);
  }
  if (item.id === "krunner" && (item.state === "available" || item.state === "enabled")) {
    const enable = item.state === "available";
    const button = h("button", {
      class: `button ${enable ? "button--secondary" : "button--quiet"}`,
      type: "button",
      text: t(enable ? "connectKrunnerEnable" : "connectKrunnerDisable"),
      "data-focus-key": "krunner",
    });
    button.addEventListener("click", async () => {
      if ((await run(() => connect.setKrunner(enable), { done: t(enable ? "connectKrunnerEnabled" : "connectKrunnerDisabled") })) !== undefined) {
        renderIntegrations();
      }
    });
    actions.push(button);
  }
  if (item.id === "default-browser" && item.state === "enabled" && item.params.previous) {
    const restore = h("button", {
      class: "button button--quiet",
      type: "button",
      text: t("connectRestore", [item.params.previousName || item.params.previous]),
      "data-focus-key": "restore-default",
    });
    restore.addEventListener("click", async () => {
      if ((await run(() => connect.restoreDefaultBrowser(), { done: t("connectRestored") })) !== undefined) {
        renderIntegrations();
      }
    });
    actions.push(restore);
  }
  return actions;
}

function integrationRow(item) {
  return h(
    "li",
    { class: "row", dataset: { integration: item.id, state: item.state } },
    h("span", { class: `state-mark state-mark--${item.state}`, "aria-hidden": "true" }),
    h(
      "div",
      { class: "row__main" },
      h(
        "p",
        { class: "row__title" },
        h("span", { text: t(`connectTitle_${item.id.replaceAll("-", "_")}`) }),
        h("span", { class: `badge badge--state badge--${item.state}`, text: t(STATE_KEYS[item.state] ?? "connectStateUnknown") })
      ),
      h("p", { class: "hint", text: integrationText(item) }),
      h(
        "details",
        { class: "more", "data-open-key": `evidence-${item.id}` },
        h("summary", { text: t("connectEvidence") }),
        h("ul", { class: "evidence" }, item.evidence.map(line => h("li", { class: "mono", text: line })))
      )
    ),
    h("div", { class: "row__end" }, integrationActions(item))
  );
}

async function renderIntegrations() {
  const list = document.getElementById("integration-list");
  list.setAttribute("aria-busy", "true");
  const items = await run(() => connect.discover());
  list.setAttribute("aria-busy", "false");
  if (items) {
    rerender(list, () => items.map(integrationRow));
    list.dataset.ready = "true";
  }
}

function setUpIntegrations() {
  document.getElementById("integrations").hidden = false;
  document.getElementById("connect-refresh").addEventListener("click", () => renderIntegrations());
  return renderIntegrations();
}

// -- passwords (flows B and H) ------------------------------------------------

const passwords = browser.nulavioPasswords;

function providerName(item) {
  return item.key === "builtin" ? t("passwordsBuiltin") : item.extension.name;
}

function providerStatus(item) {
  if (item.key === "builtin") {
    return t("passwordsBuiltinNote");
  }
  const ext = item.extension;
  const parts = [
    ext.enabled
      ? t("passwordsInstalled", [ext.version])
      : ext.installed
        ? t("passwordsInstalledOff")
        : t("passwordsNotInstalled", [ext.pinned]),
  ];
  if (item.native && !item.native.found) {
    parts.push(t(item.native.required ? "passwordsNativeMissing" : "passwordsNativeOptional"));
  }
  return parts.join(" ");
}

function providerRow(item, state) {
  const inUse = state.current === item.key;
  const end = [];
  if (inUse && item.key !== "builtin") {
    const off = h("button", { class: "button button--quiet", type: "button", text: t("passwordsDisableIntegration"), "data-focus-key": `pw-off-${item.key}` });
    off.addEventListener("click", async () => {
      const ok = await confirmDialog({ title: t("passwordsDisableTitle"), body: t("passwordsDisableBody", [providerName(item)]), confirm: t("passwordsDisableIntegration") });
      if (ok) {
        run(() => passwords.choose("builtin"), { done: t("passwordsChosen", [t("passwordsBuiltin")]) }).then(renderPasswords);
      }
    });
    end.push(off);
  } else if (!inUse) {
    const use = h("button", { class: "button button--secondary", type: "button", text: t("passwordsUse"), "data-focus-key": `pw-use-${item.key}` });
    use.addEventListener("click", async () => {
      if (item.extension && !item.extension.installed) {
        const ok = await confirmDialog({
          title: t("passwordsConfirmTitle", [providerName(item)]),
          body: t("passwordsConfirmBody", [providerName(item), item.extension.pinned]),
          confirm: t("passwordsConfirmButton"),
        });
        if (!ok) {
          return;
        }
        announce(t("passwordsInstalling", [providerName(item)]), "progress");
      }
      run(() => passwords.choose(item.key), { done: t("passwordsChosen", [providerName(item)]) }).then(renderPasswords);
    });
    end.push(use);
  }
  return h(
    "li",
    { class: "row row--plain", dataset: { provider: item.key, inUse: String(inUse) } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title" }, h("span", { text: providerName(item) }), inUse ? h("span", { class: "badge", text: t("passwordsInUse") }) : null),
      h("p", { class: "hint", text: providerStatus(item) })
    ),
    h("div", { class: "row__end" }, ...end)
  );
}

async function renderPasswords() {
  const state = await run(() => passwords.state());
  if (!state) {
    return;
  }
  const list = document.getElementById("provider-list");
  rerender(list, () => state.providers.map(item => providerRow(item, state)));
  list.setAttribute("aria-busy", "false");
  list.dataset.current = state.current;
  document.getElementById("engine-logins").textContent = t("passwordsEngineLogins", [String(state.engineLogins)]);
}

/** Look-alike sites the person chose to continue on (flow D): each can be removed, and the warning returns. */
function confirmedRow(pair) {
  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("passwordsConfirmedRemove"),
    "aria-label": t("passwordsConfirmedRemoveNamed", [pair.site]),
    "data-focus-key": `confirmed-${pair.site} ${pair.similar}`,
  });
  remove.addEventListener("click", async () => {
    const left = await run(() => passwords.removeConfirmed(pair.site, pair.similar), {
      done: t("passwordsConfirmedRemoved", [pair.site]),
    });
    if (left) {
      renderConfirmed(left);
      // The row is gone: keep the keyboard here (the next row's button, or the card's heading).
      const next = document.querySelector("#confirmed-list button");
      if (next) {
        next.focus();
      } else {
        const heading = document.getElementById("confirmed-heading");
        heading.tabIndex = -1;
        heading.focus();
      }
    }
  });
  return h(
    "li",
    { class: "row row--plain", dataset: { site: pair.site, similar: pair.similar } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title", text: pair.site }),
      h("p", { class: "row__note", text: t("passwordsConfirmedLooksLike", [pair.similar]) })
    ),
    h("div", { class: "row__end" }, remove)
  );
}

function renderConfirmed(pairs) {
  const list = document.getElementById("confirmed-list");
  rerender(list, () => pairs.map(confirmedRow));
  list.setAttribute("aria-busy", "false");
  list.hidden = !pairs.length;
  document.getElementById("confirmed-empty").hidden = Boolean(pairs.length);
}

async function setUpPasswords() {
  document.getElementById("passwords").hidden = false;
  await renderPasswords();
  const pairs = await run(() => passwords.listConfirmed());
  if (pairs) {
    renderConfirmed(pairs);
  }
}

// -- site exceptions --------------------------------------------------------

const privacy = browser.nulavioPrivacy;
const EXCEPTION_LABELS = {
  trackingprotection: { allow: "exceptionTracking" },
  "trackingprotection-pb": { allow: "exceptionTrackingPrivate" },
  "https-only-load-insecure": { allow: "exceptionHttpsOnly", session: "exceptionHttpsOnlySession" },
  cookie: { allow: "exceptionCookieAllow", deny: "exceptionCookieDeny", session: "exceptionCookieSession" },
  install: { allow: "exceptionInstall" },
  popup: { allow: "exceptionPopup" },
};

function exceptionRow(entry) {
  const key = EXCEPTION_LABELS[entry.type]?.[entry.capability] ?? EXCEPTION_LABELS[entry.type]?.allow;
  const what = key ? t(key) : `${entry.type} (${entry.capability})`;
  const notes = [
    entry.builtIn ? t("exceptionBuiltIn") : null,
    entry.session ? t("exceptionUntilClose") : null,
    entry.private ? t("exceptionPrivate") : null,
  ].filter(Boolean);
  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("engineRemove"),
    "aria-label": `${t("engineRemove")}: ${entry.site} — ${what}`,
    "data-focus-key": `exception-${entry.type}-${entry.origin}`,
  });
  remove.addEventListener("click", () => run(() => privacy.remove(entry.type, entry.origin), { done: t("doneRemoved") }));
  return h(
    "li",
    { class: "row row--plain", dataset: { type: entry.type, origin: entry.origin } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title mono", text: entry.site }),
      h("p", { class: "hint", text: [what, ...notes].join(" · ") })
    ),
    h("div", { class: "row__end" }, remove)
  );
}

async function renderExceptions() {
  const list = document.getElementById("exception-list");
  const [entries, filter] = await Promise.all([run(() => privacy.exceptions()), run(() => privacy.filter())]);
  if (entries) {
    rerender(list, () => entries.map(exceptionRow));
    list.setAttribute("aria-busy", "false");
    document.getElementById("exceptions-empty").hidden = entries.length > 0;
  }
  if (filter) {
    document.getElementById("filter-text").textContent = t(
      filter.active ? "exceptionsFilterOn" : filter.installed ? "exceptionsFilterOff" : "exceptionsFilterMissing"
    );
    document.getElementById("open-filter-list").hidden = !filter.active;
  }
}

function setUpExceptions() {
  document.getElementById("exceptions").hidden = false;
  document.getElementById("open-filter-list").addEventListener("click", () => run(() => privacy.openFilterList()));
  privacy.onChanged.addListener(debounce(renderExceptions));
  return renderExceptions();
}

// -- DNS ----------------------------------------------------------------------

function dnsText(state) {
  if (state.choice === "system") {
    return t("dnsNowSystem");
  }
  if (state.choice === "default") {
    return t("dnsNowDefault");
  }
  const name = state.provider === "custom" ? state.uri : t(`dns${state.provider[0].toUpperCase()}${state.provider.slice(1)}`);
  return t(state.choice === "strict" ? "dnsNowStrict" : "dnsNowFallback", [name]);
}

function syncDnsForm(form) {
  const choice = form.elements.choice.value;
  document.getElementById("dns-provider-row").hidden = choice === "system" || !choice;
  document.getElementById("dns-uri-field").hidden = form.elements.provider.value !== "custom";
}

async function renderDns() {
  const state = await run(() => privacy.dns());
  if (!state) {
    return;
  }
  const form = document.getElementById("dns-form");
  document.getElementById("dns-current").textContent = dnsText(state);
  form.dataset.choice = state.choice;
  for (const radio of form.elements.choice) {
    radio.checked = radio.value === state.choice;
  }
  form.elements.provider.value = state.provider ?? "cloudflare";
  form.elements.uri.value = state.provider === "custom" ? state.uri : "";
  syncDnsForm(form);
}

function setUpDns() {
  document.getElementById("dns").hidden = false;
  const form = document.getElementById("dns-form");
  form.addEventListener("change", () => syncDnsForm(form));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const choice = form.elements.choice.value;
    if (!choice) {
      return;
    }
    const details = { choice, provider: form.elements.provider.value, uri: form.elements.uri.value };
    if (await run(() => privacy.setDns(details), { form, done: t("dnsSaved") })) {
      await renderDns();
    }
  });
  return renderDns();
}

// -- page -----------------------------------------------------------------

localize();
const ready = [];
if (browser.nulavioLayout) {
  ready.push(setUpLayout());
}
if (search && profiles && routing && connect) {
  ready.push(setUpSearch(), setUpProfiles(), setUpRouting(), setUpIntegrations());
  if (browser.nulavioAI) {
    ready.push(setUpAI());
  }
  if (privacy) {
    ready.push(setUpExceptions(), setUpDns());
  }
  if (passwords) {
    ready.push(setUpPasswords());
  }
} else {
  document.getElementById("needs-build").hidden = false;
}
Promise.allSettled(ready).then(() => {
  document.documentElement.dataset.ready = "true";
  document.getElementById(location.hash.slice(1))?.scrollIntoView();
});
