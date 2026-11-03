/* Nulavio Assistant panel (A12). The question goes to the model the user chose; a page's text only
   when the user included that page in this message. Consent is per message and bound to one tab
   (AI-02): "Incluir" reads that tab's text at once and keeps it in the browser (UX5-B, Q4), the item
   shows the tab, its size and whether it was cut, and it leaves the message after every Send, or when
   that tab goes elsewhere or another tab is selected. The line above Send says where the message goes
   and its whole size; the tools refuse it if either changed. Off in private windows (D-UX6) and while
   the emergency stop is on or the assistant's agent is paused or revoked (D-UX5). Tasks run in the
   assistant's Área de IA under the permissions the user gave it. Answers are shown as plain text. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText, h, icon } from "../lib/ui.js";

const ai = browser.nulavioAI;
let state = null;
let windowId = null; // the browser window this panel lives in
let current = null; // what "Incluir esta página" would include now: {tabId, url, title}
let chips = []; // the items of the next message, as the browser keeps them: {chipId, kind, tabId, url, title, host, chars, truncated, blockChars}
let busy = false;
let contextVersion = 0; // late page replies cannot restore consent after a send or context change

const $ = id => document.getElementById(id);
const count = n => new Intl.NumberFormat(browser.i18n.getUILanguage()).format(n);
const code = error => String(error?.message ?? error);
const codePoints = text => [...text].length; // as the tools count (Python's len), not UTF-16 units
// The message is each item's block, then "Question: " and the question (assistant.py _content).
const QUESTION_PREFIX = "Question: ";
const MAX_PAGE_CHARS = 60000;

// Refusals that come before anything is sent or done (so "Nada foi alterado" style texts hold).
// The provider's own errors are not here: their texts say whether the request reached it (AI-09).
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
  "recipient-changed",
  "size-changed",
  "bad-question",
  "bad-request",
  "tools-missing",
]);
// Refusals that mean the panel itself should show another state.
const STATE_CHANGED = new Set([
  "emergency-stop",
  "assistant-paused",
  "assistant-revoked",
  "private-window",
  "profile-not-allowed",
  "not-configured",
  "recipient-changed",
]);

const BLOCKED = {
  "emergency-stop": () => [t("assistantStoppedTitle"), t("assistantStoppedText"), "settings/settings.html#ai-agents-card"],
  "assistant-paused": () => [t("assistantPausedTitle"), t("assistantPausedText"), "settings/settings.html#ai-agents-card"],
  "assistant-revoked": () => [t("assistantRevokedTitle"), t("err_assistant_revoked"), "settings/settings.html#ai-assistant"],
};

function mode() {
  return $("ask").elements.mode.value;
}

const pageChip = () => chips.find(c => c.kind === "page") ?? null;

/** The whole request as the tools will count it: Nulavio's instructions, each item, the question. */
function requestChars() {
  const question = codePoints($("prompt").value.trim());
  const items = chips.reduce((sum, c) => sum + c.blockChars, 0);
  return (state?.systemChars ?? 0) + items + (chips.length ? codePoints(QUESTION_PREFIX) : 0) + question;
}

/** Above Send: where the message goes and how big it is, all of it (Q3). In Task mode the size is
    known only afterwards, since what the assistant reads in its Área de IA goes too (AI-14). */
function showSendLine() {
  if (!state?.configured) {
    return;
  }
  $("send-line").textContent =
    mode() === "task"
      ? t("assistantSendLineTask", [state.recipient])
      : t("assistantSendLine", [state.recipient, state.provider.model, count(requestChars())]);
}

function chipItem(chip) {
  return h(
    "li",
    { class: "assistant__chip", "data-chip-id": chip.chipId },
    h(
      "span",
      { class: "assistant__chip-text" },
      h("span", { text: t("assistantAttachedPage") }),
      h("span", { class: "hint", "data-part": "binding", text: t("assistantAttachedBinding", [chip.title, chip.host]) }),
      h("span", {
        class: "hint",
        "data-part": "size",
        text: chip.truncated ? t("assistantPageLong", [count(MAX_PAGE_CHARS)]) : t("assistantPageChars", [count(chip.chars)]),
      })
    ),
    h(
      "button",
      {
        class: "assistant__chip-remove",
        type: "button",
        "aria-label": t("assistantRemovePage", [chip.title]),
        onclick: () => removeChip(chip),
      },
      h("span", { "aria-hidden": "true", text: "×" })
    )
  );
}

/** The included items, the offer to include the current page, and the reason one left. */
function showContext() {
  const task = mode() === "task";
  $("context").hidden = task;
  $("attached").hidden = !chips.length;
  if (chips.length) {
    $("attached-heading").textContent = t("assistantAttachedHeading", [state.recipient]);
  }
  $("chips").replaceChildren(...chips.map(chipItem));
  const offer = !pageChip() && current;
  $("include-page").hidden = !offer;
  if (offer) {
    $("include-page").replaceChildren(h("span", { "aria-hidden": "true", text: "+" }), " ", t("assistantIncludePage", [current.title]));
  }
  $("no-page").hidden = Boolean(pageChip() || current);
  $("summarize").hidden = task || !current;
  showSendLine();
}

/** An item leaves the message, here and in the browser, and the panel says why (`key` names it). */
function drop(chip, key) {
  chips = chips.filter(c => c !== chip);
  ai.assistantRemove(chip.chipId).catch(() => {});
  const text = t(key, [chip.title]);
  $("drift-text").textContent = text;
  $("drift").hidden = false;
  announce(text, "info");
}

