/* Toolbar profile selector (Alt+Shift+P). One click opens another profile in
   its own window; the engine reuses a running instance instead of starting a
   second one. Creating from a template creates the profile and opens it. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h } from "../lib/ui.js";
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
  const current = state.profiles.find(p => p.isCurrent);
  const others = state.profiles.filter(p => !p.isCurrent);

  document.getElementById("current").replaceChildren(
    ...(current ? [chip(current, "lg"), h("span", { class: "popup__name", text: current.name })] : [])
  );

  const unavailable = document.getElementById("unavailable");
  unavailable.hidden = state.available;
  unavailable.textContent = state.available ? "" : t(state.reason === "disabled" ? "profilesDisabled" : "profilesUnavailable");
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
              "aria-label": t("profilesOpenNamed", [profile.name]),
              dataset: { profileId: String(profile.id) },
            },
            chip(profile, "md"),
            h("span", { class: "popup__name", text: profile.name }),
            key ? h("kbd", { "aria-hidden": "true", text: key }) : null
          );
          button.addEventListener("click", () => act(() => profiles.switchTo(profile.id), t("profilesOpening", [profile.name])));
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
    .then(([state, options]) => render(state, options))
    .catch(e => announce(errorText(e), "error"))
    .finally(() => {
      document.documentElement.dataset.ready = "true";
      document.querySelector("#others .popup__item, #templates button, #manage")?.focus();
    });
}
