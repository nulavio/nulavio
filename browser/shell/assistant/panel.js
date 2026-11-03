/* Nulavio Assistant panel (A12). The question goes to the model the user chose; a page's text only
   when the user included that page in this message. Consent is per message and bound to one tab
   (AI-02): including captures {tabId, url, title}, the item shows that binding, and it leaves the
   message after every Send or Summarise, or when that tab goes elsewhere or another tab is selected.
   Off in private windows (D-UX6) and while the emergency stop is on or the assistant's agent is
   paused or revoked (D-UX5). Tasks run in the assistant's Área de IA under the permissions the user
   gave it. Answers are shown as plain text. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText, h } from "../lib/ui.js";

const ai = browser.nulavioAI;
let state = null;
let windowId = null; // the browser window this panel lives in
let current = null; // what "Incluir esta página" would include now: {tabId, url, title}
let attached = null; // the page included in the next message, captured when the user included it
let busy = false;
let contextVersion = 0; // late page replies cannot restore consent after a send or context change

const $ = id => document.getElementById(id);
const hostOf = url => URL.parse(url)?.host || url;
const count = n => new Intl.NumberFormat(browser.i18n.getUILanguage()).format(n);
const code = error => String(error?.message ?? error);

// Refusals that come before anything is sent or done (so "Nada foi alterado" style texts hold).
const BEFORE_START = new Set([
  "not-configured",
  "profile-not-allowed",
  "emergency-stop",
  "assistant-paused",
  "assistant-revoked",
  "ai-workspace",
  "private-window",
  "no-window",
  "page-changed",
  "bad-question",
  "bad-request",
  "tools-missing",
]);
// Refusals that mean the panel itself should show another state.
const STATE_CHANGED = new Set(["emergency-stop", "assistant-paused", "assistant-revoked", "private-window", "profile-not-allowed", "not-configured"]);

const BLOCKED = {
  "emergency-stop": () => [t("assistantStoppedTitle"), t("assistantStoppedText"), "settings/settings.html#ai-agents-card"],
  "assistant-paused": () => [t("assistantPausedTitle"), t("assistantPausedText"), "settings/settings.html#ai-agents-card"],
  "assistant-revoked": () => [t("assistantRevokedTitle"), t("err_assistant_revoked"), "settings/settings.html#ai-assistant"],
};

function mode() {
  return $("ask").elements.mode.value;
}

/** The included item, the offer to include the current page, and the reason one left. */
function showContext() {
  const task = mode() === "task";
  $("context").hidden = task;
  $("attached").hidden = !attached;
  if (attached) {
    $("attached-heading").textContent = t("assistantAttachedHeading", [state.recipient]);
    $("attached-binding").textContent = t("assistantAttachedBinding", [attached.title, hostOf(attached.url)]);
    $("remove-page").setAttribute("aria-label", t("assistantRemovePage", [attached.title]));
  }
  const offer = !attached && current;
  $("include-page").hidden = !offer;
  if (offer) {
    $("include-page").replaceChildren(h("span", { "aria-hidden": "true", text: "+" }), " ", t("assistantIncludePage", [current.title]));
  }
  $("no-page").hidden = Boolean(attached || current);
  $("summarize").hidden = task || !current;
}

/** The included page leaves the message, and the panel says why (`key` names the reason). */
function drop(key) {
  if (!attached) {
    return;
  }
  $("drift-text").textContent = t(key, [attached.title]);
  $("drift").hidden = false;
  attached = null;
}

/** Re-read this window's selected tab. `changedTab`: the tab an update or removal was about. */
async function refreshPage(changedTab = null) {
  const version = ++contextVersion;
  const page = await ai.assistantPage().catch(() => null);
  if (version !== contextVersion) {
    return;
  }
  if (attached) {
    const sameTab = page?.tabId === attached.tabId;
    if (!sameTab && changedTab !== attached.tabId) {
      drop("assistantDriftTab"); // another tab is selected now
    } else if (!sameTab || page.url !== attached.url) {
      drop("assistantDriftGone"); // that tab went to another address, or closed
    }
  }
  current = page;
  showContext();
}

