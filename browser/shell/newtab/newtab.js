/* New tab: honest, live protection status read from the browser's own
   settings (no counters, no network). */

import { localize, t } from "../lib/i18n.js";
import { keyElements, nulavioKeys } from "../lib/keys.js";
import { chip, errorText, h, settleRadioChanges, stateBadge } from "../lib/ui.js";

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
  // Every new tab reads these; they are independent, so they go out together
  // (one round trip of latency instead of eight). Display order is unchanged.
  const [tracking, https, gpc, ublock, providers, engineSaving] = await Promise.all([
    setting(browser.privacy.websites.trackingProtectionMode),
    setting(browser.privacy.network.httpsOnlyMode),
    setting(browser.privacy.network.globalPrivacyControl),
    extension(UBLOCK_ID),
    Promise.all(PROVIDERS.map(([id]) => extension(id))),
    setting(browser.privacy.services.passwordSavingEnabled),
  ]);
  show("tracking", ...mode(tracking));
  show("https", ...mode(https));

  show("gpc", gpc === undefined ? t("stateUnknown") : gpc ? t("gpcSent") : t("gpcNotSent"),
       gpc === undefined ? "unknown" : gpc ? "ok" : "warn");

  if (!ublock) show("filter", t("filterMissing"), "warn");
  else if (!ublock.enabled) show("filter", t("filterDisabled"), "warn");
  else show("filter", t("filterActive", [ublock.version]), "ok");

  const active = PROVIDERS.filter((_, i) => providers[i]?.enabled).map(([, name]) => name);
  if (active.length) show("passwords", active.map(name => t("passwordsProvider", [name])).join(", "), "ok");
  else if (engineSaving) show("passwords", t("passwordsEngine"), "ok");
  else show("passwords", t("passwordsNone"), "warn");
}

/* One line of facts (UX4): what needs attention, by name, or that the protections are on. No
   "tudo certo": a fact that could not be read says so. Details open by themselves when
   something needs attention. */
function summarise() {
  const facts = [...document.querySelectorAll("#status [data-status]")].filter(dd => !dd.closest("[hidden]"));
  const named = level => facts.filter(dd => dd.dataset.level === level).map(dd => dd.previousElementSibling.textContent);
  const [warn, unknown] = [named("warn"), named("unknown")];
  const summary = document.getElementById("here-summary");
  if (warn.length) {
    summary.dataset.level = "warn";
    summary.textContent = t("protectionsAttention", [warn.join(", ")]);
    document.getElementById("here-details").open = true;
  } else if (unknown.length) {
    summary.dataset.level = "unknown";
    summary.textContent = t("protectionsUnknown", [unknown.join(", ")]);
  } else {
    summary.dataset.level = "ok";
    summary.textContent = t("protectionsOn");
  }
}

// "Você está em …" (Track B): this profile, its state in words and the rules that open sites here.
async function showHere() {
  const here = await browser.nulavioProfiles?.here?.();
  if (!here) {
    return;
  }
  const states = browser.extension.inIncognitoContext
    ? ["private"]
    : here.temporary
      ? ["temporary"]
      : here.protection === "unlocked"
        ? ["protected"]
        : [];
  const who = document.getElementById("here-who");
  const plain = !states.length && here.protection === "plain";
  who.replaceChildren(
    chip(here, "md"),
    h("span", { class: "here__label", text: t("whereLabel") }),
    h("strong", { class: "here__name", text: here.temporary ? t("profilesTemporary") : here.name }),
    ...states.map(stateBadge),
    // One term everywhere for a profile without a password (audit 2026-11 T3): a quiet badge.
    ...(plain ? [h("span", { class: "badge badge--quiet here__plain", text: `◇ ${t("profileUnprotected")}` })] : [])
  );
  who.hidden = false;
  if (here.routeCount) {
    const routes = document.getElementById("here-routes");
    routes.textContent = t("routesHere", [String(here.routeCount)]);
    routes.hidden = false;
    document.getElementById("here-sites").replaceChildren(...here.routes.map(site => h("li", { class: "mono", text: site })));
    document.getElementById("here-route-list").hidden = false;
  }
}

// UX3G N5: the label and the search use the same engine. The engine is read
// only after the profile's first-run search migration has settled, and a
// search made before then waits for it instead of guessing.
let shownEngine = null;

async function defaultEngineName() {
  const managed = browser.nulavioSearch;
  if (managed) {
    // state() waits for the first-run migration, so the default is final.
    const { engines } = await managed.state();
    const key = browser.extension.inIncognitoContext ? "isDefaultPrivate" : "isDefault";
    return (engines.find(engine => engine[key]) ?? engines.find(engine => engine.isDefault))?.name ?? null;
  }
  const engines = await browser.search.get();
  return engines.find(engine => engine.isDefault)?.name ?? null;
}

