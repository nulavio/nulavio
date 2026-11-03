/* Toolbar profile selector (Alt+Shift+P), also opened from the band's profile flag.
   One click opens another profile; the engine brings forward its running instance instead of
   starting a second one. Each row says the profile's state in words (Protegido, Bloqueado)
   and whether it is open now. "Novo perfil…" opens a create sheet: a template only fills it,
   and nothing is created before "Criar e abrir" (UX4, audit SPA-02/09/17). */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h, profileStates, stateBadge, temporaryStorageText } from "../lib/ui.js";
import { TEMPLATE_NAMES, freeName } from "../lib/names.js";

const profiles = browser.nulavioProfiles;
let known = { profiles: [] };
let options = null;

async function act(action, doneText) {
  try {
    await action();
    if (doneText) {
      announce(doneText);
    }
    window.close();
  } catch (e) {
    announce(errorText(e), "error");
  }
}

/** A row's name is what it shows: the verb and name, then its state and whether it is open. */
function rowName(profile) {
  if (profile.locked) {
    return t("profilesUnlockNamed", [profile.name]); // "Bancos, bloqueado, desbloquear…"
  }
  const extras = [
    ...profileStates(profile).map(state => t(state === "protected" ? "vaultProtectedBadge" : "profilesTemporaryShort")),
    ...(profile.running ? [t("profileRunning")] : []),
  ];
  return [t("profilesOpenNamed", [profile.name]), ...extras].join(", ");
}

function profileRow(profile, index) {
  const key = index < 9 ? String(index + 1) : null;
  const button = h(
    "button",
    {
      class: "popup__item",
      type: "button",
      "aria-keyshortcuts": key,
      "aria-label": rowName(profile),
      dataset: { profileId: String(profile.id), running: String(Boolean(profile.running)) },
    },
    chip(profile, "md"),
    h("span", { class: "popup__name", text: profile.name }),
    ...profileStates(profile).map(stateBadge),
    profile.running ? h("span", { class: "popup__running", text: t("profileRunning") }) : null,
    key ? h("kbd", { "aria-hidden": "true", text: key }) : null
  );
  button.addEventListener("click", () =>
    profile.locked
      ? act(() => browser.nulavioVault.openUnlockPage(profile.id))
      : act(() => profiles.switchTo(profile.id), t("profilesOpening", [profile.name]))
  );
  return h("li", {}, button);
}

function render(state) {
  const temporary = state.reason === "temporary";
  const current = temporary ? { ...state.profiles[0], name: t("profilesTemporary") } : state.profiles.find(p => p.isCurrent);
  const others = state.profiles.filter(p => !p.isCurrent);
  // A temporary profile's chip shows the initial of "Temporary", not of "Temporary profile" in every language.
  const badge = temporary ? { ...current, name: t("profilesTemporaryShort") } : current;

  document.getElementById("current").replaceChildren(
    ...(current
      ? [chip(badge, "lg"), h("span", { class: "popup__name", text: current.name }), ...profileStates(current).map(stateBadge)]
      : [])
  );
  document.querySelector(".popup__keys").hidden = temporary;

  const unavailable = document.getElementById("unavailable");
  unavailable.hidden = state.available;
  unavailable.textContent = state.available
    ? ""
    : temporary
      ? temporaryStorageText(state.temporary)
      : t(state.reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
  document.getElementById("others-section").hidden = !state.available;
  document.getElementById("new-profile").hidden = !state.available;
  if (!state.available) {
    return;
  }
  document
    .getElementById("others")
    .replaceChildren(...(others.length ? others.map(profileRow) : [h("li", { class: "popup__empty", text: t("profilesNone") })]));
}

/* "Always open this site in this profile": a rule the user creates with one
   click, for the site of the active tab (activeTab: only after this click). */
async function renderSite(state) {
  const routing = browser.nulavioRouting;
  const current = state.profiles.find(p => p.isCurrent);
  if (!routing || !state.available || !current?.id || state.profiles.length < 2) {
    return;
  }
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) {
    return;
  }
  const site = await routing.ruleFor(tab.url);
  const name = site.registrable ? site.registrable : site.host;
  const shown = site.registrable ? (await routing.ruleFor(`https://${site.registrable}/`)).display : site.display;
  const rule = site.rule;
  const text = document.getElementById("site-rule");
  const actions = [];
  if (rule && rule.action !== "stay") {
    const target = state.profiles.find(p => p.id === rule.profileId);
    text.textContent = target ? t("routingSiteOpensIn", [shown, target.name]) : t("routingTargetMissing");
    const remove = h("button", { class: "button button--quiet", type: "button", text: t("routingRemoveRule") });
    remove.addEventListener("click", () => act(() => routing.removeRule(rule.id), t("doneRemoved")));
    actions.push(remove);
  }
  if (!rule || rule.profileId !== current.id) {
    const always = h("button", { class: "button button--secondary", type: "button", text: t("routingAlwaysHere", [shown]) });
    always.addEventListener("click", () =>
      act(
        () =>
          routing.addRule({
            site: name,
            match: site.registrable ? "domain" : "host",
            action: "open-in",
            profileId: current.id,
          }),
        t("doneAdded")
      )
    );
    actions.unshift(always);
  }
  document.getElementById("site-actions").replaceChildren(...actions);
  document.getElementById("site-section").hidden = actions.length === 0;
}

// -- the create sheet ------------------------------------------------------------

