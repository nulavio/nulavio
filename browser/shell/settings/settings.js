/* Nulavio settings: search engines and profiles. Every change goes through
   the engine's own services (Search Service, profile service) via the
   Shell's privileged APIs; this page keeps no state of its own. */

import { localize, t } from "../lib/i18n.js";
import { TEMPLATE_NAMES, freeName, templateHintKey } from "../lib/names.js";
import {
  announce,
  avatarPicker,
  chip,
  confirmDialog,
  errorText,
  h,
  lockCurrentProfile,
  profileStates,
  rerender,
  stateBadge,
  temporaryStorageText,
  tintAvatars,
} from "../lib/ui.js";
import { setUpAI } from "./ai.js";
import { setUpAppearance } from "./appearance.js";
import { setUpShortcuts } from "./shortcuts.js";
import { setUpLayout } from "./layout.js";
import { setUpNav } from "./nav.js";

const search = browser.nulavioSearch;
const profiles = browser.nulavioProfiles;

function debounce(fn, ms = 60) {
  let timer = null;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, ms);
  };
}

/** Run an action; show errors next to the form (or in the status line). The result is shown next to
    the control that started it; `background` reads (re-rendering a list) belong to no control. */
async function run(action, { form = null, done = null, background = false } = {}) {
  const control = background ? null : document.activeElement;
  const error = form?.querySelector(".form-error");
  if (error) {
    error.textContent = "";
  }
  try {
    const result = await action();
    if (done) {
      announce(done, "ok", { control });
    }
    return result;
  } catch (e) {
    if (error) {
      error.textContent = errorText(e);
    } else {
      announce(errorText(e), "error", { control });
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
    { class: "inline-form", novalidate: true, "data-keep-edits": "" },
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
  aliasForm.addEventListener("submit", async event => {
    event.preventDefault();
    const field = aliasForm.elements.alias;
    const saved = await run(
      async () => {
        await search.setAlias(engine.id, field.value);
        return true;
      },
      { form: aliasForm, done: t("doneSaved") }
    );
    if (saved) {
      field.defaultValue = field.value; // saved: no longer an edit to keep across a redraw
    }
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
  const state = await run(() => search.state(), { background: true });
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
  // Off, the option says what turns it on, not only what it would do (audit 2026-11 SET-09).
  document.getElementById("suggest-private-note").textContent = t(anyOptIn ? "suggestPrivateNote" : "suggestPrivateOff");

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
        h("span", { class: "swatch__fill", style: `--tile: var(--nv-color-identityTile-${color}); --glyph: var(--nv-color-identityGlyph-${color})`, "aria-hidden": "true" }),
        h("span", { class: "visually-hidden", text: t(`color_${color}`) })
      )
    )
  );
}

function profileRow(profile) {
  const form = h(
    "form",
    { class: "stack stack--tight", novalidate: true, "data-keep-edits": "" },
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
    avatarPicker({ avatars: profileOptions.avatars, selected: profile.avatar, color: profile.color, name: profile.name, focusKey: `avatar-${profile.id}` }),
    colorPicker(profile),
    profile.kind === "sensitive" ? h("p", { class: "hint", "data-kind": "sensitive", text: t("profilesSensitiveHint") }) : null,
    h("p", { class: "form-error", role: "alert" }),
    h("div", { class: "actions" }, h("button", { class: "button button--secondary", type: "submit", text: t("profilesSave"), "data-focus-key": `save-${profile.id}` }))
  );
  form.addEventListener("change", event => {
    if (event.target.name === "color") {
      tintAvatars(form.querySelector(".swatches--glyphs"), event.target.value);
    }
  });
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
    if (profile.encrypted && !profile.locked && browser.nulavioVault) {
      const lock = h("button", {
        class: "button button--secondary",
        type: "button",
        text: t("vaultLockCurrent", [profile.name]),
        "data-focus-key": `lock-current-${profile.id}`,
      });
      lock.addEventListener("click", async () => {
        const said = await run(() => lockCurrentProfile(profile.name));
        if (said) {
          announce(said, "info");
        }
      });
      end.push(lock);
    }
    if (profile.id === null) {
      // Not in the profile store yet: no inline editor, so the row's action edits it (audit 2026-11 SET-03).
      const edit = h("button", { class: "button button--secondary", type: "button", text: t("profilesEditCurrent"), "data-focus-key": "edit-current" });
      edit.addEventListener("click", () => run(() => profiles.openCurrentPage("edit")));
      end.push(edit);
    }
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
    // Every way it unlocks, with add, replace and remove (UX4, audit SB-09); phones are one of them.
    const methods = h("a", {
      class: "button button--quiet",
      href: `../vault/methods.html?p=${profile.id}`,
      text: t("bandSurfaceMethods"),
      "aria-label": t("methodsNamed", [profile.name]),
      "data-focus-key": `methods-${profile.id}`,
    });
    end.push(methods);
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
        ...profileStates(profile).map(stateBadge)
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

/** The header names the profile being configured, with its state in words (SPA-05). */
async function renderWhere(state) {
  const where = document.getElementById("settings-where");
  const workspace = browser.nulavioAI ? await browser.nulavioAI.workspaceAgent().catch(() => null) : null;
  const current =
    state.reason === "temporary"
      ? { name: t("profilesTemporaryShort"), color: "slate", avatar: null, temporary: true }
      : state.available
        ? state.profiles.find(p => p.isCurrent)
        : null;
  where.hidden = !current;
  if (!current) {
    return;
  }
  const states = [...(workspace ? ["workspace"] : []), ...profileStates(current)];
  where.replaceChildren(
    chip(current, "md"),
    h("span", { class: "settings-where__label", text: t("whereLabel") }),
    h("strong", { class: "settings-where__name", text: current.temporary ? t("profilesTemporary") : current.name }),
    ...states.map(stateBadge)
  );
}

async function renderProfiles() {
  const state = await run(() => profiles.list(), { background: true });
  if (!state) {
    return;
  }
  renderWhere(state);
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
  // Deleting the profile you are in is a quiet action in the card's footer, never next to its name (SET-03).
  rerender(document.getElementById("profiles-footer"), () => {
    if (!state.profiles.some(p => p.isCurrent)) {
      return [];
    }
    const del = h("button", { class: "button button--quiet", type: "button", text: t("profilesDeleteCurrent"), "data-focus-key": "delete-current" });
    del.addEventListener("click", () => run(() => profiles.openCurrentPage("delete")));
    return [del];
  });
  // A template only fills the form below (audit SPA-09): nothing is created before "Criar perfil".
  const form = document.getElementById("create-profile");
  rerender(document.getElementById("templates"), () =>
    profileOptions.templates.map(template => {
      const name = t(TEMPLATE_NAMES[template.id]);
      const button = h("button", {
        class: "button button--secondary button--with-chip",
        type: "button",
        "aria-pressed": String(form.dataset.template === template.id),
        "data-focus-key": `template-${template.id}`,
        dataset: { template: template.id },
      });
      button.append(chip({ name, avatar: template.avatar, color: template.color }, "sm"), h("span", { text: name }));
      button.addEventListener("click", () => {
        form.dataset.template = template.id;
        form.elements.name.value = freeName(name, state.profiles.map(p => p.name));
        for (const each of document.querySelectorAll("#templates button")) {
          each.setAttribute("aria-pressed", String(each === button));
        }
        document.getElementById("template-hint").textContent = t(templateHintKey(template.id));
        form.elements.name.focus();
      });
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
    const templateId = form.dataset.template;
    const created = await run(() => profiles.create({ name: form.elements.name.value, ...(templateId ? { templateId } : {}) }), {
      form,
      done: t("profilesCreated"),
    });
    if (created !== undefined) {
      form.reset();
      delete form.dataset.template;
      for (const each of document.querySelectorAll("#templates button")) {
        each.setAttribute("aria-pressed", "false");
      }
      document.getElementById("template-hint").textContent = t(templateHintKey(null));
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
  const [state, people] = await Promise.all([run(() => routing.state(), { background: true }), run(() => profiles.list(), { background: true })]);
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
  // With one profile there is nowhere to route to: say so and offer a new profile (audit 2026-11 SET-01).
  const alone = people.profiles.length < 2 && !state.rules.length;
  document.getElementById("routing-empty").hidden = !alone;
  document.getElementById("add-rule").hidden = alone;
  rerender(document.getElementById("rules"), () =>
    state.rules.length ? state.rules.map(ruleRow) : alone ? [] : h("li", { class: "hint", text: t("routingNoRules") })
  );
  // UX6: the default destination for links from other apps; off (disabled) with routing, gone when alone.
  const fallback = document.getElementById("routing-fallback");
  document.getElementById("routing-fallback-field").hidden = alone;
  fallback.disabled = !state.enabled;
  fallback.replaceChildren(
    h("option", { value: "0", text: t("routingFallbackLast") }),
    ...people.profiles
      .filter(p => p.id !== null)
      .map(p => h("option", { value: String(p.id), text: t(p.encrypted ? "routingFallbackAlwaysProtected" : "routingFallbackAlways", [p.name]) })),
    // A deleted destination keeps its own entry: a profile created later can take the same id, and
    // choosing this entry must never make that profile the destination.
    ...(state.fallback.missing ? [h("option", { value: "missing", disabled: true, text: t("routingFallbackGone") })] : [])
  );
  fallback.value = state.fallback.missing ? "missing" : String(state.fallback.profileId);
  // The note says links stop at a warning page: true only while routing is on.
  const missing = state.fallback.missing && state.enabled;
  document.getElementById("routing-fallback-missing").hidden = !missing;
  fallback.setAttribute("aria-describedby", missing ? "routing-fallback-hint routing-fallback-missing" : "routing-fallback-hint");
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
  document.getElementById("routing-fallback").addEventListener("change", event => {
    if (event.target.value !== "missing") {
      run(() => routing.setFallback(Number(event.target.value)), { done: t("doneSaved") });
    }
  });
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
  const items = await run(() => connect.discover(), { background: true });
  list.setAttribute("aria-busy", "false");
  if (items) {
    // What works or can be turned on comes first; what this computer lacks is folded below (SET-05).
    const missing = item => item.state === "unavailable" || item.state === "unknown";
    const absent = items.filter(missing);
    rerender(list, () => items.filter(item => !missing(item)).map(integrationRow));
    rerender(document.getElementById("integration-unavailable"), () => absent.map(integrationRow));
    document.getElementById("integration-more").hidden = !absent.length;
    document.getElementById("integration-more-summary").textContent = t("connectNotFound", [String(absent.length)]);
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
  const state = await run(() => passwords.state(), { background: true });
  const list = document.getElementById("provider-list");
  list.setAttribute("aria-busy", "false"); // also when the read failed: nothing is loading any more
  if (!state) {
    return;
  }
  rerender(list, () => state.providers.map(item => providerRow(item, state)));
  list.setAttribute("aria-busy", "false");
  list.dataset.current = state.current;
  const logins = state.engineLogins;
  document.getElementById("engine-logins").textContent =
    logins === 0 ? t("passwordsEngineLoginsNone") : logins === 1 ? t("passwordsEngineLoginsOne") : t("passwordsEngineLogins", [String(logins)]);
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
  const pairs = await run(() => passwords.listConfirmed(), { background: true });
  if (pairs) {
    renderConfirmed(pairs);
  } else {
    document.getElementById("confirmed-list").setAttribute("aria-busy", "false");
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
  remove.addEventListener("click", async () => {
    // A browser default is removed only after its consequence is said (audit 2026-11 SET-14).
    if (entry.builtIn) {
      const ok = await confirmDialog({
        title: t("exceptionRemoveBuiltInTitle"),
        body: t("exceptionRemoveBuiltInBody", [entry.site, what]),
        confirm: t("engineRemove"),
      });
      if (!ok) {
        return;
      }
    }
    run(() => privacy.remove(entry.type, entry.origin), { done: t("doneRemoved") });
  });
  return h(
    "li",
    { class: "row row--plain", dataset: { type: entry.type, origin: entry.origin, ...(entry.builtIn ? { builtIn: "" } : {}) } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title" }, h("span", { class: "mono", text: entry.site }),
        entry.builtIn ? h("span", { class: "badge badge--quiet", text: t("exceptionBuiltInBadge") }) : null),
      h("p", { class: "hint", text: [what, ...notes].join(" · ") })
    ),
    h("div", { class: "row__end" }, remove)
  );
}

async function renderExceptions() {
  const list = document.getElementById("exception-list");
  const [entries, filter] = await Promise.all([run(() => privacy.exceptions(), { background: true }), run(() => privacy.filter(), { background: true })]);
  list.setAttribute("aria-busy", "false");
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
    // What the default does right now, in plain words (audit 2026-11 SET-02).
    return t(state.encryptedNow ? "dnsNowDefaultEncrypted" : "dnsNowDefaultPlain");
  }
  const name = state.provider === "custom" ? state.uri : t(`dns${state.provider[0].toUpperCase()}${state.provider.slice(1)}`);
  return t(state.choice === "strict" ? "dnsNowStrict" : "dnsNowFallback", [name]);
}

function syncDnsForm(form) {
  const choice = form.elements.choice.value;
  document.getElementById("dns-provider-row").hidden = choice === "system" || choice === "default" || !choice;
  document.getElementById("dns-uri-field").hidden = form.elements.provider.value !== "custom";
  // "Salvar escolha" only when the form says something other than what is in effect.
  const same = choice === form.dataset.choice && (choice === "system" || choice === "default"
    || (form.elements.provider.value === form.dataset.provider && form.elements.uri.value === form.dataset.uri));
  document.getElementById("dns-save").disabled = !choice || choice === "default" || same;
}

async function renderDns() {
  const state = await run(() => privacy.dns(), { background: true });
  if (!state) {
    return;
  }
  const form = document.getElementById("dns-form");
  document.getElementById("dns-current").textContent = dnsText(state);
  form.dataset.choice = state.choice;
  document.getElementById("dns-default-option").hidden = state.choice !== "default";
  for (const radio of form.elements.choice) {
    radio.checked = radio.value === state.choice;
  }
  form.elements.provider.value = state.provider ?? "cloudflare";
  form.elements.uri.value = state.provider === "custom" ? state.uri : "";
  form.dataset.provider = form.elements.provider.value;
  form.dataset.uri = form.elements.uri.value;
  syncDnsForm(form);
}

function setUpDns() {
  document.getElementById("dns").hidden = false;
  const form = document.getElementById("dns-form");
  form.addEventListener("change", () => syncDnsForm(form));
  form.addEventListener("input", () => syncDnsForm(form));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const choice = form.elements.choice.value;
    if (!choice || choice === "default") {
      return; // "Padrão do navegador (atual)" is what is in effect: nothing to save
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
if (browser.nulavioPersonalise) {
  ready.push(setUpAppearance(), setUpShortcuts());
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
setUpNav();
Promise.allSettled(ready).then(() => {
  document.documentElement.dataset.ready = "true";
});
