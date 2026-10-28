/* Settings → AI & Automation (S7, ADR 0007). Everything here is the user's
   decision about agents: which may connect, how much they may do without
   asking, on which sites, and for how long. Agents cannot reach this page;
   changes apply to an agent's next call. */

import { t } from "../lib/i18n.js";
import { announce, confirmDialog, errorText, h, icon, rerender } from "../lib/ui.js";

const ai = browser.nulavioAI;
const LEVELS = ["restricted", "assisted", "autonomous", "full_control"];
const MODES = ["allow", "ask", "block"];
const DURATIONS = [
  { key: "always", minutes: null },
  { key: "30min", minutes: 30 },
  { key: "8h", minutes: 480 },
];

let state = null;

async function run(action, done = null) {
  try {
    const result = await action();
    if (done) {
      announce(done);
    }
    return result;
  } catch (e) {
    announce(errorText(e), "error");
    return null;
  }
}

// Consents that raise what an agent may do: the browser's own localised words (never text from the tools),
// the critical dialog variant, Cancel focused first.
async function acceptFullControl(name) {
  return confirmDialog({
    title: t("aiFullControlTitle", [name]),
    body: t("aiFullControlBody", [name]),
    confirm: t("aiFullControlConfirm"),
    danger: true,
    critical: true,
  });
}

async function acceptRawAutomation(name) {
  return confirmDialog({
    title: t("aiRawTitle", [name]),
    body: t("aiRawBody", [name]),
    confirm: t("aiRawConfirm"),
    danger: true,
    critical: true,
  });
}

/** A localised name for an id from the tools (tool, event, client), or the id itself: never a raw locale key. */
function named(prefix, id) {
  return (id && browser.i18n.getMessage(`${prefix}${String(id).replace(/[^a-z0-9_]/gi, "_")}`)) || String(id ?? "");
}

function rawCapability() {
  return state?.rawCapability ?? "debugging";
}

