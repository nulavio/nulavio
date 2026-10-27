/* New tab: honest, live protection status read from the browser's own
   settings (no counters, no network). */

import { localize, t } from "../lib/i18n.js";

const UBLOCK_ID = "uBlock0@raymondhill.net";
// Official extensions of the supported credential providers (browser/config/providers.json).
const PROVIDERS = [
  ["78272b6fa58f4a1abaac99321d503a20@proton.me", "Proton Pass"],
  ["keepassxc-browser@keepassxc.org", "KeePassXC-Browser"],
  ["{446900e4-71c2-419f-a6a7-df9c091e268b}", "Bitwarden"],
];

function show(key, text, level = "ok") {
  const el = document.querySelector(`[data-status="${key}"]`);
  el.textContent = text;
  el.dataset.level = level; // "ok" | "warn" | "unknown": styled with icon + words, never colour alone
}

async function setting(api) {
  try {
    return (await api.get({})).value;
  } catch {
    return undefined;
  }
}

function mode(value) {
  if (value === "always") return [t("stateAlways"), "ok"];
  if (value === "private_browsing") return [t("statePrivateOnly"), "warn"];
  if (value === "never") return [t("stateOff"), "warn"];
  return [t("stateUnknown"), "unknown"];
}

async function extension(id) {
  try {
    return await browser.management.get(id);
  } catch {
    return null; // not installed
  }
}

async function refresh() {
  show("tracking", ...mode(await setting(browser.privacy.websites.trackingProtectionMode)));
  show("https", ...mode(await setting(browser.privacy.network.httpsOnlyMode)));

  const gpc = await setting(browser.privacy.network.globalPrivacyControl);
  show("gpc", gpc === undefined ? t("stateUnknown") : gpc ? t("gpcSent") : t("gpcNotSent"),
       gpc === undefined ? "unknown" : gpc ? "ok" : "warn");

  const ublock = await extension(UBLOCK_ID);
  if (!ublock) show("filter", t("filterMissing"), "warn");
  else if (!ublock.enabled) show("filter", t("filterDisabled"), "warn");
  else show("filter", t("filterActive", [ublock.version]), "ok");

  const active = [];
  for (const [id, name] of PROVIDERS) {
    const ext = await extension(id);
    if (ext?.enabled) active.push(name);
  }
  const engineSaving = await setting(browser.privacy.services.passwordSavingEnabled);
  if (active.length) show("passwords", active.map(name => t("passwordsProvider", [name])).join(", "), "ok");
  else if (engineSaving) show("passwords", t("passwordsEngine"), "ok");
  else show("passwords", t("passwordsNone"), "warn");
}

document.getElementById("search").addEventListener("submit", event => {
  event.preventDefault();
  const text = document.getElementById("search-input").value.trim();
  if (text) {
    browser.search.query({ text, disposition: "CURRENT_TAB" });
  }
});

async function showEngine() {
  const engines = await browser.search.get();
  const current = engines.find(engine => engine.isDefault);
  if (current) {
    document.getElementById("search-input").placeholder = t("searchWith", [current.name]);
  }
}

// DNS (Nulavio build): how site names are looked up, and the one-time choice.
async function showDns() {
  const privacy = browser.nulavioPrivacy;
  if (!privacy) {
    return;
  }
  const state = await privacy.dns();
  const row = document.getElementById("dns-status");
  row.hidden = false;
  if (state.choice === "system" || state.choice === "default") {
    show("dns", t(state.choice === "system" ? "dnsStatusSystem" : "dnsStatusDefault"), "ok");
  } else {
    show("dns", t(state.choice === "strict" ? "dnsStatusStrict" : "dnsStatusFallback"), "ok");
  }
  const card = document.getElementById("dns-choice");
  card.hidden = state.chosen;
  card.querySelector("p").textContent = t(state.encryptedNow ? "dnsChoiceBodyEncrypted" : "dnsChoiceBody");
  if (state.chosen) {
    return;
  }
  const done = async action => {
    await action();
    card.hidden = true;
    await showDns();
  };
  document.getElementById("dns-keep-system").onclick = () => done(() => privacy.setDns({ choice: "system" }));
  document.getElementById("dns-later").onclick = () => done(() => privacy.dismissDnsChoice());
}

// Search settings exist only where the Shell is built in (privileged API).
document.getElementById("search-settings").hidden = !browser.nulavioSearch;

localize();
showEngine().catch(() => {});
Promise.allSettled([refresh(), showDns()]).then(() => {
  document.documentElement.dataset.ready = "true";
});
