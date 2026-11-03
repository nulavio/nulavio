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
// The run this panel shows (UX5-C2): {runId, kind, text, stopping, steps}. Its events arrive through
// onAssistantEvent; ones that come before assistantStart answers wait in `early`.
let run = null;
let early = [];
let paint = 0;
// This window's conversation, as the browser keeps it (UX5-D, Q16): turns, sizes, no page text.
let thread = null;
const MAX_REQUEST_CHARS = 200000; // assistant.py MAX_REQUEST_CHARS (Q20)
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
  "thread-recipient",
  "too-large",
  "bad-history",
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
  return (state?.systemChars ?? 0) + (thread?.historyChars ?? 0) + items + (chips.length ? codePoints(QUESTION_PREFIX) : 0) + question;
}

/** The conversation went to another recipient than the one the assistant uses now (Q2). */
const threadMoved = () => Boolean(thread?.historyTurns && thread.recipient && thread.recipient !== state?.recipient);

/** Above Send: where the message goes and how big it is, all of it (Q3). In Task mode the size is
    known only afterwards, since what the assistant reads in its Área de IA goes too (AI-14). */
function showSendLine() {
  if (!state?.configured) {
    return;
  }
  const task = mode() === "task";
  const total = requestChars();
  $("send-line").textContent = task
    ? t("assistantSendLineTask", [state.recipient])
    : t("assistantSendLine", [state.recipient, state.provider.model, count(total)]);
  // Above the limit, Send waits for an explicit choice: never a silent cut (Q20).
  const tooLarge = !task && total > MAX_REQUEST_CHARS;
  $("too-large").hidden = !tooLarge;
  if (tooLarge) {
    $("too-large-text").textContent = t("assistantTooLarge", [count(total), count(MAX_REQUEST_CHARS)]);
    $("large-leave").hidden = !thread?.page || thread.pageLeftOut;
  }
  const moved = !task && threadMoved();
  $("thread-moved").hidden = !moved;
  if (moved) {
    $("thread-moved-text").textContent = t("assistantThreadMoved", [thread.recipient, state.recipient]);
    $("moved-carry").textContent = t("assistantCarryThread", [state.recipient]);
  }
  if (!run) {
    $("send").disabled = tooLarge || moved;
  }
}

/** The earlier turns of this conversation, and the line that says what goes with the next message. */
function renderThread() {
  const turns = thread?.turns ?? [];
  // The latest turn is the answer below while it is shown there; the list has the ones before it.
  const shown = !$("answer-section").hidden && turns.length ? turns.slice(0, -1) : turns;
  $("thread").replaceChildren(...shown.map(turnItem));
  $("thread-section").hidden = !turns.length;
  $("thread-empty").hidden = Boolean(turns.length) || mode() === "task";
  const n = thread?.historyTurns ?? 0;
  const withPage = thread?.page && !thread.pageLeftOut;
  $("thread-line").textContent = !n
    ? t("assistantThreadNone")
    : n === 1
      ? withPage
        ? t("assistantThreadLinePageOne", [thread.page.title])
        : t("assistantThreadLineOne")
      : withPage
        ? t("assistantThreadLinePage", [count(n), thread.page.title])
        : t("assistantThreadLine", [count(n)]);
  $("leave-page").hidden = !thread?.page || thread.pageLeftOut;
  const last = turns.at(-1);
  $("retry-actions").hidden = run || mode() === "task" || thread?.retryChars == null || threadMoved();
  if (!$("retry-actions").hidden) {
    const chars = (state?.systemChars ?? 0) + thread.historyChars + thread.retryChars;
    $("retry-hint").textContent = t("assistantRetryHint", [count(chars), state.recipient]);
    $("retry").dataset.chars = String(chars);
  }
  $("copy-answer").hidden = !(last?.state === "done" && last.answer) || $("answer-section").hidden;
  showSendLine();
}

function turnItem(turn) {
  const said =
    turn.state === "done"
      ? turn.answer
      : turn.state === "cancelled"
        ? [turn.answer, t("assistantInterrupted")].filter(Boolean).join("\n")
        : errorText(turn.code);
  const receipt =
    turn.state === "done"
      ? t("assistantTurnReceipt", [count(turn.chars ?? 0), turn.recipient])
      : turn.sent
        ? t("assistantTurnMayHaveGone")
        : t("assistantTurnNotSent");
  return h(
    "li",
    { class: "assistant__turn", "data-state": turn.state },
    h("p", { class: "assistant__turn-question", text: turn.question }),
    turn.page ? h("p", { class: "hint", text: t("assistantTurnPage", [turn.page.title, turn.page.host]) }) : null,
    h("p", { class: "assistant__turn-answer", text: said }),
    h("p", { class: "hint", text: receipt }),
    turn.state === "done" && turn.answer
      ? h("button", { class: "button button--quiet", type: "button", text: t("assistantCopy"), onclick: () => copy(turn.answer) })
      : null
  );
}