function when(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

function capabilityRow(agent, capability) {
  const grant = agent.grants?.[capability];
  const select = h(
    "select",
    { class: "select", "aria-label": t(`aiCap_${capability}`), "data-focus-key": `mode-${agent.id}-${capability}` },
    ...MODES.map(mode => h("option", { value: mode, text: t(`aiMode_${mode}`), selected: agent.modes[capability] === mode }))
  );
  const duration = h(
    "select",
    { class: "select", "aria-label": t("aiDurationLabel") },
    ...DURATIONS.map(d => h("option", { value: d.key, text: t(`aiDuration_${d.key}`) }))
  );
  select.addEventListener("change", () =>
    run(async () => {
      const minutes = DURATIONS.find(d => d.key === duration.value)?.minutes;
      await ai.change(agent.id, "grant", { capability, mode: select.value, minutes });
      await renderAgents();
    }, t("doneSaved"))
  );
  const meta = grant
    ? grant.until
      ? t("aiGrantUntil", [when(grant.until)])
      : grant.session
        ? t("aiGrantSession")
        : t("aiGrantSet")
    : t("aiGrantFromLevel");
  const reset = grant
    ? h("button", {
        class: "button button--quiet",
        type: "button",
        text: t("aiGrantReset"),
        onclick: () => run(() => ai.change(agent.id, "clear-grant", { capability }).then(renderAgents), t("doneSaved")),
      })
    : null;
  return h(
    "li",
    { class: "row row--plain" },
    h("div", { class: "row__main" }, h("p", { class: "row__title", text: t(`aiCap_${capability}`) }), h("p", { class: "row__note", text: meta })),
    h("div", { class: "row__end" }, select, duration, reset)
  );
}

/* Raw automation: not part of any level; a separate switch per agent with its own critical confirmation.
   Off again needs no confirmation; on again shows the warning again. */
function rawAutomationRow(agent) {
  const on = Boolean(agent.raw_automation_accepted);
  const input = h("input", { type: "checkbox", role: "switch", checked: on, "data-focus-key": `raw-${agent.id}` });
  input.addEventListener("change", async () => {
    const enabled = input.checked;
    if (enabled && !(await acceptRawAutomation(agent.name))) {
      input.checked = false;
      return;
    }
    await run(() => ai.change(agent.id, "raw-automation", { enabled, acceptRawAutomation: enabled }).then(renderAgents), t("doneSaved"));
  });
  return h(
    "label",
    { class: "check check--switch", dataset: { rawAutomation: agent.id } },
    input,
    h(
      "span",
      {},
      h("span", { text: t("aiRawLabel") }),
      h("span", { class: "hint", text: on ? t("aiRawHintOn", [when(agent.raw_automation_accepted)]) : t("aiRawHintOff") })
    )
  );
}

/* The level in words ("Nível: Controle total"), with the security-state badge family: Controle total has
   a warning tint and icon, Autônomo a warning outline; the other two stay plain. */
function levelBadge(level) {
  const text = t("aiLevelBadge", [t(`aiLevel_${level}`)]);
  if (level === "full_control") {
    return h("span", { class: "badge badge--warning", dataset: { level } }, icon("warning", "badge__icon"), text);
  }
  return h("span", { class: level === "autonomous" ? "badge badge--outline" : "badge", dataset: { level }, text });
}

function stateBadge(kind, text) {
  return h("span", { class: "badge badge--quiet", dataset: { state: kind } }, icon(kind === "paused" ? "pause" : "revoked", "badge__icon"), text);
}

let groupProfiles = [];

function profilesEditor(agent) {
  const allowed = new Map((agent.profiles ?? []).map(p => [p.path, p.label]));
  const boxes = groupProfiles.map(profile => {
    const box = h("input", { type: "checkbox", value: profile.path, checked: allowed.has(profile.path), dataset: { label: profile.name } });
    return h("label", { class: "check" }, box, h("span", { text: profile.name }));
  });
  const save = h("button", { class: "button button--secondary", type: "button", text: t("profilesSave"), "data-focus-key": `profiles-save-${agent.id}` });
  save.addEventListener("click", () => {
    const chosen = boxes.map(b => b.querySelector("input")).filter(i => i.checked).map(i => ({ label: i.dataset.label, path: i.value }));
    run(() => ai.change(agent.id, "profiles", { profiles: chosen }).then(renderAgents), t("doneSaved"));
  });
  const routes = (agent.routes ?? []).map(route => {
    const others = agent.routes.filter(r => r !== route);
    const remove = h("button", {
      class: "button button--quiet",
      type: "button",
      text: t("aiRouteRemove"),
      onclick: () => run(() => ai.change(agent.id, "routes", { routes: others }).then(renderAgents), t("doneSaved")),
    });
    return h(
      "li",
      { class: "row row--plain" },
      h("div", { class: "row__main" }, h("p", { class: "row__title", text: t("aiRouteText", [route.site, route.profile]) })),
      h("div", { class: "row__end" }, remove)
    );
  });
  const site = h("input", { class: "input", placeholder: "localhost, dev.example.org", "aria-label": t("aiRouteSite"), "data-focus-key": `route-site-${agent.id}` });
  const target = h(
    "select",
    { class: "select", "aria-label": t("aiRouteProfile"), "data-focus-key": `route-profile-${agent.id}` },
    ...(agent.profiles ?? []).map(p => h("option", { value: p.label, text: p.label }))
  );
  const addRoute = h(
    "form",
    { class: "inline-form", novalidate: true },
    site,
    target,
    h("button", { class: "button button--secondary", type: "submit", text: t("aiRouteAdd"), "data-focus-key": `route-add-${agent.id}` })
  );
  addRoute.addEventListener("submit", event => {
    event.preventDefault();
    const next = [...(agent.routes ?? []), { site: site.value.trim(), profile: target.value }];
    run(() => ai.change(agent.id, "routes", { routes: next }).then(renderAgents), t("doneSaved"));
  });
  return h(
    "div",
    { class: "stack stack--tight" },
    h("p", { class: "subhead", text: t("aiProfilesLabel") }),
    h("p", { class: "hint", text: t("aiProfilesHint") }),
    boxes.length ? h("div", { class: "actions" }, ...boxes, save) : h("p", { class: "hint", text: t("aiNoProfiles") }),
    h("p", { class: "subhead", text: t("aiRoutesLabel") }),
    routes.length ? h("ul", { class: "list" }, ...routes) : h("p", { class: "hint", text: t("aiNoRoutes") }),
    agent.profiles?.length ? addRoute : null
  );
}

function agentRow(agent) {
  const badges = [
    h("span", { class: "badge badge--quiet", text: named("aiClient_", agent.client) }),
    levelBadge(agent.autonomy),
    agent.revoked ? stateBadge("revoked", t("aiRevoked")) : null,
    agent.paused ? stateBadge("paused", t("aiPaused")) : null,
  ];
  const seen = agent.last_client;
  const meta = [
    agent.active_sessions?.length ? t("aiConnectedNow", [String(agent.active_sessions.length)]) : null,
    seen ? t("aiLastSeen", [when(seen.seen), seen.executable ?? "?"]) : t("aiNeverConnected"),
    seen && seen.matches === false ? t("aiClientMismatch") : null,
    agent.domains?.length ? t("aiSitesOnly", [agent.domains.join(", ")]) : t("aiAnySite"),
  ].filter(Boolean);

  const level = h(
    "select",
    { class: "select", "aria-label": t("aiAutonomyLabel"), "data-focus-key": `level-${agent.id}` },
    ...LEVELS.map(l => h("option", { value: l, text: t(`aiLevel_${l}`), selected: agent.autonomy === l }))
  );
  level.addEventListener("change", async () => {
    const accept = level.value === "full_control" ? await acceptFullControl(agent.name) : false;
    if (level.value === "full_control" && !accept) {
      level.value = agent.autonomy;
      return;
    }
    await run(() => ai.change(agent.id, "autonomy", { level: level.value, acceptFullControl: accept }).then(renderAgents), t("doneSaved"));
  });
  const sites = h("input", { class: "input", value: (agent.domains ?? []).join(", "), placeholder: "example.org, docs.example.org" });
  const sitesForm = h(
    "form",
    { class: "inline-form", novalidate: true },
    h("label", { class: "field" }, h("span", { class: "field__label", text: t("aiSitesLabel") }), sites),
    h("button", { class: "button button--secondary", type: "submit", text: t("profilesSave") })
  );
  sitesForm.addEventListener("submit", event => {
    event.preventDefault();
    const domains = sites.value.split(/[\s,]+/).filter(Boolean);
    run(() => ai.change(agent.id, "domains", { domains }).then(renderAgents), t("doneSaved"));
  });

  const pause = h("button", {
    class: "button button--secondary",
    type: "button",
    text: agent.paused ? t("aiResume") : t("aiPause"),
    "data-focus-key": `pause-${agent.id}`,
    onclick: () => run(() => ai.change(agent.id, "pause", { paused: !agent.paused }).then(renderAgents)),
  });
  const revoke = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("aiRevoke"),
    hidden: Boolean(agent.revoked),
    onclick: async () => {
      if (await confirmDialog({ title: t("aiRevokeTitle", [agent.name]), body: t("aiRevokeBody"), confirm: t("aiRevoke"), danger: true })) {
        await run(() => ai.change(agent.id, "revoke").then(renderAgents), t("aiRevokedNow", [agent.name]));
      }
    },
  });
  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("aiRemove"),
    onclick: async () => {
      if (await confirmDialog({ title: t("aiRemoveTitle", [agent.name]), body: t("aiRemoveBody"), confirm: t("aiRemove"), danger: true })) {
        await run(() => ai.change(agent.id, "remove").then(renderAgents), t("doneRemoved"));
      }
    },
  });
  const rotate = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("aiNewToken"),
    onclick: () => run(() => ai.change(agent.id, "rotate-token"), t("aiKeyReplaced", [agent.name])),
  });

  return h(
    "li",
    { class: "row row--plain row--agent", dataset: { agentId: agent.id } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title" }, h("span", { text: agent.name }), ...badges),
      ...meta.map(text => h("p", { class: "row__note", text }))
    ),
    h("div", { class: "row__end" }, pause, revoke),
    h(
      "details",
      { class: "more", "data-open-key": `agent-${agent.id}` },
      h("summary", { text: t("aiPermissions") }),
      h(
        "div",
        { class: "stack stack--tight" },
        h("label", { class: "field" }, h("span", { class: "field__label", text: t("aiAutonomyLabel") }), level),
        sitesForm
      ),
      profilesEditor(agent),
      h(
        "ul",
        { class: "list" },
        ...Object.keys(state.capabilities)
          .filter(c => c !== rawCapability())
          .map(c => capabilityRow(agent, c))
      ),
      agent.client === "nulavio-assistant" ? null : rawAutomationRow(agent),
      h("div", { class: "actions" }, rotate, remove)
    )
  );
}

