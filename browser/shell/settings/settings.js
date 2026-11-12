/* What is left of the Shell's own settings page: the agents (their permissions, consent and activity) and
   the desktop integrations, plus the one section still waiting to be removed (layout).
   Everything else is drawn by the browser's settings page (ADR 0008, ADR 0011); nav.js sends an old address
   there. This page keeps no state of its own. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, confirmDialog, errorText, h, profileStates, rerender, stateBadge } from "../lib/ui.js";
import { setUpAI } from "./ai.js";
import { setUpLayout } from "./layout.js";
import { setUpNav } from "./nav.js";

const profiles = browser.nulavioProfiles;

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

// -- whose settings these are ------------------------------------------------

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

// -- page -----------------------------------------------------------------

localize();
const ready = [];
if (browser.nulavioLayout) {
  ready.push(setUpLayout());
}
if (profiles && connect) {
  const where = () => profiles.list().then(renderWhere, console.error);
  profiles.onChanged.addListener(where);
  ready.push(where(), setUpIntegrations());
  if (browser.nulavioAI) {
    ready.push(setUpAI());
  }
} else {
  document.getElementById("needs-build").hidden = false;
}
setUpNav();
Promise.allSettled(ready).then(() => {
  document.documentElement.dataset.ready = "true";
});
