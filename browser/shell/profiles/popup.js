/* Toolbar profile selector (Alt+Shift+P). One click opens another profile in
   its own window; the engine reuses a running instance instead of starting a
   second one. Creating from a template creates the profile and opens it. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h, temporaryStorageText } from "../lib/ui.js";
import { TEMPLATE_NAMES, freeName } from "../lib/names.js";

const profiles = browser.nulavioProfiles;

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

function render(state, options) {
  const temporary = state.reason === "temporary";
  const current = temporary ? { ...state.profiles[0], name: t("profilesTemporary") } : state.profiles.find(p => p.isCurrent);
  const others = state.profiles.filter(p => !p.isCurrent);
  // A temporary profile's chip shows the initial of "Temporary", not of "Temporary profile" in every language.
  const badge = temporary ? { ...current, name: t("profilesTemporaryShort") } : current;

  document.getElementById("current").replaceChildren(
    ...(current ? [chip(badge, "lg"), h("span", { class: "popup__name", text: current.name })] : [])
  );
  document.querySelector(".popup__keys").hidden = temporary;

  const unavailable = document.getElementById("unavailable");
  unavailable.hidden = state.available;
  unavailable.textContent = state.available
    ? ""
    : temporary
      ? temporaryStorageText(state.temporary)
      : t(state.reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
  document.getElementById("new-protected").hidden = temporary;
  document.getElementById("others-section").hidden = !state.available;
  document.getElementById("new-section").hidden = !state.available;
  if (!state.available) {
    return;
  }

  const list = document.getElementById("others");
  list.replaceChildren(
    ...(others.length
      ? others.map((profile, index) => {
          const key = index < 9 ? String(index + 1) : null;
          const button = h(
            "button",
            {
              class: "popup__item",
              type: "button",
              "aria-keyshortcuts": key,
              // The visible name and state stay in the accessible name (SPA-10, SB-17).
              "aria-label": t(profile.locked ? "profilesUnlockNamed" : "profilesOpenNamed", [profile.name]),
              dataset: { profileId: String(profile.id) },
            },
            chip(profile, "md"),
            h("span", { class: "popup__name", text: profile.name }),
            profile.locked ? h("span", { class: "badge", text: t("profilesLocked") }) : null,
            key ? h("kbd", { "aria-hidden": "true", text: key }) : null
          );
          button.addEventListener("click", () =>
            profile.locked
              ? act(() => browser.nulavioVault.openUnlockPage(profile.id))
              : act(() => profiles.switchTo(profile.id), t("profilesOpening", [profile.name]))
          );
          return h("li", {}, button);
        })
      : [h("li", { class: "popup__empty", text: t("profilesNone") })])
  );

  document.getElementById("templates").replaceChildren(
    ...options.templates.map(template => {
      const name = t(TEMPLATE_NAMES[template.id]);
      const button = h(
        "button",
        { class: "button button--secondary button--with-chip", type: "button", dataset: { template: template.id } },
        chip({ name, avatar: template.avatar, color: template.color }, "sm"),
        h("span", { text: name })
      );
      button.addEventListener("click", () =>
        act(async () => {
          const id = await profiles.create({ templateId: template.id, name: freeName(name, state.profiles.map(p => p.name)) });
          await profiles.switchTo(id);
        }, t("profilesCreated"))
      );
      return button;
    })
  );
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

document.addEventListener("keydown", event => {
  if (event.altKey || event.ctrlKey || event.metaKey || !/^[1-9]$/.test(event.key)) {
    return;
  }
  if (event.target.closest?.("input, select, textarea")) {
    return;
  }
  const item = document.querySelectorAll("#others .popup__item")[Number(event.key) - 1];
  if (item) {
    event.preventDefault();
    item.click();
  }
});

document.getElementById("manage").addEventListener("click", async () => {
  await browser.tabs.create({ url: browser.runtime.getURL("settings/settings.html#profiles") });
  window.close();
});

localize();
if (profiles) {
  Promise.all([profiles.list(), profiles.options()])
    .then(async ([state, options]) => {
      render(state, options);
      await renderSite(state).catch(e => console.error(e));
    })
    .catch(e => announce(errorText(e), "error"))
    .finally(() => {
      document.documentElement.dataset.ready = "true";
      document.querySelector("#others .popup__item, #templates button, #manage")?.focus();
    });
}

document.getElementById("new-temporary").addEventListener("click", () =>
  act(() => profiles.openTemporary(), t("profilesTemporaryOpening"))
);

document.getElementById("new-protected").addEventListener("click", () =>
  act(() => browser.tabs.create({ url: browser.runtime.getURL("vault/create.html") }))
);