function syncMode() {
  const task = mode() === "task";
  $("task-note").hidden = !task;
  $("prompt-label").textContent = t(task ? "assistantTaskLabel" : "assistantQuestion");
  const level = state?.agent?.autonomy ?? "restricted";
  $("task-note").textContent = t("assistantTaskNote", [t(`aiLevel_${level.replace("-", "_")}`) || level]);
  showContext();
}

async function render() {
  state = await ai.assistantState();
  const view = state.privateWindow
    ? "private"
    : !state.configured
      ? "not-configured"
      : !state.profileAllowed
        ? "not-allowed"
        : state.blocked
          ? "blocked"
          : "ready";
  document.body.dataset.state = view;
  $("private").hidden = view !== "private";
  $("blocked").hidden = view !== "blocked";
  $("setup").hidden = view !== "not-configured" && view !== "not-allowed";
  $("ask").hidden = view !== "ready";
  $("allow-profile").hidden = view !== "not-allowed";
  $("setup-text").textContent = view === "not-configured" ? t("assistantNotConfigured") : t("assistantProfileNotAllowed", [state.recipient]);
  if (view === "blocked") {
    const [title, text, page] = (BLOCKED[state.blocked] ?? BLOCKED["assistant-paused"])();
    $("blocked-title").textContent = title;
    $("blocked-text").textContent = text;
    $("resume-settings").dataset.page = page;
  }
  $("footer").hidden = view === "private" || !state.configured;
  if (state.configured) {
    $("footer").textContent = t("assistantFooter", [state.provider.model, state.recipient]);
  }
  if (view === "ready") {
    await refreshPage();
    syncMode();
  } else {
    ++contextVersion;
    attached = null;
  }
}

function showSteps(steps) {
  $("steps").replaceChildren(
    ...(steps ?? []).map(s => h("li", { text: `${s.tool}${s.error ? ` — ${t("assistantStepFailed")}` : ""}` }))
  );
  $("steps").hidden = !steps?.length;
}

function showResult(result, task) {
  const halted = task && result.stopped;
  const text = result.answer || (halted ? "" : t("assistantNoAnswer"));
  $("answer").textContent = text;
  $("answer").hidden = !text;
  $("receipt").textContent = task
    ? t("assistantSentTask", [result.recipient ?? state.recipient])
    : result.pageChars
      ? t("assistantSentPage", [count(result.pageChars), result.recipient])
      : t("assistantSentQuestionOnly", [result.recipient]);
  showSteps(result.steps);
  $("answer-section").hidden = false;
  if (halted) {
    const why = result.stopped === "step-limit" ? t("assistantStoppedStepLimit", [count(result.limit ?? 8)]) : errorText(result.stopped);
    $("activity-actions").hidden = false;
    announce(result.steps?.length ? `${why} ${t("assistantTaskMayHaveActed")}` : why, "error");
  } else {
    announce(t("assistantAnswerReady"));
  }
  document.body.dataset.answered = "true";
}

async function showError(error, task) {
  const reason = code(error);
  let text = errorText(error);
  if (task && !BEFORE_START.has(reason)) {
    // The run may have acted before it ended (a time limit, the tools ending, the provider failing):
    // never "nothing was changed" here.
    text = reason.startsWith("provider-") ? `${text} ${t("assistantTaskMayHaveActed")}` : errorText("task-unfinished");
    $("activity-actions").hidden = false;
  }
  announce(text, "error");
  if (STATE_CHANGED.has(reason)) {
    await render().catch(() => {});
  } else if (reason === "page-changed") {
    await refreshPage();
  }
}

async function send(question, page) {
  const task = mode() === "task";
  busy = true;
  ++contextVersion;
  // Consent is per message: what was included goes with this one only.
  attached = null;
  $("drift").hidden = true;
  showContext();
  $("answer-section").hidden = true;
  $("activity-actions").hidden = true;
  delete document.body.dataset.answered;
  $("send").disabled = true;
  $("summarize").disabled = true;
  $("include-page").disabled = true;
  // One polite announcement now, one when it ends (AI-12); no check mark until then.
  announce(t(task ? "assistantWorking" : "assistantAsking", [state.recipient]), "progress");
  try {
    const result = task
      ? await ai.assistantTask(question)
      : await ai.assistantAsk(question, page ? { tabId: page.tabId, url: page.url } : null);
    showResult(result, task);
  } catch (e) {
    await showError(e, task);
  } finally {
    busy = false;
    $("send").disabled = false;
    $("summarize").disabled = false;
    $("include-page").disabled = false;
  }
}