async function showEngine() {
  const name = await defaultEngineName();
  shownEngine = name;
  const input = document.getElementById("search-input");
  input.placeholder = name ? t("searchWith", [name]) : t("searchPlaceholder");
}
const engineShown = showEngine().catch(() => {});

document.getElementById("search").addEventListener("submit", async event => {
  event.preventDefault();
  const text = document.getElementById("search-input").value.trim();
  if (!text) {
    return;
  }
  await engineShown;
  if (shownEngine) {
    browser.search.search({ query: text, engine: shownEngine, disposition: "CURRENT_TAB" });
  } else {
    browser.search.query({ text, disposition: "CURRENT_TAB" });
  }
});

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
  const body = document.getElementById("layout-choice-body");
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
  let keyboard = null;

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
      // The choice is settled (dismissed here, or no longer pending while the
      // sidebar is available and unlocked): this tab no longer follows layout
      // changes (every open new tab answered each one with a privileged state()
      // call). A choice hidden only because the sidebar is off or a pref is
      // locked can come back, so that tab keeps listening.
      const settled = dismissedInThisTab || (state.available && !state.locked);
      if (settled && !busy && !keyboard?.pending()) {
        unlisten();
      }
      return;
    }
    card.hidden = false;
    card.dataset.preset = state.preset;
    // QA B-2: "start with Lateral, you can keep it" only while the window is in Lateral.
    body.textContent = t(state.preset === "lateral" ? "layoutChoiceBody" : "layoutChoiceBodyOpen");
    current.textContent = !state.available ? t("layoutUnavailable") : state.locked ? t("layoutLocked")
      : t(`layoutCurrent_${state.preset}`);
    done.textContent = doneLabel(state.preset);
    // QA B-7: never disabled while a preset applies, so Tab from the radios still lands on it
    // (in visual order) instead of skipping to the next link; clicks wait on `busy`.
    done.disabled = !state.available || state.locked;
    done.setAttribute("aria-disabled", String(busy));
    done.hidden = false;
    retry.hidden = true;
    for (const radio of radios) {
      radio.checked = radio.value === state.preset;
      radio.disabled = busy || !state.available || state.locked;
    }
  };
  const refreshLayout = async () => {
    if (closed || busy || keyboard?.pending()) return;
    const request = ++revision;
    try {
      const state = await api.state();
      if (closed || busy || keyboard?.pending() || request !== revision) return;
      render(state);
    } catch (e) {
      if (closed || busy || request !== revision) return;
      if (!card.hidden || editingInThisTab) {
        showUnavailable(e);
      }
    }
  };
  const unlisten = () => {
    if (!listening) return;
    try {
      api.onChanged.removeListener(refreshLayout);
    } catch {
      // Context already tearing down.
    }
    listening = false;
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
  group.addEventListener("change", event => {
    if (radios.includes(event.target)) {
      editingInThisTab = true;
      revision++;
      // UX3E QA N-1: the action names the selected layout at once, not after it applies.
      done.textContent = doneLabel(event.target.value);
    }
  });
  keyboard = settleRadioChanges(group, async event => {
    const chosen = radios.find(radio => radio.checked);
    if (busy || !radios.includes(event.target) || !chosen) return;
    editingInThisTab = true;
    busy = true;
    revision++;
    group.setAttribute("aria-busy", "true");
    error.textContent = "";
    const focused = document.activeElement;
    for (const radio of radios) radio.disabled = true;
    done.setAttribute("aria-disabled", "true");
    current.textContent = t("layoutApplying");
    try {
      await api.apply(chosen.value);
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
    // A keyboard choice still waiting applies first, so "Manter …" keeps what is selected.
    if (keyboard?.pending()) await keyboard.flush();
    if (busy) return;
    busy = true;
    revision++;
    error.textContent = "";
    done.setAttribute("aria-disabled", "true");
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
  document.getElementById("dns-choice-body").textContent = t(state.encryptedNow ? "dnsChoiceBodyEncrypted" : "dnsChoiceBody");
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

// -- First run (audit 2026-11 FR-01) -------------------------------------------------------------
// In a genuinely new profile, one card at a time below the search: welcome, the layout and DNS
// cards (steps 1 and 2), passwords, the default browser, then "all set". Each answer applies at
// once and is never asked again; a tab closed midway resumes at the first step not yet answered.
// Private windows, temporary profiles and AI Workspaces never see it (NulavioPrivacy.firstRun).
const QUESTIONS = ["layout", "dns", "passwords", "default-browser"];
const STEP_CARDS = {
  welcome: "firstrun-welcome",
  layout: "layout-choice",
  dns: "dns-choice",
  passwords: "firstrun-passwords",
  "default-browser": "firstrun-default",
  finished: "firstrun-done",
};
const FIRST_CONTROL = {
  welcome: "firstrun-start",
  layout: "layout-choice-done",
  dns: "dns-choice-heading",
  passwords: "firstrun-passwords-choose",
  "default-browser": "firstrun-default-make",
  finished: "firstrun-finish",
};

async function firstRun() {
  const privacy = browser.nulavioPrivacy;
  if (!privacy?.firstRun || browser.extension.inIncognitoContext) {
    return;
  }
  const start = await privacy.firstRun().catch(() => null);
  if (!start?.active) {
    return;
  }
  const layoutApi = browser.nulavioLayout;
  const connect = browser.nulavioConnect;
  const done = new Set(start.done);
  const [layout, dns, defaultBrowser] = await Promise.all([
    layoutApi?.state().catch(() => null),
    privacy.dns().catch(() => null),
    connect?.defaultBrowserState?.().catch(() => null),
  ]);
  // The steps that apply here: asked now, or answered earlier in this same sequence (so "Etapa N de M"
  // keeps its numbers in a tab opened later).
  const applies = {
    layout: done.has("layout") || Boolean(layout?.choicePending),
    dns: done.has("dns") || dns?.chosen === false,
    passwords: true,
    "default-browser": done.has("default-browser") || defaultBrowser?.state === "available",
  };
  const questions = QUESTIONS.filter(step => applies[step]);
  const order = ["welcome", ...questions, "finished"];
  const progress = document.getElementById("firstrun-progress");
  const searchButton = document.querySelector("#search .button");
  let current = null;

  const pending = async step => {
    if (done.has(step)) {
      return false;
    }
    if (step === "layout") {
      return Boolean((await layoutApi.state().catch(() => null))?.choicePending);
    }
    if (step === "dns") {
      return (await privacy.dns().catch(() => null))?.chosen === false;
    }
    return true;
  };
  const record = async step => {
    done.add(step);
    await privacy.firstRunDone([step]).catch(() => {});
  };
  const show = step => {
    current = step;
    for (const [name, id] of Object.entries(STEP_CARDS)) {
      const card = document.getElementById(id);
      card.toggleAttribute("data-gated", name !== step);
      if (card.classList.contains("firstrun")) {
        card.hidden = name !== step;
      }
    }
    const n = questions.indexOf(step);
    progress.hidden = n < 0;
    progress.textContent = n < 0 ? "" : t("firstrunProgress", [String(n + 1), String(questions.length)]);
    // While a first-run card is the page's question, the search is not its main action.
    searchButton.classList.toggle("button--primary", !step);
    searchButton.classList.toggle("button--secondary", Boolean(step));
  };
  const leave = () => {
    show(null);
    for (const id of Object.values(STEP_CARDS)) {
      document.getElementById(id).removeAttribute("data-gated");
    }
  };
  // Go to the first step not answered yet. Focus follows only when the person was in a first-run card
  // (on load the keyboard stays where the browser put it).
  const advance = async (answered, { focus = false } = {}) => {
    const wasInside = focus || Object.values(STEP_CARDS).some(id => document.getElementById(id).contains(document.activeElement));
    if (answered) {
      await record(answered);
    }
    for (const step of order) {
      if (step === "finished") {
        await fillSummary();
        show(step);
        break;
      }
      if (await pending(step)) {
        show(step);
        break;
      }
      if ((step === "layout" || step === "dns") && !done.has(step)) {
        await record(step); // answered in its card (or in Settings): never asked again
      }
    }
    if (wasInside) {
      const control = document.getElementById(FIRST_CONTROL[current]);
      if (control?.matches("h2")) {
        control.tabIndex = -1; // a heading takes focus only from here, as a reading position
      }
      control?.focus();
    }
  };

  const fact = key => document.querySelector(`#status [data-status="${key}"]`);
  const factLine = key => `${fact(key).previousElementSibling.textContent}: ${fact(key).textContent}`;
  document.getElementById("firstrun-facts").replaceChildren(
    ...["tracking", "https", "filter"].map(key => h("li", { "data-level": fact(key).dataset.level, text: factLine(key) })),
    h("li", { "data-level": "ok", text: t("firstrunNothingSent") })
  );
  document.getElementById("firstrun-passwords-now").textContent = t("firstrunPasswordsNow", [fact("passwords").textContent]);

  async function fillSummary() {
    const [layoutNow, dnsNow, defaultNow] = await Promise.all([
      layoutApi?.state().catch(() => null),
      privacy.dns().catch(() => null),
      applies["default-browser"] ? connect.defaultBrowserState().catch(() => null) : null,
    ]);
    const presetKey = { lateral: "layoutLateral", top: "layoutTop", focus: "layoutFocus" }[layoutNow?.preset];
    const dnsKey = dnsNow ? { system: "dnsStatusSystem", default: "dnsStatusDefault", strict: "dnsStatusStrict" }[dnsNow.choice] ?? "dnsStatusFallback" : null;
    const rows = [
      presetKey ? [t("firstrunSummaryTabs"), t(presetKey)] : null,
      dnsKey ? [t("dnsHeading"), t(dnsKey)] : null,
      [t("statusPasswords"), fact("passwords").textContent],
      defaultNow ? [t("firstrunSummaryDefault"), t(defaultNow.state === "enabled" ? "firstrunDefaultIsNulavio" : "firstrunDefaultIsOther")] : null,
    ].filter(Boolean);
    document.getElementById("firstrun-summary").replaceChildren(
      ...rows.map(([name, value]) => h("div", {}, h("dt", { text: name }), h("dd", { text: value })))
    );
  }

  document.getElementById("firstrun-start").addEventListener("click", () => advance("welcome"));
  document.getElementById("firstrun-skip").addEventListener("click", async () => {
    // "Pular": everything stays as it is now; no first-run question comes back.
    if (layoutApi && (await pending("layout"))) {
      await layoutApi.dismissChoice().catch(() => {});
    }
    if (await pending("dns")) {
      await privacy.dismissDnsChoice().catch(() => {});
    }
    await privacy.firstRunDone(["welcome", ...QUESTIONS, "finished"]).catch(() => {});
    leave();
    document.getElementById("layout-choice").hidden = true;
    document.getElementById("dns-choice").hidden = true;
    document.getElementById("search-input").focus();
  });
  document.getElementById("firstrun-passwords-choose").addEventListener("click", async event => {
    event.preventDefault();
    await record("passwords");
    location.href = event.currentTarget.href;
  });
  document.getElementById("firstrun-passwords-later").addEventListener("click", () => advance("passwords"));
  const make = document.getElementById("firstrun-default-make");
  make.addEventListener("click", async () => {
    const error = document.getElementById("firstrun-default-error");
    error.textContent = "";
    make.setAttribute("aria-busy", "true");
    try {
      await connect.setDefaultBrowser();
      await advance("default-browser");
    } catch (e) {
      error.textContent = errorText(e);
    } finally {
      make.removeAttribute("aria-busy");
    }
  });
  document.getElementById("firstrun-default-later").addEventListener("click", () => advance("default-browser"));
  document.getElementById("firstrun-finish").addEventListener("click", async () => {
    await record("finished");
    leave();
    document.getElementById("search-input").focus();
  });
  // The layout and DNS cards hide themselves once answered: then the next step comes.
  const answered = new MutationObserver(() => {
    if ((current === "layout" && document.getElementById("layout-choice").hidden)
      || (current === "dns" && document.getElementById("dns-choice").hidden)) {
      // Answered in its card: the next step takes the keyboard, even though the layout card sends it
      // to the search as it closes (QA R6-1).
      advance(null, { focus: true });
    }
  });
  for (const id of ["layout-choice", "dns-choice"]) {
    answered.observe(document.getElementById(id), { attributes: true, attributeFilter: ["hidden"] });
  }
  await advance(null);
}

// Search settings and Nulavio settings exist only where the Shell is built in (privileged API).
document.getElementById("search-settings").hidden = !browser.nulavioSearch;
document.getElementById("open-settings").hidden = !browser.nulavioSearch;

// UX6: Nulavio's keys in "Atalhos e ajuda", as the engine has them now.
async function showNulavioKeys() {
  const keys = await nulavioKeys();
  for (const row of document.querySelectorAll("#nulavio-keys li[data-command]")) {
    const shortcut = keys[row.dataset.command];
    row.hidden = !shortcut;
    row.querySelector(".keys__keys").replaceChildren(...keyElements(shortcut));
  }
}

localize();
showNulavioKeys().catch(e => console.error(e));
// UX3G N1: paint once, in the final shape. The page stays invisible (pages.css)
// until the first-run cards, the engine label and the "Você está em" line are
// known, so nothing moves after the first frame; a slow API never holds it longer than 400 ms.
const facts = Promise.allSettled([refresh(), showDns()]).then(summarise);
const layoutShown = showLayoutChoice();
const firstRunShown = Promise.allSettled([facts, layoutShown]).then(() => firstRun()).catch(e => console.error(e));
const shaped = Promise.allSettled([engineShown, facts, showHere(), layoutShown, firstRunShown]);
Promise.race([shaped, new Promise(resolve => setTimeout(resolve, 400))]).then(() => {
  document.documentElement.dataset.painted = "true";
  performance.mark("nv-painted"); // UX7: the new tab's time to its final shape (scripts/research/frame_scene.py)
});
browser.nulavioSearch?.onChanged.addListener(() => showEngine().catch(() => {}));
shaped.then(() => {
  document.documentElement.dataset.ready = "true";
});