const sheet = document.getElementById("sheet");
let chosenTemplate = null;

function fillSheet(template) {
  chosenTemplate = template?.id ?? null;
  for (const button of document.querySelectorAll("#templates button")) {
    button.setAttribute("aria-pressed", String(button.dataset.template === chosenTemplate));
  }
  const name = sheet.elements.name;
  if (template && !name.dataset.touched) {
    name.value = freeName(t(TEMPLATE_NAMES[template.id]), known.profiles.map(p => p.name));
  }
  if (template) {
    sheet.elements.avatar.value = template.avatar;
    sheet.querySelector(`input[name="color"][value="${template.color}"]`).checked = true;
  }
}

function buildSheet() {
  document.getElementById("templates").replaceChildren(
    ...options.templates.map(template => {
      const name = t(TEMPLATE_NAMES[template.id]);
      const button = h(
        "button",
        { class: "button button--secondary button--with-chip", type: "button", "aria-pressed": "false", dataset: { template: template.id } },
        chip({ name, avatar: template.avatar, color: template.color }, "sm"),
        h("span", { text: name })
      );
      button.addEventListener("click", () => fillSheet(template));
      return button;
    })
  );
  document.getElementById("sheet-avatar").replaceChildren(
    ...options.avatars.map(a => h("option", { value: a, text: browser.i18n.getMessage(`avatar_${a.replaceAll("-", "_")}`) || a }))
  );
  const colors = document.getElementById("sheet-colors");
  colors.append(
    ...options.colors.map((color, index) =>
      h(
        "label",
        { class: "swatch", title: t(`color_${color}`) },
        h("input", { type: "radio", name: "color", value: color, checked: index === 0 }),
        h("span", { class: "swatch__fill", style: `--chip: var(--nv-color-identity-${color})`, "aria-hidden": "true" }),
        h("span", { class: "visually-hidden", text: t(`color_${color}`) })
      )
    )
  );
  sheet.elements.name.addEventListener("input", () => {
    sheet.elements.name.dataset.touched = "1";
  });
}

function openSheet() {
  document.getElementById("menu").hidden = true;
  sheet.hidden = false;
  sheet.querySelector(".form-error").textContent = "";
  sheet.elements.name.focus();
}

function closeSheet() {
  sheet.hidden = true;
  document.getElementById("menu").hidden = false;
  document.getElementById("new-profile").focus();
}

sheet.addEventListener("submit", async event => {
  event.preventDefault();
  const error = sheet.querySelector(".form-error");
  error.textContent = "";
  const values = Object.fromEntries(new FormData(sheet));
  const name = values.name.trim();
  if (!name) {
    error.textContent = t("err_invalid_name");
    sheet.elements.name.focus();
    return;
  }
  if (values.protect) {
    // A protected profile is made in the Vault's own steps (password, recovery code), prefilled here.
    const query = new URLSearchParams({ name, ...(chosenTemplate ? { template: chosenTemplate } : {}) });
    await act(() => browser.tabs.create({ url: browser.runtime.getURL(`vault/create.html?${query}`) }));
    return;
  }
  try {
    const id = await profiles.create({ name, avatar: values.avatar, color: values.color, ...(chosenTemplate ? { templateId: chosenTemplate } : {}) });
    await act(() => profiles.switchTo(id), t("profilesCreated"));
  } catch (e) {
    error.textContent = errorText(e);
  }
});
document.getElementById("sheet-back").addEventListener("click", closeSheet);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !sheet.hidden) {
    event.preventDefault();
    closeSheet();
  }
});

// -- keyboard: 1–9 open a profile, arrows move between the rows ------------------

document.addEventListener("keydown", event => {
  if (!sheet.hidden || event.altKey || event.ctrlKey || event.metaKey || event.target.closest?.("input, select, textarea")) {
    return;
  }
  const items = [...document.querySelectorAll("#others .popup__item")];
  if (/^[1-9]$/.test(event.key)) {
    const item = items[Number(event.key) - 1];
    if (item) {
      event.preventDefault();
      item.click();
    }
    return;
  }
  const at = items.indexOf(document.activeElement);
  const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key];
  if (at !== -1 && next !== undefined && items[next]) {
    event.preventDefault();
    items[next].focus();
  }
});

async function openShellPage(path) {
  await browser.tabs.create({ url: browser.runtime.getURL(path) });
  window.close();
}
document.getElementById("manage").addEventListener("click", () => openShellPage("settings/settings.html#profiles"));
document.getElementById("settings").addEventListener("click", () => openShellPage("settings/settings.html"));
document.getElementById("new-profile").addEventListener("click", openSheet);
document.getElementById("new-temporary").addEventListener("click", () =>
  act(() => profiles.openTemporary(), t("profilesTemporaryOpening"))
);

localize();
if (profiles) {
  Promise.all([profiles.list(), profiles.options()])
    .then(async ([state, choices]) => {
      known = state;
      options = choices;
      buildSheet();
      render(state);
      await renderSite(state).catch(e => console.error(e));
    })
    .catch(e => announce(errorText(e), "error"))
    .finally(() => {
      document.documentElement.dataset.ready = "true";
      // In a temporary profile the way out is another temporary window (SPA-17).
      const first = known.reason === "temporary" ? "#new-temporary" : "#others .popup__item, #new-profile:not([hidden]), #manage";
      document.querySelector(first)?.focus();
    });
}