let renders = 0;

async function renderAgents() {
  // The latest call wins: an older answer that arrives late (the stop switch toggled twice quickly)
  // must not put back a state that is no longer true.
  const turn = ++renders;
  const next = await ai.overview();
  const profiles = browser.nulavioProfiles ? (await browser.nulavioProfiles.list()).profiles.filter(p => p.path) : [];
  if (turn !== renders) {
    return;
  }
  state = next;
  groupProfiles = profiles;
  const stop = document.getElementById("ai-stop");
  stop.checked = state.stopped;
  // While every agent is stopped, a persistent warning at the top of the section says so, with a way back.
  document.getElementById("ai-stopped").hidden = !state.stopped;
  rerender(document.getElementById("ai-agents"), () =>
    state.agents.length ? state.agents.map(agentRow) : [h("li", { class: "popup__empty", text: t("aiNoAgents") })]
  );
}

function renderLevels() {
  document.getElementById("ai-levels").replaceChildren(
    ...LEVELS.map(level =>
      h(
        "label",
        { class: "check" },
        h("input", { type: "radio", name: "autonomy", value: level, checked: level === "restricted" }),
        h("span", {}, h("strong", { text: t(`aiLevel_${level}`) }), h("span", { class: "hint", text: t(`aiLevelHint_${level}`) }))
      )
    )
  );
}