function removeChip(chip) {
  ++contextVersion;
  chips = chips.filter(c => c !== chip);
  ai.assistantRemove(chip.chipId).catch(() => {});
  showContext();
  $("include-page").focus();
}

/** "Incluir esta página" and "Resumir": the tab shown now is read and kept for the next message.
    Resolves to true when the page is in the message. */
async function includeCurrent() {
  const version = ++contextVersion;
  const page = await ai.assistantPage().catch(() => null); // what the tab shows at this moment
  if (version !== contextVersion || document.body.dataset.state !== "ready") {
    return false;
  }
  current = page;
  if (!page) {
    showContext();
    return false;
  }
  let chip;
  try {
    chip = await ai.assistantInclude({ kind: "page", tabId: page.tabId, url: page.url });
  } catch (e) {
    announce(errorText(e), "error");
    await refreshPage();
    return false;
  }
  if (version !== contextVersion || document.body.dataset.state !== "ready") {
    ai.assistantRemove(chip.chipId).catch(() => {}); // a Send or a change came first: it is not for that one
    return false;
  }
  chips = [...chips.filter(c => c.kind !== "page"), chip];
  $("drift").hidden = true;
  showContext();
  return true;
}

/** Re-read this window's selected tab. `changedTab`: the tab an update or removal was about. */
async function refreshPage(changedTab = null) {
  const version = ++contextVersion;
  const page = await ai.assistantPage().catch(() => null);
  if (version !== contextVersion) {
    return;
  }
  const attached = pageChip();
  if (attached) {
    const sameTab = page?.tabId === attached.tabId;
    if (!sameTab && changedTab !== attached.tabId) {
      drop(attached, "assistantDriftTab"); // another tab is selected now
    } else if (!sameTab || page.url !== attached.url) {
      drop(attached, "assistantDriftGone"); // that tab went to another address, or closed
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
    chips = await ai.assistantChips().catch(() => []); // kept by the browser while the panel was closed
    await refreshPage();
    syncMode();
  } else {
    ++contextVersion;
    chips = [];
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
  // The provider's limit stopped the answer (AI-08): said where the answer ends, not only announced.
  $("truncated").hidden = !result.truncated;
  $("receipt").textContent = task
    ? t("assistantSentTask", [result.recipient ?? state.recipient])
    : result.pageChars
      ? t("assistantSentPage", [count(result.pageChars), result.recipient, count(result.chars)])
      : t("assistantSentQuestionOnly", [result.recipient, count(result.chars)]);
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
    text = reason.startsWith("provider-") || reason === "workspace-failed"
      ? `${text} ${t("assistantTaskMayHaveActed")}`
      : errorText("task-unfinished");
    $("activity-actions").hidden = false;
  }
  announce(text, "error");
  if (STATE_CHANGED.has(reason)) {
    await render().catch(() => {});
  } else if (reason === "page-changed") {
    await refreshPage();
  }
}

async function send(question) {
  const task = mode() === "task";
  // What the line above Send says now is what the tools check: where it goes, and its size.
  const expected = { recipient: state.recipient, model: state.provider.model };
  const items = task ? [] : chips.map(c => c.chipId);
  const chars = requestChars();
  busy = true;
  ++contextVersion;
  // Consent is per message: what was included goes with this one only (the browser drops it too).
  chips = [];
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
      ? await ai.assistantTask(question, expected)
      : await ai.assistantAsk(question, { chips: items, expected: { ...expected, chars } });
    showResult(result, task);
  } catch (e) {
    await showError(e, task);
  } finally {
    busy = false;
    $("send").disabled = false;
    $("summarize").disabled = false;
    $("include-page").disabled = false;
    showSendLine();
  }
}

$("ask").addEventListener("submit", event => {
  event.preventDefault();
  const question = $("prompt").value.trim();
  if (question && !busy) {
    send(question);
  }
});
$("prompt").addEventListener("input", showSendLine);
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
  await includeCurrent();
  $("prompt").focus(); // the offer button is gone either way; the question comes next
});
// "Resumir" includes this page and writes the request; Send stays the person's (Q5).
$("summarize").addEventListener("click", async () => {
  if (busy) {
    return;
  }
  if (await includeCurrent()) {
    $("prompt").value = t("assistantSummarizePrompt");
    showSendLine();
    $("send").focus();
  }
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
let renderAgain = false;
let lastBlockedCheck = 0;
let blockedTimer = null;
// One check at a time; a request that arrives during a check gets one more check that
// starts after it, so a resume made meanwhile is never answered by an older check.
function renderShared() {
  if (rendering) {
    renderAgain = true;
    return rendering;
  }
  rendering = render().finally(() => {
    rendering = null;
    if (renderAgain) {
      renderAgain = false;
      if (document.body.dataset.state === "blocked") {
        renderShared().catch(() => {});
      }
    }
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
  if (document.body.dataset.state === "ready" && (tabId === pageChip()?.tabId || here)) {
    refreshPage(tabId);
  }
});
browser.tabs.onRemoved.addListener(tabId => {
  if (document.body.dataset.state === "ready" && tabId === pageChip()?.tabId) {
    refreshPage(tabId);
  }
});
window.addEventListener("focus", () => {
  if (document.body.dataset.state === "blocked") {
    recheckBlocked();
  }
});

localize();
$("truncated").prepend(icon("warning", "callout__icon"));
browser.windows
  .getCurrent()
  .then(win => (windowId = win.id))
  .catch(() => {})
  .then(render)
  .catch(e => announce(errorText(e), "error"))
  .finally(() => (document.documentElement.dataset.ready = "true"));
