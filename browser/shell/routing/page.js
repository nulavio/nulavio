/* Pages shown instead of a link that routing held back: "ask" (the user's
   rule says to ask first) and "blocked" (the target profile could not take
   it). Neither page loads the link: the address is shown as text, and opening
   it anywhere is an explicit choice. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h } from "../lib/ui.js";

const routing = browser.nulavioRouting;
const mode = document.body.dataset.mode;
const params = new URLSearchParams(location.search);

function webUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

async function closeThisTab() {
  const tab = await browser.tabs.getCurrent();
  await browser.tabs.remove(tab.id);
}

async function openHere(url, rule, remember) {
  if (remember && rule) {
    await routing.setRuleAction(rule.id, "stay");
  }
  const tab = await browser.tabs.getCurrent();
  await browser.tabs.update(tab.id, { url: url.href });
}

async function openThere(url, rule, remember) {
  if (remember && rule && rule.action === "ask") {
    await routing.setRuleAction(rule.id, "open-in");
  }
  await routing.openIn(rule.profileId, url.href);
  await closeThisTab();
}

function button(label, kind, action) {
  const el = h("button", { class: `button ${kind}`, type: "button", text: label });
  el.addEventListener("click", async () => {
    for (const b of document.querySelectorAll("#actions button")) {
      b.disabled = true;
    }
    try {
      await action();
    } catch (e) {
      announce(errorText(e), "error");
      for (const b of document.querySelectorAll("#actions button")) {
        b.disabled = false;
      }
    }
  });
  return el;
}

async function render() {
  const url = webUrl(params.get("u"));
  if (!url) {
    document.getElementById("explain").textContent = t("routingBadLink");
    return;
  }
  document.getElementById("url").textContent = url.href;
  const state = await routing.state();
  const rule = state.rules.find(r => r.id === params.get("r")) ?? null;
  const host = url.hostname;
  const target = rule && rule.profileName ? { name: rule.profileName, color: rule.profileColor, avatar: null } : null;

  if (target) {
    const box = document.getElementById("target");
    box.hidden = false;
    box.replaceChildren(chip(target, "md"), h("span", { class: "popup__name", text: target.name }));
  }

  const actions = [];
  const remember = () => document.getElementById("remember").checked;
  if (mode === "ask") {
    const typed = params.get("src") === "typed";
    document.getElementById("explain").textContent = target
      ? t(typed ? "routingAskExplainTyped" : "routingAskExplain", [host, target.name])
      : t("routingRuleGone", [host]);
    if (target) {
      actions.push(button(t("routingOpenIn", [target.name]), "button--primary", () => openThere(url, rule, remember())));
      document.getElementById("remember-field").hidden = false;
    }
    actions.push(button(t("routingOpenHere"), "button--secondary", () => openHere(url, rule, remember())));
  } else {
    const why = params.get("why");
    const name = rule?.profileName;
    document.getElementById("explain").textContent =
      why === "missing" || !name
        ? t("routingBlockedMissing", [host])
        : why === "launch"
          ? t("routingBlockedLaunch", [host, name])
          : t("routingBlockedError", [host]);
    if (rule && name) {
      actions.push(button(t("routingTryAgain", [name]), "button--primary", () => openThere(url, rule, false)));
    }
    actions.push(button(t("routingOpenHereAnyway"), "button--secondary", () => openHere(url, null, false)));
  }
  document.getElementById("actions").replaceChildren(...actions);
}

localize();
render()
  .catch(e => announce(errorText(e), "error"))
  .finally(() => {
    document.documentElement.dataset.ready = "true";
    document.querySelector("#actions button")?.focus();
  });