async function offerWizard(agent, config) {
  const form = document.getElementById("ai-connect-form");
  if (agent.client === "other") {
    showConfig(agent.client, config);
    return;
  }
  const { clients } = await ai.detect();
  const found = clients.find(c => c.client === agent.client);
  if (!found?.path) {
    showConfig(agent.client, config, t("aiNotDetected", [found?.label ?? agent.client]));
    return;
  }
  const plan = await ai.plan(agent.id, agent.client);
  document.getElementById("ai-wizard-detected").textContent = t("aiDetected", [found.label, found.version ?? ""]);
  document.getElementById("ai-wizard-intro").textContent = t("aiWizardIntro", [found.label, plan.target]);
  document.getElementById("ai-wizard-command").textContent = plan.display;
  const existing = document.getElementById("ai-wizard-existing");
  existing.hidden = !plan.existing;
  existing.textContent = t("aiReplaceExisting", [found.label]);
  const install = document.getElementById("ai-wizard-install");
  install.textContent = t("aiInstall", [found.label]);
  install.onclick = () =>
    run(async () => {
      install.disabled = true;
      try {
        const result = await ai.install(agent.id, agent.client, plan.existing);
        const state = result.check.connected ? "connected" : result.check.configured ? "configured" : "missing";
        document.getElementById("ai-wizard").hidden = true;
        showConfig(agent.client, config, t(`aiInstalled_${state}`, [found.label]));
      } finally {
        install.disabled = false;
      }
    });
  document.getElementById("ai-wizard-manual").onclick = () => {
    document.getElementById("ai-wizard").hidden = true;
    showConfig(agent.client, config);
  };
  form.hidden = true;
  document.getElementById("ai-wizard").hidden = false;
  install.focus();
}

function showConfig(client, config, note = null) {
  document.getElementById("ai-config-intro").textContent = [note, t(`aiConfigIntro_${client.replace("-", "_")}`)].filter(Boolean).join(" ");
  document.getElementById("ai-config").textContent = config;
  document.getElementById("ai-connect-form").hidden = true;
  document.getElementById("ai-connect-result").hidden = false;
  document.getElementById("ai-copy").focus();
}

async function connect(event) {
  event.preventDefault();
  const form = event.target;
  const error = form.querySelector(".form-error");
  error.textContent = "";
  const data = new FormData(form);
  const details = {
    name: String(data.get("name") ?? "").trim(),
    client: String(data.get("client")),
    autonomy: String(data.get("autonomy")),
    disposable: data.get("disposable") === "on",
  };
  if (!details.name) {
    error.textContent = t("err_invalid_name");
    form.elements.name.focus();
    return;
  }
  if (details.autonomy === "full_control") {
    details.acceptFullControl = await acceptFullControl(details.name);
    if (!details.acceptFullControl) {
      return;
    }
  }
  try {
    const { agent, config } = await ai.add(details);
    form.reset();
    await renderAgents();
    await offerWizard(agent, config);
  } catch (e) {
    error.textContent = errorText(e);
  }
}

/** What an activity line did, in words: events (connected, raw automation ended) and tools by their title. */
function activityTitle(entry) {
  if (entry.event) {
    return named("aiEvent_", entry.event);
  }
  return entry.tool ? named("aiTool_", entry.tool) : t("aiEvent_other");
}