async function refreshThread() {
  thread = await ai.assistantThread().catch(() => null);
  renderThread();
}

/** "Copiar": the answer's text only, on the person's click. */
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    announce(t("assistantCopied"));
  } catch {
    announce(t("assistantCopyFailed"), "error");
  }
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
  if (thread) {
    renderThread();
  }
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
    thread = await ai.assistantThread().catch(() => null);
    await refreshPage();
    syncMode();
    renderThread();
    if (!run) {
      const [going] = await ai.assistantRuns().catch(() => []);
      if (going) {
        // A Task goes on while the panel is closed (Q18): this panel shows it, with "Parar".
        run = { runId: going.runId, kind: going.kind, text: "", stopping: going.state === "cancelling", steps: [...going.steps] };
        setRunning(true);
        showSteps(run.steps);
        $("answer-section").hidden = !run.steps.length;
        announce(t("assistantTaskGoesOn"), "progress");
      }
    }
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

function setRunning(on) {
  busy = on;
  // While a run goes, Send is "Parar" (Esc too); nothing else changes the message.
  $("send").textContent = t(on ? "assistantStop" : "assistantSend");
  $("send").setAttribute("aria-keyshortcuts", on ? "Escape" : "Control+Enter");
  $("send").classList.toggle("button--primary", !on);
  $("send").classList.toggle("button--secondary", on);
  $("send").disabled = false;
  $("summarize").disabled = on;
  $("include-page").disabled = on;
  $("prompt").readOnly = on;
  if (on) {
    $("retry-actions").hidden = true;
  } else {
    showSendLine();
  }
}

/** The answer as it arrives: plain text in one node, painted once per frame, with a still block cursor.
    The region is not live: a screen reader hears the start and the end (AI-12), not every piece. */
function showPartial() {
  paint = 0;
  if (!run) {
    return;
  }
  $("answer-section").hidden = false;
  $("answer").hidden = false;
  $("answer").replaceChildren(document.createTextNode(run.text), h("span", { class: "assistant__cursor", "aria-hidden": "true" }));
}

function onRunEvent(event) {
  if (!run || event.runId !== run.runId) {
    if (run && !run.runId) {
      early.push(event); // assistantStart has not answered yet
    }
    return;
  }
  if (event.type === "delta") {
    run.text += event.text;
    paint ||= requestAnimationFrame(showPartial);
  } else if (event.type === "step" && event.state !== "started") {
    run.steps.push({ tool: event.tool, error: event.state !== "ok" });
    showSteps(run.steps);
    $("answer-section").hidden = false;
  } else if (event.type === "done") {
    finishRun(event);
  } else if (event.type === "error") {
    const kind = run.kind;
    endRun();
    showError({ message: event.code }, kind === "task").then(refreshThread);
  }
}

function endRun() {
  cancelAnimationFrame(paint);
  paint = 0;
  run = null;
  early = [];
  setRunning(false);
}

async function finishRun(result) {
  const { kind, text, stopping } = run;
  const task = kind === "task";
  endRun();
  // The conversation first, so the panel is whole when it says the answer is ready.
  thread = await ai.assistantThread().catch(() => thread);
  if (!result.cancelled) {
    if (!task) {
      $("prompt").value = ""; // the question is in the conversation now; after an error or a stop it stays
    }
    showResult(result, task);
    renderThread();
    if (stopping) {
      announce(t("assistantArrivedBeforeStop")); // the answer came before the stop reached the tools
    }
    return;
  }
  // Stopped: say what may have left, never "nothing changed" once a request went (UX5-C2).
  $("answer-section").hidden = false;
  $("answer").textContent = text;
  $("answer").hidden = !text;
  $("truncated").hidden = true;
  $("interrupted").hidden = task;
  $("interrupted-text").textContent = result.cutBy ? errorText(result.cutBy) : t("assistantInterrupted");
  $("receipt").textContent = "";
  showSteps(result.steps);
  renderThread();
  document.body.dataset.answered = "true";
  let why = !result.sent ? t("assistantCancelledNothing") : task ? t("assistantTaskCancelled") : t("assistantCancelledSent", [state.recipient]);
  if (task && result.sent) {
    why = `${why} ${t("assistantTaskMayHaveActed")}`;
    $("activity-actions").hidden = false;
  }
  announce(result.cutBy ? `${errorText(result.cutBy)} ${why}` : why, "error");
  if (result.cutBy) {
    await render().catch(() => {});
  }
}

