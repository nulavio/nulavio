/* Toolbar profile selector (Alt+Shift+P), also opened from the band's profile flag.
   One click opens another profile; the engine brings forward its running instance instead of
   starting a second one. Each row says the profile's state in words (Protegido, Bloqueado)
   and whether it is open now. "Novo perfil…" opens a create sheet: a template only fills it,
   and nothing is created before "Criar e abrir" (UX4, audit SPA-02/09/17). */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h, lockCurrentProfile, profileStates, stateBadge, temporaryStorageText } from "../lib/ui.js";
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
  // A protected profile open in this window can be locked from here: it closes its windows (UX4).
  const actions = document.getElementById("current-actions");
  actions.hidden = !(current?.encrypted && !current.locked && browser.nulavioVault);
  if (!actions.hidden) {
    const lock = h("button", { class: "button button--secondary", type: "button", id: "lock-current", text: t("vaultLockCurrent", [current.name]) });
    lock.addEventListener("click", async () => {
      try {
        const said = await lockCurrentProfile(current.name);
        if (said) {
          announce(said, "info");
        }
      } catch (e) {
        announce(errorText(e), "error");
      }
    });
    actions.replaceChildren(lock);
  }

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

let createdId = null; // made already: a second "Criar e abrir" only opens it (review F15)

sheet.addEventListener("submit", async event => {
  event.preventDefault();
  // Inside the sheet, errors are said in the sheet (the menu's status line is hidden behind it).
  const error = sheet.querySelector(".form-error");
  error.textContent = "";
  const values = Object.fromEntries(new FormData(sheet));
  const name = values.name.trim();
  if (!name) {
    error.textContent = t("err_invalid_name");
    sheet.elements.name.focus();
    return;
  }
  try {
    if (values.protect && createdId === null) {
      // A protected profile is made in the Vault's own steps (password, recovery code), with what was
      // chosen here: name, template, icon and colour.
      const query = new URLSearchParams({
        name,
        avatar: values.avatar,
        color: values.color,
        ...(chosenTemplate ? { template: chosenTemplate } : {}),
      });
      await browser.tabs.create({ url: browser.runtime.getURL(`vault/create.html?${query}`) });
      window.close();
      return;
    }
    if (createdId === null) {
      createdId = await profiles.create({ name, avatar: values.avatar, color: values.color, ...(chosenTemplate ? { templateId: chosenTemplate } : {}) });
    }
    await profiles.switchTo(createdId);
    window.close();
  } catch (e) {
    error.textContent = errorText(e);
    if (createdId !== null) {
      document.getElementById("sheet-create").textContent = t("profilesOpenNamed", [name]);
    }
  }
});
document.getElementById("sheet-back").addEventListener("click", closeSheet);
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !sheet.hidden) {
    event.preventDefault();
    closeSheet();
  }
});

// -- typing filters the list -------------------------------------------------------

const filter = document.getElementById("filter");
const fold = text => String(text).normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase();
const visibleItems = () => [...document.querySelectorAll("#others li:not([hidden]) .popup__item")];

function applyFilter() {
  const query = fold(filter.value.trim());
  let shown = 0;
  for (const item of document.querySelectorAll("#others .popup__item")) {
    const hit = !query || fold(item.querySelector(".popup__name").textContent).includes(query);
    item.parentElement.hidden = !hit;
    shown += hit ? 1 : 0;
  }
  const none = document.getElementById("filter-none");
  none.hidden = shown > 0 || !query;
  none.textContent = none.hidden ? "" : t("profilesFilterNone", [filter.value.trim()]);
}

function clearFilter() {
  filter.value = "";
  filter.hidden = true;
  applyFilter();
}

filter.addEventListener("input", applyFilter);
filter.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    clearFilter();
    document.querySelector("#others .popup__item")?.focus();
  } else if (event.key === "Enter") {
    event.preventDefault();
    visibleItems()[0]?.click();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    visibleItems()[0]?.focus();
  }
});

// -- keyboard: 1–9 open a profile, arrows move between the rows, letters filter -----

document.addEventListener("keydown", event => {
  if (!sheet.hidden || event.altKey || event.ctrlKey || event.metaKey || event.target.closest?.("input, select, textarea")) {
    return;
  }
  const items = visibleItems();
  if (/^\p{L}$/u.test(event.key) && document.querySelectorAll("#others .popup__item").length > 1) {
    event.preventDefault();
    filter.hidden = false;
    filter.value += event.key;
    filter.focus();
    applyFilter();
    return;
  }
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