async function renderActivity() {
  const { entries } = await ai.activity(30);
  const names = Object.fromEntries((state?.agents ?? []).map(a => [a.id, a.name]));
  rerender(document.getElementById("ai-activity"), () =>
    entries.length
      ? entries.reverse().map(e =>
          h(
            "li",
            { class: "row row--plain" },
            h(
              "div",
              { class: "row__main" },
              h("p", { class: "row__title", text: `${names[e.agent] ?? e.agent} · ${activityTitle(e)}` }),
              h("p", { class: "row__note", text: [when(e.ts), e.target, e.decision === "deny" ? t("aiDenied", [e.reason ?? ""]) : null].filter(Boolean).join(" · ") })
            )
          )
        )
      : [h("li", { class: "popup__empty", text: t("aiNoActivity") })]
  );
}

// -- Nulavio Assistant (A12) -----------------------------------------------------------

async function renderAssistant() {
  const form = document.getElementById("ai-assistant");
  const state = await ai.assistantState().catch(e => (announce(errorText(e), "error"), null));
  if (!state) {
    return;
  }
  const status = document.getElementById("ai-assistant-state");
  status.textContent = state.configured
    ? t("assistantStateConfigured", [state.provider.model, state.recipient, t(state.hasKey ? "assistantKeyStored" : "assistantKeyNone")])
    : t("assistantStateNone");
  if (state.configured) {
    form.elements.kind.value = state.provider.kind;
    form.elements.model.value = state.provider.model;
    form.elements.baseUrl.value = state.provider.base_url;
  }
  form.elements.allowed.checked = state.profileAllowed;
  document.getElementById("ai-assistant-allowed-hint").textContent = t("assistantAllowHint", [state.recipient ?? t("assistantRecipientUnknown")]);
  document.getElementById("ai-assistant-forget").hidden = !state.configured;
  form.dataset.configured = String(state.configured);
}

function setUpAssistant() {
  const form = document.getElementById("ai-assistant");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    error.textContent = "";
    const details = { kind: form.elements.kind.value, baseUrl: form.elements.baseUrl.value.trim(), model: form.elements.model.value.trim() };
    if (form.elements.key.value) {
      details.key = form.elements.key.value; // to the system keyring through the Nulavio tools; never stored here
    }
    try {
      await ai.assistantConfigure(details);
      await ai.assistantAllow(form.elements.allowed.checked);
      form.elements.key.value = "";
      announce(t("assistantSaved"));
      await renderAssistant();
      await renderAgents(); // the assistant is an agent too: it appears in the list at once
    } catch (e) {
      error.textContent = errorText(e);
    }
  });
  document.getElementById("ai-assistant-forget").addEventListener("click", async () => {
    if (await confirmDialog({ title: t("assistantForgetTitle"), body: t("assistantForgetBody"), confirm: t("assistantForget"), danger: true })) {
      await ai.assistantForget().then(renderAssistant, e => announce(errorText(e), "error"));
    }
  });
  return renderAssistant();
}

export async function setUpAI() {
  if (await ai.workspaceAgent()) {
    return; // an agent drives this window: its settings are managed from the user's own window
  }
  document.getElementById("ai").hidden = false;
  renderLevels();
  document.getElementById("ai-stop").addEventListener("change", event =>
    run(() => ai.setStopped(event.target.checked).then(renderAgents), event.target.checked ? t("aiStoppedNow") : t("aiResumedNow"))
  );
  document.getElementById("ai-stopped").prepend(icon("warning", "callout__icon"));
  document.getElementById("ai-resume").addEventListener("click", () =>
    run(() => ai.setStopped(false).then(renderAgents), t("aiResumedNow"))
  );
  document.getElementById("ai-connect-form").addEventListener("submit", connect);
  document.getElementById("ai-copy").addEventListener("click", () =>
    run(() => navigator.clipboard.writeText(document.getElementById("ai-config").textContent), t("aiCopied"))
  );
  document.getElementById("ai-connect-again").addEventListener("click", () => {
    document.getElementById("ai-config").textContent = "";
    document.getElementById("ai-connect-result").hidden = true;
    document.getElementById("ai-wizard").hidden = true;
    document.getElementById("ai-connect-form").hidden = false;
  });
  document.getElementById("ai-activity-clear").addEventListener("click", async () => {
    if (await confirmDialog({ title: t("aiActivityClearTitle"), body: t("aiActivityClearBody"), confirm: t("aiActivityClear"), danger: true })) {
      await run(() => ai.clearActivity().then(renderActivity), t("doneRemoved"));
    }
  });
  await renderAgents();
  await renderActivity();
  await setUpAssistant();
}
