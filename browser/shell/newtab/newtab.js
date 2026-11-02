/* New tab: honest, live protection status read from the browser's own
   settings (no counters, no network). */

import { localize, t } from "../lib/i18n.js";
import { errorText } from "../lib/ui.js";

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

// First-run layout choice (D-UX2): shown only on genuinely new profiles,
// synced live with Settings and native sidebar changes.
async function showLayoutChoice() {
  const api = browser.nulavioLayout;
  if (!api) {
    return;
  }
  const card = document.getElementById("layout-choice");
  const group = document.getElementById("layout-choice-options");
  const radios = [...group.querySelectorAll('input[name="newtab-layout"]')];
  const current = document.getElementById("layout-choice-current");
  const error = document.getElementById("layout-choice-error");
  const done = document.getElementById("layout-choice-done");
  const retry = document.getElementById("layout-choice-retry");
  let revision = 0;
  let busy = false;
  let closed = false;
  let listening = false;
  // Keep the card mounted in this tab while the user previews presets by
  // keyboard or pointer so ArrowDown/ArrowUp never collapses the active control.
  let editingInThisTab = false;
  let dismissedInThisTab = false;

  const doneLabel = preset => (
    preset === "lateral" || preset === "top" || preset === "focus"
      ? t(`layoutChoiceKeep_${preset}`)
      : t("layoutChoiceDone")
  );
  const showUnavailable = err => {
    card.hidden = false;
    current.textContent = t("layoutUnavailable");
    error.textContent = errorText(err);
    for (const radio of radios) radio.disabled = true;
    done.hidden = true;
    retry.hidden = false;
  };
  const render = state => {
    if (dismissedInThisTab || (!state.choicePending && !editingInThisTab)) {
      card.hidden = true;
      return;
    }
    card.hidden = false;
    card.dataset.preset = state.preset;
    current.textContent = !state.available ? t("layoutUnavailable") : state.locked ? t("layoutLocked")
      : t(`layoutCurrent_${state.preset}`);
    done.textContent = doneLabel(state.preset);
    done.disabled = busy || !state.available || state.locked;
    done.hidden = false;
    retry.hidden = true;
    for (const radio of radios) {
      radio.checked = radio.value === state.preset;
      radio.disabled = busy || !state.available || state.locked;
    }
  };
  const refreshLayout = async () => {
    if (closed || busy) return;
    const request = ++revision;
    try {
      const state = await api.state();
      if (closed || busy || request !== revision) return;
      render(state);
    } catch (e) {
      if (closed || busy || request !== revision) return;
      if (!card.hidden || editingInThisTab) {
        showUnavailable(e);
      }
    }
  };
  const listen = async () => {
    if (listening) return true;
    try {
      api.onChanged.addListener(refreshLayout);
      listening = true;
      return true;
    } catch (e) {
      let shouldSurface = !card.hidden || editingInThisTab;
      if (!shouldSurface && !dismissedInThisTab) {
        try {
          const state = await api.state();
          shouldSurface = Boolean(state?.choicePending);
        } catch {
          shouldSurface = true;
        }
      }
      if (!closed && shouldSurface) {
        showUnavailable(e);
      } else if (!closed) {
        card.hidden = true;
      }
      return false;
    }
  };

  window.addEventListener("pagehide", () => {
    closed = true;
    revision++;
    if (listening) {
      try {
        api.onChanged.removeListener(refreshLayout);
      } catch {
        // Context already tearing down.
      }
      listening = false;
    }
  });
  window.addEventListener("pageshow", async event => {
    if (!event.persisted) return;
    closed = false;
    group.setAttribute("aria-busy", String(busy));
    if (await listen()) await refreshLayout();
  });
  group.addEventListener("change", async event => {
    if (busy || !radios.includes(event.target)) return;
    editingInThisTab = true;
    busy = true;
    revision++;
    group.setAttribute("aria-busy", "true");
    error.textContent = "";
    const focused = document.activeElement;
    for (const radio of radios) radio.disabled = true;
    done.disabled = true;
    current.textContent = t("layoutApplying");
    try {
      await api.apply(event.target.value);
    } catch (e) {
      if (!closed) error.textContent = errorText(e);
    } finally {
      busy = false;
      if (!closed) {
        group.setAttribute("aria-busy", "false");
        await refreshLayout();
        if (radios.includes(focused) && document.activeElement === document.body && !focused.disabled) {
          focused.focus();
        }
      }
    }
  });
  done.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    revision++;
    error.textContent = "";
    done.disabled = true;
    for (const radio of radios) radio.disabled = true;
    const hadFocusInside = card.contains(document.activeElement);
    try {
      await api.dismissChoice();
      dismissedInThisTab = true;
      editingInThisTab = false;
      card.hidden = true;
      if (hadFocusInside) {
        document.getElementById("search-input")?.focus();
      }
    } catch (e) {
      if (!closed) {
        error.textContent = errorText(e);
        busy = false;
        await refreshLayout();
        return;
      }
    }
    busy = false;
  });
  retry.addEventListener("click", async () => {
    error.textContent = "";
    if (await listen()) await refreshLayout();
  });

  if (await listen()) {
    await refreshLayout();
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
  // The buttons follow what the resolver does now: "keep" always keeps it.
  card.dataset.encrypted = String(state.encryptedNow);
  document.getElementById("dns-actions-system").hidden = state.encryptedNow;
  document.getElementById("dns-actions-encrypted").hidden = !state.encryptedNow;
  if (state.chosen) {
    return;
  }
  const done = async action => {
    await action();
    card.hidden = true;
    await showDns();
  };
  const toSystem = () => done(() => privacy.setDns({ choice: "system" }));
  document.getElementById("dns-keep-system").onclick = toSystem;
  document.getElementById("dns-later").onclick = () => done(() => privacy.dismissDnsChoice());
  // Keeping the engine's encrypted default changes nothing; it only records that the person decided.
  document.getElementById("dns-keep-encrypted").onclick = () => done(() => privacy.dismissDnsChoice());
  document.getElementById("dns-use-system").onclick = toSystem;
}

// Search settings exist only where the Shell is built in (privileged API).
document.getElementById("search-settings").hidden = !browser.nulavioSearch;

localize();
showEngine().catch(() => {});
Promise.allSettled([refresh(), showDns(), showLayoutChoice()]).then(() => {
  document.documentElement.dataset.ready = "true";
});
