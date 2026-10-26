/* The page shown instead of a locked profile (S6). It unlocks with the
   profile's own methods (password, this computer's login, recovery code),
   then opens the profile, with the address that was held back if there was
   one. The address is shown as text and never loaded here. States are on
   <body data-state>: loading, idle, unlocking, unlocked, error,
   device-unavailable, recovery-required, storage-unavailable, not-locked. */

import { localize, t } from "../lib/i18n.js";
import { announce, chip, errorText, h } from "../lib/ui.js";

const vault = browser.nulavioVault;
const params = new URLSearchParams(location.search);
const profileId = Number(params.get("p"));
const url = webUrl(params.get("u"));
const byId = id => document.getElementById(id);

let profile = null;

function webUrl(raw) {
  try {
    const parsed = new URL(raw ?? "");
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed : null;
  } catch {
    return null;
  }
}

function setState(state, message = "", level = "ok") {
  document.body.dataset.state = state;
  announce(message, level);
}

function busy(on) {
  for (const control of document.querySelectorAll("input, button")) {
    control.disabled = on;
  }
}

function showRecovery(show) {
  byId("recovery-form").hidden = !show;
  byId("password-form").hidden = show || !profile.methods.some(m => m.method === "password");
  byId("alternatives").hidden = show;
  (show ? byId("recovery") : byId("password"))?.focus();
}

async function closeSoon() {
  const tab = await browser.tabs.getCurrent();
  const siblings = await browser.tabs.query({ windowId: tab.windowId });
  // Closing the last tab would close the window (and maybe the browser): show a new tab instead.
  setTimeout(() => (siblings.length > 1 ? browser.tabs.remove(tab.id) : browser.tabs.update(tab.id, { url: "about:newtab" })), 800);
}

async function attempt(method, secret = null) {
  setState("unlocking", t("vaultUnlocking"));
  busy(true);
  try {
    await vault.unlock(profileId, method, secret ?? undefined, url?.href);
    setState("unlocked", t("vaultUnlocked", [profile.name]));
    await closeSoon();
  } catch (e) {
    busy(false);
    const code = String(e?.message ?? e);
    if (code === "keyring-missing" || code === "keyring-unavailable") {
      setState("device-unavailable", t("vaultKeyringUnavailable"), "error");
      (byId("password-form").hidden ? byId("recovery") : byId("password"))?.focus();
    } else if (code === "wrong-secret" || code === "wrong-key") {
      setState("error", t(method === "recovery-code" ? "vaultWrongRecovery" : "vaultWrongPassword"), "error");
      const field = method === "recovery-code" ? byId("recovery") : byId("password");
      field.value = "";
      field.focus();
    } else if (code === "recovery-code-malformed") {
      setState("error", t("vaultRecoveryMalformed"), "error");
      byId("recovery").focus();
    } else {
      setState("error", errorText(e), "error");
    }
  }
}

async function render() {
  const capabilities = await vault.capabilities();
  if (!capabilities.storage || !capabilities.sodium) {
    byId("headline").textContent = t("vaultUnavailableHeadline");
    setState("storage-unavailable", t("vaultStorageMissing"), "error");
    return;
  }
  profile = await vault.status(profileId);
  byId("who").replaceChildren(chip(profile, "lg"), h("span", { class: "popup__name", text: profile.name }));
  if (url) {
    byId("url").textContent = url.href;
    byId("url").hidden = false;
  }
  if (!profile.encrypted || !profile.locked) {
    byId("headline").textContent = t("vaultNotLockedHeadline", [profile.name]);
    byId("explain").textContent = t("vaultNotLocked");
    const open = () =>
      (url ? browser.nulavioRouting.openIn(profileId, url.href) : browser.nulavioProfiles.switchTo(profileId)).then(closeSoon);
    byId("alternatives").replaceChildren(
      h("button", { class: "button button--primary", type: "button", text: t("vaultOpenProfile", [profile.name]), onclick: open })
    );
    setState("not-locked");
    return;
  }
  byId("explain").textContent = url ? t("vaultExplainLink", [profile.name, url.host]) : t("vaultExplain", [profile.name]);
  const kinds = new Set(profile.methods.map(m => m.method));
  byId("password-form").hidden = !kinds.has("password");
  const alternatives = [];
  if (kinds.has("os-keyring")) {
    const onclick = () => attempt("os-keyring");
    alternatives.push(h("button", { class: "button button--secondary", type: "button", id: "use-keyring", text: t("vaultUseKeyring"), onclick }));
  }
  if (kinds.has("recovery-code")) {
    const onclick = () => showRecovery(true);
    alternatives.push(h("button", { class: "button button--quiet", type: "button", id: "use-recovery", text: t("vaultUseRecovery"), onclick }));
  }
  byId("alternatives").replaceChildren(...alternatives);
  if (!kinds.has("password") && !kinds.has("os-keyring")) {
    showRecovery(true);
    setState("recovery-required", t("vaultRecoveryRequired"));
    return;
  }
  setState("idle");
  (kinds.has("password") ? byId("password") : byId("use-keyring"))?.focus();
}

byId("password-form").addEventListener("submit", event => {
  event.preventDefault();
  attempt("password", byId("password").value);
});
byId("recovery-form").addEventListener("submit", event => {
  event.preventDefault();
  attempt("recovery-code", byId("recovery").value);
});
byId("recovery-back").addEventListener("click", () => showRecovery(false));

const UNAVAILABLE = new Set(["tools-missing", "storage-unavailable", "helper-failed"]);

localize();
render()
  .catch(e => {
    if (UNAVAILABLE.has(String(e?.message))) {
      byId("headline").textContent = t("vaultUnavailableHeadline");
      setState("storage-unavailable", t("vaultStorageMissing"), "error");
    } else {
      setState("error", errorText(e), "error");
    }
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
