/* Pages shown instead of a link that routing held back: "ask" (the user's
   rule says to ask first) and "blocked" (the target profile could not take
   it). Neither page loads the link: the address is shown as text, and opening
   it anywhere is an explicit choice. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h, profileStates, stateBadge } from "../lib/ui.js";

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

async function unlockThere(url, rule, remember) {
  if (remember && rule && rule.action === "ask") {
    await routing.setRuleAction(rule.id, "open-in");
  }
  // The Vault's own page unlocks it and then opens the link there; nothing loads here.
  await browser.nulavioVault.openUnlockPage(rule.profileId, url.href);
  await closeThisTab();
}

function routeEnd(profile, note) {
  return [
    chip(profile, "md"),
    h("span", { class: "route__name", text: profile.name }),
    ...profileStates(profile).map(stateBadge),
    note ? h("span", { class: "route__note", text: note }) : null,
  ].filter(Boolean);
}

async function render() {
  const url = webUrl(params.get("u"));
  if (!url) {
    document.getElementById("explain").textContent = t("routingBadLink");
    return;
  }
  document.getElementById("url").textContent = url.href;
  const [state, people] = await Promise.all([routing.state(), browser.nulavioProfiles.list().catch(() => null)]);
  const rule = state.rules.find(r => r.id === params.get("r")) ?? null;
  const host = url.hostname;
  const record = rule ? people?.profiles.find(p => p.id === rule.profileId) : null;
  const target = record ?? (rule && rule.profileName ? { name: rule.profileName, color: rule.profileColor, avatar: null } : null);
  const current = people?.profiles.find(p => p.isCurrent) ?? null;

  // Where you are → where the rule sends the link (SPA-07).
  if (target && current) {
    document.getElementById("route-from").replaceChildren(...routeEnd(current, t("routingThisProfile")));
    document.getElementById("route-to").replaceChildren(...routeEnd(target));
    document.getElementById("route").hidden = false;
  }
  if (rule && target) {
    const why = document.getElementById("why");
    why.hidden = false;
    document.getElementById("why-text").textContent = t(rule.action === "ask" ? "routingWhyAsk" : "routingWhyOpen", [rule.display, target.name]);
    document.getElementById("edit-rules").hidden = true;
  }

  const actions = [];
  const remember = () => document.getElementById("remember").checked;
  const here = current ? t(mode === "ask" ? "routingOpenIn" : "routingOpenInAnyway", [current.name]) : null;
  // A locked target is unlocked first, from here (SPA-08): never a dead end that pushes "open here".
  const toTarget = record?.locked
    ? button(t("routingUnlockAndOpen", [target.name]), "button--primary", () => unlockThere(url, rule, mode === "ask" && remember()))
    : null;
  if (mode === "ask") {
    const explain = { typed: "routingAskExplainTyped", page: "routingAskExplainPage" }[params.get("src")] ?? "routingAskExplain";
    document.getElementById("explain").textContent = target
      ? t(explain, [host, target.name])
      : t("routingRuleGone", [host]);
    if (target) {
      actions.push(toTarget ?? button(t("routingOpenIn", [target.name]), "button--primary", () => openThere(url, rule, remember())));
      document.getElementById("remember-label").textContent = t("routingRememberFor", [rule.display]);
      document.getElementById("remember-hint").textContent = current
        ? t("routingRememberHint", [target.name, current.name, rule.display])
        : "";
      document.getElementById("remember-field").hidden = false;
    }
    actions.push(button(here ?? t("routingOpenHere"), "button--secondary", () => openHere(url, rule, remember())));
  } else {
    const why = params.get("why");
    const name = rule?.profileName;
    document.getElementById("explain").textContent =
      why === "missing" || !name
        ? t("routingBlockedMissing", [host])
        : why === "launch"
          ? t("routingBlockedLaunch", [host, name])
          : why === "locked"
            ? t("routingBlockedLocked", [host, name])
            : t("routingBlockedError", [host]);
    if (rule && name) {
      actions.push(toTarget ?? button(t("routingTryAgain", [name]), "button--primary", () => openThere(url, rule, false)));
    }
    actions.push(button(here ?? t("routingOpenHereAnyway"), "button--secondary", () => openHere(url, null, false)));
  }
  actions.push(button(t("routingDontOpen"), "button--quiet", closeThisTab));
  actions[0].setAttribute("aria-describedby", "explain");
  document.getElementById("actions").replaceChildren(...actions);
}

localize();
render()
  .catch(e => announce(errorText(e), "error"))
  .finally(() => {
    document.documentElement.dataset.ready = "true";
    document.querySelector("#actions button")?.focus();
  });
