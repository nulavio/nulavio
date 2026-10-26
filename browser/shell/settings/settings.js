/* Nulavio settings: search engines and profiles. Every change goes through
   the engine's own services (Search Service, profile service) via the
   Shell's privileged APIs; this page keeps no state of its own. */

import { localize, t } from "../lib/i18n.js";
import { TEMPLATE_NAMES, freeName } from "../lib/names.js";
import { announce, chip, confirmDialog, errorText, h, rerender } from "../lib/ui.js";

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
    h("p", { class: "form-error", role: "alert" }),
    h("div", { class: "actions" }, h("button", { class: "button button--secondary", type: "submit", text: t("profilesSave"), "data-focus-key": `save-${profile.id}` }))
  );
  form.addEventListener("submit", event => {
    event.preventDefault();
    const { name, avatar, color } = Object.fromEntries(new FormData(form));
    run(() => profiles.update(profile.id, { name, avatar, color }), { form, done: t("doneSaved") });
  });

  const end = [];
  if (profile.isCurrent) {
    const del = h("button", { class: "button button--quiet", type: "button", text: t("profilesDeleteCurrent") });
    del.addEventListener("click", () => run(() => profiles.openCurrentPage("delete")));
    end.push(del);
  } else {
    const open = h("button", {
      class: "button button--secondary",
      type: "button",
      text: t("profilesOpen"),
      "aria-label": t("profilesOpenNamed", [profile.name]),
      "data-focus-key": `open-${profile.id}`,
    });
    open.addEventListener("click", () => run(() => profiles.switchTo(profile.id), { done: t("profilesOpening", [profile.name]) }));
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
    end.push(open, del);
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
        profile.isCurrent ? h("span", { class: "badge", text: t("profilesCurrent") }) : null
      ),
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
  unavailable.textContent = usable ? "" : t(state.reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
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

// -- page -----------------------------------------------------------------

localize();
const ready = [];
if (search && profiles && routing) {
  ready.push(setUpSearch(), setUpProfiles(), setUpRouting());
} else {
  document.getElementById("needs-build").hidden = false;
}
Promise.allSettled(ready).then(() => {
  document.documentElement.dataset.ready = "true";
  document.getElementById(location.hash.slice(1))?.scrollIntoView();
});
