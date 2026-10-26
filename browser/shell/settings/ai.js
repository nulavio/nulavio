/* Settings → AI & Automation (S7, ADR 0007). Everything here is the user's
   decision about agents: which may connect, how much they may do without
   asking, on which sites, and for how long. Agents cannot reach this page;
   changes apply to an agent's next call. */

import { t } from "../lib/i18n.js";
import { announce, confirmDialog, errorText, h, rerender } from "../lib/ui.js";

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

async function acceptFullControl() {
  return confirmDialog({
    title: t("aiFullControlTitle"),
    body: state.fullControlWarning,
    confirm: t("aiFullControlConfirm"),
    danger: true,
  });
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

function agentRow(agent) {
  const badges = [
    h("span", { class: "badge badge--quiet", text: t(`aiClient_${agent.client.replace("-", "_")}`) }),
    h("span", { class: "badge", text: t(`aiLevel_${agent.autonomy}`) }),
    agent.revoked ? h("span", { class: "badge badge--quiet", text: t("aiRevoked") }) : null,
    agent.paused ? h("span", { class: "badge badge--quiet", text: t("aiPaused") }) : null,
  ];
  const seen = agent.last_client;
  const meta = [
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
    const accept = level.value === "full_control" ? await acceptFullControl() : false;
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
    onclick: () =>
      run(async () => {
        const { config } = await ai.change(agent.id, "rotate-token");
        showConfig(agent.client, config);
      }),
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
      h("ul", { class: "list" }, ...Object.keys(state.capabilities).map(c => capabilityRow(agent, c))),
      h("div", { class: "actions" }, rotate, remove)
    )
  );
}

async function renderAgents() {
  state = await ai.overview();
  const stop = document.getElementById("ai-stop");
  stop.checked = state.stopped;
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

function showConfig(client, config) {
  document.getElementById("ai-config-intro").textContent = t(`aiConfigIntro_${client.replace("-", "_")}`);
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
    details.acceptFullControl = await acceptFullControl();
    if (!details.acceptFullControl) {
      return;
    }
  }
  try {
    const { config } = await ai.add(details);
    showConfig(details.client, config);
    form.reset();
    await renderAgents();
  } catch (e) {
    error.textContent = errorText(e);
  }
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
              h("p", { class: "row__title", text: `${names[e.agent] ?? e.agent} · ${e.tool ?? t(`aiEvent_${e.event ?? "other"}`)}` }),
              h("p", { class: "row__note", text: [when(e.ts), e.target, e.decision === "deny" ? t("aiDenied", [e.reason ?? ""]) : null].filter(Boolean).join(" · ") })
            )
          )
        )
      : [h("li", { class: "popup__empty", text: t("aiNoActivity") })]
  );
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
  document.getElementById("ai-connect-form").addEventListener("submit", connect);
  document.getElementById("ai-copy").addEventListener("click", () =>
    run(() => navigator.clipboard.writeText(document.getElementById("ai-config").textContent), t("aiCopied"))
  );
  document.getElementById("ai-connect-again").addEventListener("click", () => {
    document.getElementById("ai-config").textContent = "";
    document.getElementById("ai-connect-result").hidden = true;
    document.getElementById("ai-connect-form").hidden = false;
  });
  document.getElementById("ai-activity-clear").addEventListener("click", async () => {
    if (await confirmDialog({ title: t("aiActivityClearTitle"), body: t("aiActivityClearBody"), confirm: t("aiActivityClear"), danger: true })) {
      await run(() => ai.clearActivity().then(renderActivity), t("doneRemoved"));
    }
  });
  await renderAgents();
  await renderActivity();
}