$("ask").addEventListener("submit", event => {
  event.preventDefault();
  const question = $("prompt").value.trim();
  if (question && !busy) {
    send(question, mode() === "ask" ? attached : null);
  }
});
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault();
    $("ask").requestSubmit();
  }
});
$("ask").addEventListener("change", event => {
  if (event.target.name === "mode") {
    ++contextVersion;
    syncMode();
  }
});
$("include-page").addEventListener("click", async () => {
  if (busy) {
    return;
  }
  const version = ++contextVersion;
  const page = await ai.assistantPage().catch(() => null); // what the tab shows at this moment
  if (version !== contextVersion || document.body.dataset.state !== "ready") {
    return;
  }
  if (page) {
    attached = page;
    $("drift").hidden = true;
  }
  current = page;
  showContext();
  $("prompt").focus(); // the offer button is gone either way; the question comes next
});
$("remove-page").addEventListener("click", () => {
  ++contextVersion;
  attached = null;
  showContext();
  $("include-page").focus();
});
$("summarize").addEventListener("click", async () => {
  if (busy) {
    return;
  }
  const version = ++contextVersion;
  const question = t("assistantSummarizePrompt");
  $("prompt").value = question;
  const page = await ai.assistantPage().catch(() => null); // this explicit action includes the page shown now
  if (version !== contextVersion || document.body.dataset.state !== "ready") {
    return;
  }
  if (!page) {
    refreshPage();
    return;
  }
  send(question, page);
});
const openShell = page => browser.tabs.create({ url: browser.runtime.getURL(page) });
$("open-settings").addEventListener("click", () => openShell("settings/settings.html#ai-assistant"));
$("resume-settings").addEventListener("click", event => openShell(event.currentTarget.dataset.page));
$("open-activity").addEventListener("click", () => openShell("settings/settings.html#ai-activity-card"));
$("allow-profile").addEventListener("click", () => ai.assistantAllow(true).then(render, e => announce(errorText(e), "error")));

// While blocked (paused, emergency stop), the panel checks again whether it was resumed in
// Settings when the person comes back to it. Each check runs the Nulavio tools (and a
// keyring lookup), so tab switches and focus changes share one check every few seconds,
// with a final one at the end of a burst; the tools still refuse while blocked.
const BLOCKED_RECHECK_MS = 3000;
let rendering = null;
let lastBlockedCheck = 0;
let blockedTimer = null;
function renderShared() {
  rendering ??= render().finally(() => {
    rendering = null;
  });
  return rendering;
}
function recheckBlocked() {
  if (blockedTimer) {
    return;
  }
  const wait = Math.max(0, lastBlockedCheck + BLOCKED_RECHECK_MS - Date.now());
  blockedTimer = setTimeout(() => {
    blockedTimer = null;
    lastBlockedCheck = Date.now();
    if (document.body.dataset.state === "blocked") {
      renderShared().catch(() => {});
    }
  }, wait);
}

browser.tabs.onActivated.addListener(info => {
  if (!state || (windowId !== null && info.windowId !== windowId)) {
    return;
  }
  if (document.body.dataset.state === "blocked") {
    recheckBlocked(); // resumed in Settings?
  } else if (document.body.dataset.state === "ready") {
    refreshPage();
  }
});
browser.tabs.onUpdated.addListener((tabId, _info, tab) => {
  // Without the "tabs" permission the event carries no address or title, but it does say which tab
  // is selected where: re-read for the included tab and for this window's selected tab.
  const here = tab?.active && (windowId === null || tab.windowId === windowId);
  if (document.body.dataset.state === "ready" && (tabId === attached?.tabId || here)) {
    refreshPage(tabId);
  }
});
browser.tabs.onRemoved.addListener(tabId => {
  if (document.body.dataset.state === "ready" && tabId === attached?.tabId) {
    refreshPage(tabId);
  }
});
window.addEventListener("focus", () => {
  if (document.body.dataset.state === "blocked") {
    recheckBlocked();
  }
});

localize();
browser.windows
  .getCurrent()
  .then(win => (windowId = win.id))
  .catch(() => {})
  .then(render)
  .catch(e => announce(errorText(e), "error"))
  .finally(() => (document.documentElement.dataset.ready = "true"));