async function send(question, { retry = false } = {}) {
  const task = mode() === "task";
  // What the line above Send says now is what the tools check: where it goes, and its size.
  const expected = { recipient: state.recipient, model: state.provider.model };
  const items = task || retry ? [] : chips.map(c => c.chipId);
  const chars = retry ? Number($("retry").dataset.chars) : requestChars();
  ++contextVersion;
  // Consent is per message: what was included goes with this one only (the browser drops it too).
  chips = [];
  $("drift").hidden = true;
  showContext();
  $("answer-section").hidden = true;
  $("activity-actions").hidden = true;
  $("interrupted").hidden = true;
  $("truncated").hidden = true;
  $("steps").hidden = true;
  $("answer").replaceChildren();
  $("copy-answer").hidden = true;
  delete document.body.dataset.answered;
  run = { runId: null, kind: task ? "task" : "ask", text: "", stopping: false, steps: [] };
  setRunning(true);
  renderThread(); // the turn that was below joins the list above
  // One polite announcement now, one when it ends (AI-12); no check mark until then.
  announce(t(task ? "assistantWorking" : "assistantAsking", [state.recipient]), "progress");
  try {
    const { runId } = task
      ? await ai.assistantStart("task", { task: question, expected })
      : retry
        ? await ai.assistantStart("ask", { retry: true, expected: { ...expected, chars } })
        : await ai.assistantStart("ask", { question, chips: items, expected: { ...expected, chars } });
    run.runId = runId;
    if (run.stopping) {
      ai.assistantCancel(runId).catch(() => {}); // "Parar" came before the run had an id
    }
    const waiting = early;
    early = [];
    waiting.forEach(onRunEvent);
  } catch (e) {
    endRun();
    await showError(e, task);
    await refreshThread();
  }
}

/** "Parar": the tools are asked to stop; what they say then (done, cancelled or not) ends the run. */
function stop() {
  if (!run || run.stopping) {
    return;
  }
  run.stopping = true;
  $("send").disabled = true; // until the run ends: one stop is enough
  if (run.runId) {
    ai.assistantCancel(run.runId).catch(() => {});
  }
}

$("ask").addEventListener("submit", event => {
  event.preventDefault();
  if (run) {
    stop();
    return;
  }
  const question = $("prompt").value.trim();
  if (question && !busy) {
    send(question);
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && run && !event.defaultPrevented) {
    event.preventDefault();
    stop();
  }
});
ai.onAssistantEvent.addListener(onRunEvent);
$("prompt").addEventListener("input", showSendLine);
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault();
    if (!run) {
      $("ask").requestSubmit(); // never a stop by the send shortcut
    }
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
$("retry").addEventListener("click", () => {
  if (!run) {
    send("", { retry: true });
  }
});
$("copy-answer").addEventListener("click", () => copy($("answer").textContent));
const newThread = async () => {
  await ai.assistantThreadClear().catch(() => {});
  $("answer-section").hidden = true;
  await refreshThread();
  announce(t("assistantThreadCleared"));
  $("prompt").focus();
};
$("new-thread").addEventListener("click", newThread);
$("moved-new").addEventListener("click", newThread);
$("large-new").addEventListener("click", newThread);
const leavePage = async () => {
  await ai.assistantThreadLeavePage().catch(() => {});
  await refreshThread();
  announce(t("assistantPageLeftOut"));
};
$("leave-page").addEventListener("click", leavePage);
$("large-leave").addEventListener("click", leavePage);
$("moved-carry").addEventListener("click", async () => {
  await ai.assistantThreadCarry(state.recipient).catch(() => {});
  await refreshThread();
  announce(t("assistantThreadCarried", [state.recipient]));
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
$("interrupted").prepend(icon("warning", "callout__icon"));
browser.windows
  .getCurrent()
  .then(win => (windowId = win.id))
  .catch(() => {})
  .then(render)
  .catch(e => announce(errorText(e), "error"))
  .finally(() => (document.documentElement.dataset.ready = "true"));
