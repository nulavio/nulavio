/* "Agent permission request" (S7, UX1): an agent asked for something its
   settings say to ask about. The page names the agent and its level, what it
   wants, how risky that is (critical / warning / info, with an icon and words),
   where it acts (its AI Workspace or one of the user's profiles), and when
   silence becomes a no. Deny is the filled primary, first and focused; the
   answer applies once or until the agent disconnects, or refuses. It is never
   shown in an AI Workspace, which the agent itself drives. States on
   <body data-state>: loading, asking, answered, expired, error. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText, icon } from "../lib/ui.js";

const ai = browser.nulavioAI;
const id = new URLSearchParams(location.search).get("id") ?? "";
const byId = name => document.getElementById(name);
const TIERS = new Set(["critical", "warning", "info"]);

function setState(state, message = "", level = "ok") {
  document.body.dataset.state = state;
  announce(message, level);
}

async function closeSoon() {
  const tab = await browser.tabs.getCurrent();
  const siblings = await browser.tabs.query({ windowId: tab.windowId });
  setTimeout(() => (siblings.length > 1 ? browser.tabs.remove(tab.id) : browser.tabs.update(tab.id, { url: "about:newtab" })), 1200);
}

function expired() {
  for (const button of document.querySelectorAll("#actions button")) {
    button.hidden = true;
  }
  byId("expires").hidden = true;
  byId("only-if").hidden = true; // advice for a decision that is no longer asked
  setState("expired", t("aiRequestExpired"), "warn");
}

// The two answers that allow work only after the page has been visible for a moment, so keys
// meant for another tab (Tab, then Enter, as the page opened in front) cannot approve (audit A5).
const ARM_MS = 1500;
let armTimer = null;

function setAllowArmed(armed) {
  for (const name of ["once", "session"]) {
    byId(name).disabled = !armed;
  }
}

function armAllow() {
  clearTimeout(armTimer);
  setAllowArmed(false);
  if (document.visibilityState === "visible" && document.body.dataset.state === "asking") {
    armTimer = setTimeout(() => setAllowArmed(true), ARM_MS);
  }
}

async function answer(value) {
  if (value !== "deny" && byId(value)?.disabled) {
    return; // not armed yet
  }
  clearTimeout(armTimer);
  document.removeEventListener("visibilitychange", armAllow);
  for (const button of document.querySelectorAll("#actions button")) {
    button.disabled = true;
  }
  try {
    await ai.answer(id, value);
    setState("answered", t(value === "deny" ? "aiAnsweredDeny" : value === "session" ? "aiAnsweredSession" : "aiAnsweredOnce"));
    await closeSoon();
  } catch (e) {
    const expired = e?.message === "invalid"; // answered elsewhere or timed out: a warning, not a failure
    setState(expired ? "expired" : "error", expired ? t("aiRequestExpired") : errorText(e), expired ? "warn" : "error");
  }
}

function showRisk(tier) {
  // An unknown tier is shown as the highest one: the page never understates a request.
  const level = TIERS.has(tier) ? tier : "critical";
  const risk = byId("risk");
  risk.classList.add(`callout--${level}`);
  risk.dataset.risk = level;
  risk.prepend(icon(level, "callout__icon"));
  byId("risk-text").textContent = t(`aiRisk_${level}`);
  risk.hidden = false;
}

function showExpiry(iso) {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return;
  }
  const time = at.toLocaleTimeString(browser.i18n.getUILanguage(), { hour: "2-digit", minute: "2-digit" });
  byId("expires").textContent = t("aiRequestExpires", [time]);
  byId("expires").hidden = false;
  // The bridge gives up at that moment and counts it as a no; say so here too.
  setTimeout(() => document.body.dataset.state === "asking" && expired(), Math.max(0, at.getTime() - Date.now()));
}

async function render() {
  const request = await ai.request(id);
  byId("who").textContent = t("aiRequestFrom", [request.agent, t(`aiLevel_${request.autonomy}`)]);
  byId("headline").textContent = t("aiRequestWants", [request.agent, t(`aiCap_${request.capability}`)]);
  showRisk(request.risk);
  if (request.target) {
    byId("target").textContent = request.target;
    byId("target").hidden = false;
  }
  const place = request.place ?? { kind: "workspace" };
  byId("where").textContent =
    place.kind === "profile" ? t("aiRequestWhereProfile", [String(place.profile ?? "")]) : t("aiRequestWhereWorkspace", [request.agent]);
  byId("once").addEventListener("click", () => answer("once"));
  byId("session").addEventListener("click", () => answer("session"));
  byId("deny").addEventListener("click", () => answer("deny"));
  setState("asking");
  armAllow();
  document.addEventListener("visibilitychange", armAllow);
  if (request.expires) {
    showExpiry(request.expires);
  }
  byId("deny").focus(); // the safe answer is the default for the keyboard
}

localize();
render()
  .catch(e => {
    if (e?.message === "expired") {
      byId("headline").textContent = t("aiRequestTitle");
      expired();
    } else {
      // No request was read: the page names itself and leaves no answer to press, since none
      // would do anything (audit 2026-11 S-01).
      byId("headline").textContent = t("aiRequestTitle");
      for (const button of document.querySelectorAll("#actions button")) {
        button.hidden = true;
      }
      for (const name of ["who", "where", "only-if"]) {
        byId(name).hidden = true;
      }
      setState("error", errorText(e), "error");
    }
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
