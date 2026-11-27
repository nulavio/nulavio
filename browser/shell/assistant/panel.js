/* Nulavio Assistant panel (A12). The question goes to the model the user chose; a page's text only
   when the user included that page in this message. Consent is per message and bound to one tab
   (AI-02): "Incluir" reads that tab's text at once and keeps it in the browser (UX5-B, Q4), the item
   shows the tab, its size and whether it was cut, and it leaves the message after every Send, or when
   that tab goes elsewhere or another tab is selected (a Send waits for the panel's check of it, #816).
   The line above Send says where the message goes and its whole size; the tools refuse it if either
   changed. Off in private windows (D-UX6) and while
   the emergency stop is on or the assistant's agent is paused or revoked (D-UX5). Tasks run in the
   assistant's Área de IA under the permissions the user gave it. Answers are shown as plain text. */

import { localize, t } from "../lib/i18n.js";
import { renderMarkdown } from "../lib/markdown.js";
import { announce, errorText, h, icon } from "../lib/ui.js";

const ai = browser.nulavioAI;
let state = null;
let windowId = null; // the browser window this panel lives in
let current = null; // what "Incluir esta página" would include now: {tabId, url, title}
let chips = []; // the items of the next message, as the browser keeps them: {chipId, kind, tabId, url, title, host, address, chars, truncated, blockChars}
let busy = false;
// The run this panel shows (UX5-C2): {runId, kind, text, stopping, steps}. Its events arrive through
// onAssistantEvent; ones that come before assistantStart answers wait in `early`.
let run = null;
let early = [];
let paint = 0;
// This window's conversation, as the browser keeps it (UX5-D, Q16): turns, sizes, no page text.
let thread = null;
let shownAnswer = ""; // the latest answer as the model wrote it (for "Copiar")
const MAX_REQUEST_CHARS = 200000; // assistant.py MAX_REQUEST_CHARS (Q20)
let contextVersion = 0; // late page replies cannot restore consent after a send or context change
// The list's revision (#759): every write of `chips` moves it, and so do every move of `contextVersion`, an entry
// point's delivery that changed the items and the removal of a cancelled Include's item. An item-list reply is drawn only when it did not move while that reply was on its way
// (checkedChips); otherwise the list is read again. So a reply never puts back an item removed, dropped or replaced
// meanwhile, nor writes over one included. A reply with the list and the tab already drawn writes nothing (#813).
let revision = 0;
let sends = 0; // messages started from this panel: a refusal that arrives after one is not about the next
let restoring = Promise.resolve(); // the panel reading and checking the items it opens with (#758)
let drawn = false; // a ready render read the conversation and the items since the panel was last in another state
let tabCheck = null; // the last check of the selected tab (refreshPage) that has not bound the items yet (#816)
let waiting = null; // a Send that waits for that check (#816): `cancel()` ends the wait, and nothing goes
let drops = 0; // items that left the message with a notice (drop): a Send keeps the notice of one its wait dropped

const $ = id => document.getElementById(id);
/** The one way `chips` changes: the revision moves with it. */
function setChips(list) {
  chips = list;
  ++revision;
}
/** Whether `list` holds the items drawn now, in that order (an item's id names its content). */
const sameItems = list => list.length === chips.length && list.every((c, i) => c.chipId === chips[i].chipId);
/** A Send, a mode change, a tab to read again, another state: a reply about the context before it is void. */
function newContext() {
  ++revision;
  return ++contextVersion;
}
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
  "tab-changed",
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
  "assistant-settings-changed",
]);

// The assistant's service is set in the settings page ("Assistente e IA"); the agents and the activity record
// are the Shell's own page.
const SETTINGS = "settings:ai";
const BLOCKED = {
  "emergency-stop": () => [t("assistantStoppedTitle"), t("assistantStoppedText"), "settings/settings.html#ai-agents-card"],
  "assistant-paused": () => [t("assistantPausedTitle"), t("assistantPausedText"), "settings/settings.html#ai-agents-card"],
  "assistant-revoked": () => [t("assistantRevokedTitle"), t("err_assistant_revoked"), SETTINGS],
};

function mode() {
  return $("ask").elements.mode.value;
}

const pageChip = () => chips.find(c => c.kind === "page") ?? null;

/** The whole request as the tools will count it: Nulavio's instructions, each item, the question (the one Send took). */
function requestChars(text = $("prompt").value.trim()) {
  const question = codePoints(text);
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
  const tooMany = !task && (thread?.historyTurns ?? 0) >= (thread?.maxTurns ?? Infinity);
  const tooLarge = !task && (total > MAX_REQUEST_CHARS || tooMany);
  $("too-large").hidden = !tooLarge;
  if (tooLarge) {
    $("too-large-text").textContent = tooMany
      ? t("assistantTooManyTurns", [count(thread.maxTurns)])
      : t("assistantTooLarge", [count(total), count(MAX_REQUEST_CHARS)]);
    $("large-leave").hidden = !thread?.page || thread.pageLeftOut;
  }
  const moved = !task && threadMoved();
  $("thread-moved").hidden = !moved;
  if (moved) {
    $("thread-moved-text").textContent = t("assistantThreadMoved", [thread.recipient, state.recipient]);
    $("moved-carry").textContent = t("assistantCarryThread", [state.recipient]);
  }
  if (!run && !waiting) {
    $("send").disabled = tooLarge || moved; // a Send that waits for a tab check keeps it off (#816)
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
      : withPage && thread.copies > 1
        ? t("assistantThreadLineCopies", [count(n), count(thread.copies)])
        : withPage
          ? t("assistantThreadLinePage", [count(n), thread.page.title])
          : t("assistantThreadLine", [count(n)]);
  $("leave-page").hidden = !thread?.page || thread.pageLeftOut;
  const last = turns.at(-1);
  // A retry goes only to the recipient that turn was for (review UX5-D F1).
  const otherRecipient = Boolean(thread?.retryRecipient && thread.retryRecipient !== state?.recipient);
  $("retry-actions").hidden = run || mode() === "task" || thread?.retryChars == null || threadMoved() || otherRecipient;
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
    turn.page ? h("p", { class: "hint", text: t("assistantTurnPage", [turn.page.title, turn.page.address]) }) : null,
    turn.selection ? h("p", { class: "hint", text: t("assistantTurnSelection", [turn.selection.title, turn.selection.address]) }) : null,
    turnAnswer(turn.state === "done" ? said : "", turn.state === "done" ? "" : said),
    h("p", { class: "hint", text: receipt }),
    turn.state === "done" && turn.answer
      ? h("button", { class: "button button--quiet", type: "button", text: t("assistantCopy"), onclick: () => copy(turn.answer) })
      : null
  );
}

/** An earlier answer, in the same safe Markdown as the latest one; other states as plain text. */
function turnAnswer(markdown, plain) {
  const box = h("div", { class: "assistant__turn-answer" });
  if (markdown) {
    renderMarkdown(box, markdown);
  } else {
    box.textContent = plain;
  }
  return box;
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
  const selection = chip.kind === "selection";
  const size = selection
    ? chip.truncated
      ? t("assistantSelectionMayBeCut", [count(chip.chars)])
      : t("assistantPageChars", [count(chip.chars)])
    : chip.truncated
      ? t("assistantPageLong", [count(MAX_PAGE_CHARS)])
      : t("assistantPageChars", [count(chip.chars)]);
  return h(
    "li",
    { class: "assistant__chip", "data-chip-id": chip.chipId, "data-kind": chip.kind },
    h(
      "span",
      { class: "assistant__chip-text" },
      h("span", { text: t(selection ? "assistantAttachedSelection" : "assistantAttachedPage") }),
      // The address as it goes with the text (#653): origin and path, without its query or fragment.
      h("span", { class: "hint", "data-part": "binding", text: t("assistantAttachedBinding", [chip.title, chip.address]) }),
      chip.frameAddress ? h("span", { class: "hint", "data-part": "frame", text: t("assistantSelectionFrame", [chip.frameAddress]) }) : null,
      h("span", { class: "hint", "data-part": "size", text: size })
    ),
    h(
      "button",
      {
        class: "assistant__chip-remove",
        type: "button",
        "aria-label": t(selection ? "assistantRemoveSelection" : "assistantRemovePage", [chip.title]),
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
  ++drops;
  setChips(chips.filter(c => c !== chip));
  ai.assistantRemove(chip.chipId).catch(() => {});
  const text = t(key, [chip.title]);
  $("drift-text").textContent = text;
  $("drift").hidden = false;
  announce(text, "info");
}

function removeChip(chip) {
  newContext();
  setChips(chips.filter(c => c !== chip));
  ai.assistantRemove(chip.chipId).catch(() => {});
  showContext();
  $("include-page").focus();
}

/** "Incluir esta página" and "Resumir": the tab shown now is read and kept for the next message.
    Resolves to true when the page is in the message. */
async function includeCurrent() {
  const version = newContext();
  const sent = sends;
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
    if (sends !== sent) {
      return false; // a Send came first: the browser dropped the item it was reading (page-changed), not an error
    }
    announce(errorText(e), "error");
    await refreshPage();
    return false;
  }
  if (version !== contextVersion || document.body.dataset.state !== "ready") {
    // A Send or a change came first: it is not for that one. A list read after the browser stored it is read again.
    ++revision;
    ai.assistantRemove(chip.chipId).catch(() => {});
    return false;
  }
  setChips([...chips.filter(c => c.kind !== "page"), chip]); // a list read before the browser stored it is read again
  $("drift").hidden = true;
  showContext();
  return true;
}

/** Every item is bound to the tab it came from (a page, or a selection in it): one that `page`, the selected tab,
    does not hold leaves the message. `changedTab`: the tab an update or removal was about. */
function bindToPage(page, changedTab = null) {
  for (const attached of [...chips]) {
    const sameTab = page?.tabId === attached.tabId;
    if (!sameTab && changedTab !== attached.tabId) {
      drop(attached, "assistantDriftTab"); // another tab is selected now
    } else if (!sameTab || page.url !== attached.url) {
      drop(attached, "assistantDriftGone"); // that tab went to another address, or closed
    }
  }
  current = page;
}

/** Re-read this window's selected tab. `changedTab`: the tab an update or removal was about. Until it comes back it is
    `tabCheck`, which a Send waits for (#816); one that another change made void (an item removed) stays there for that
    Send. */
function refreshPage(changedTab = null) {
  const version = newContext();
  const check = ai
    .assistantPage()
    .catch(() => null)
    .then(page => {
      if (version !== contextVersion) {
        return; // a newer check is `tabCheck` now, or a Send checks again
      }
      if (tabCheck === check) {
        tabCheck = null;
      }
      bindToPage(page, changedTab);
      showContext();
    });
  tabCheck = check;
  return check;
}

/** Send waits for the panel's check of the selected tab on its way, and for a newer one started meanwhile, so it takes
    only the items still bound to the tab selected then (#816). A check that another change made void (an item removed)
    is made again. It ends when the wait is cancelled. */
async function tabChecked() {
  while (tabCheck && waiting && document.body.dataset.state === "ready") {
    const check = tabCheck;
    await check.catch(() => {});
    if (tabCheck === check && waiting) {
      refreshPage(); // void: nothing newer came, so the tab is read again
    }
  }
}

/** The items the browser keeps for this window's next message, checked against the tab selected now before they are
    drawn (#758): the list and that tab are read together, and what the tab does not hold leaves with no await in
    between, so Send carries only items the panel shows and the selected tab holds. When `revision` moved while they
    were on their way (a Send, a tab event, an item included, removed or dropped, an entry point's delivery: #739,
    #759), both are read again, without cancelling what came meanwhile. These reads start no new context, so an
    Include or a tab event's check on its way stays (#773). `fallback`: the list when it cannot be read. False when
    the panel went to another state meanwhile. */
async function checkedChips(fallback) {
  for (;;) {
    const read = revision;
    const [list, page] = await Promise.all([ai.assistantChips().catch(fallback), ai.assistantPage().catch(() => null)]);
    if (document.body.dataset.state !== "ready") {
      return false; // paused, private: no items there
    }
    if (read === revision) {
      // Another list on its way, read before this one was drawn, is read again; a list and a tab as already drawn
      // change nothing, so it is drawn as it is (#813).
      if (!sameItems(list) || page?.tabId !== current?.tabId || page?.url !== current?.url || page?.title !== current?.title) {
        setChips(list);
      }
      bindToPage(page);
      showContext();
      return true;
    }
  }
}

/** The items the browser kept while the panel was closed. */
const restoreChips = () => checkedChips(() => []);

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
  // First contact (audit 2026-11 ASSIST-02/03): a title, and setting it up is the one main action.
  $("setup-title").hidden = view !== "not-configured";
  $("open-settings").textContent = t(view === "not-configured" ? "assistantConfigureButton" : "assistantOpenSettings");
  $("open-settings").classList.toggle("button--primary", view === "not-configured");
  $("open-settings").classList.toggle("button--secondary", view !== "not-configured");
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
    // A render while the composer shows: the line above Send and the items' heading name the recipient Send would use
    // now, before any await (#773). When the panel opens, or after another state, they wait for the reads: until then
    // it knows neither the conversation's size nor the selected tab, so it draws no size and no "no page" hint.
    if (drawn) {
      syncMode();
    }
    // Set before any await: an entry point's delivery meanwhile waits for these items to be checked (takeOffer).
    restoring = (async () => {
      thread = await ai.assistantThread().catch(() => null);
      await restoreChips();
    })();
    await restoring;
    drawn = document.body.dataset.state === "ready";
    syncMode();
    renderThread();
    await takeOffer();
    await adoptTask();
  } else {
    cancelWait(); // a Send that waits sends nothing from another state, even once the composer shows again (#816)
    newContext();
    setChips([]);
    tabCheck = null; // no items to check: when the composer shows again, its own reads check them
    drawn = false;
    // Hidden now. When the composer shows again, nothing from before waits on it for the reads: no item Send would not
    // carry, no offer of a page, no hint, no size.
    $("chips").replaceChildren();
    $("attached").hidden = true;
    $("include-page").hidden = true;
    $("no-page").hidden = true;
    $("send-line").textContent = "";
  }
}

/** Passages the answer quoted word for word from a page that went (UX5-E): the label says where
    from; "Mostrar a aba" only selects that tab while it still shows that address, as it went: origin and path (#653; no scrolling in v1). */
function showSources(list) {
  $("sources").replaceChildren(
    ...(list ?? []).map(source =>
      h(
        "li",
        { class: "assistant__source" },
        h("p", { class: "hint", text: t("assistantSourceLabel", [source.title, URL.parse(source.url)?.host ?? ""]) }),
        source.heading ? h("p", { class: "hint", text: t("assistantSourceHeading", [source.heading]) }) : null,
        h("blockquote", { class: "assistant__source-quote", text: source.quote }),
        h("button", {
          class: "button button--quiet",
          type: "button",
          text: t("assistantSourceShow"),
          onclick: () =>
            ai.assistantShowSource(source.url).then(
              shown => announce(shown ? t("assistantSourceShown", [source.title]) : t("assistantSourceGone", [source.title]), shown ? "ok" : "error"),
              e => announce(errorText(e), "error")
            ),
        })
      )
    )
  );
  $("sources-section").hidden = !list?.length;
}

/** A tool's name in the person's language, never a raw id. */
const toolName = id => browser.i18n.getMessage(`aiTool_${String(id).replace(/[^a-z0-9_]/gi, "_")}`) || String(id);
const STEP_STATES = new Set(["started", "ok", "denied", "error", "cancelled"]);

/** A Task goes on while the panel is closed (Q18): this panel shows it again, with "Parar", and the
    permission request it waits for, if any. An Ask open when the panel closed is being stopped: it is
    not shown as going on. */
async function adoptTask() {
  if (run || document.body.dataset.state !== "ready") {
    return;
  }
  const going = (await ai.assistantRuns().catch(() => [])).find(r => r.kind === "task");
  if (!going || run) {
    return;
  }
  const stopping = going.state === "cancelling";
  cancelWait(); // the composer is the Task's now: a Send that waits sends nothing, even after the Task ends (#816)
  run = { runId: going.runId, kind: "task", text: "", stopping, steps: [...going.steps] };
  setRunning(true);
  $("send").disabled = stopping; // a stop already asked for: it ends by itself
  showSteps(run.steps);
  $("answer-section").hidden = !run.steps.length;
  announce(t(stopping ? "assistantTaskStopping" : "assistantTaskGoesOn"), "progress");
  if (going.pendingApproval) {
    showApproval(going.pendingApproval); // the card it waits for comes back with the panel
  }
}

/** The run's timeline (UX5-F): each step, by its tool's name, and what happened to it. */
function showSteps(steps) {
  $("steps").setAttribute("aria-label", t("assistantStepsLabel"));
  $("steps").replaceChildren(
    ...(steps ?? []).map(step => {
      const state = STEP_STATES.has(step.state) ? step.state : step.error ? "error" : "ok";
      return h("li", { "data-state": state }, h("span", { text: toolName(step.tool) }), " ", h("span", { class: "hint", text: t(`assistantStep_${state}`) }));
    })
  );
  $("steps").hidden = !steps?.length;
}

// -- the permission card (UX5-F, Q9): a request of this panel's run, answered here ------------------
let approval = null; // {id, timer}
const RISKS = new Set(["critical", "warning", "info"]);

function hideApproval() {
  if (approval) {
    clearTimeout(approval.timer);
    clearTimeout(approval.arm);
  }
  approval = null;
  $("approval").hidden = true;
}

let showing = null; // the request a card is being built for; a newer one, or its end, wins
const gone = new Set(); // requests whose step ended or that another place shows

async function showApproval(id) {
  if (approval?.id === id || gone.has(id)) {
    return;
  }
  showing = id;
  const request = await ai.request(id).catch(() => null);
  if (!request || !run || showing !== id || gone.has(id)) {
    return;
  }
  hideApproval();
  approval = { id };
  // An unknown tier is shown as the highest: the card never understates a request.
  const tier = RISKS.has(request.risk) ? request.risk : "critical";
  $("approval").className = `callout callout--${tier} assistant__approval`;
  $("approval-icon").replaceChildren(icon(tier, "callout__icon"));
  $("approval-who").textContent = t("aiRequestFrom", [request.agent, t(`aiLevel_${request.autonomy}`)]);
  $("approval-headline").textContent = t("aiRequestWants", [request.agent, t(`aiCap_${request.capability}`)]);
  $("approval-risk").textContent = t(`aiRisk_${tier}`);
  $("approval-target").textContent = request.target ?? "";
  $("approval-target").hidden = !request.target;
  const place = request.place ?? { kind: "workspace" };
  $("approval-where").textContent =
    place.kind === "profile" ? t("aiRequestWhereProfile", [String(place.profile ?? "")]) : t("aiRequestWhereWorkspace", [request.agent]);
  const expires = new Date(request.expires);
  $("approval-expires").hidden = Number.isNaN(expires.getTime());
  if (!$("approval-expires").hidden) {
    const time = expires.toLocaleTimeString(browser.i18n.getUILanguage(), { hour: "2-digit", minute: "2-digit" });
    $("approval-expires").textContent = t("aiRequestExpires", [time]);
    approval.timer = setTimeout(() => {
      hideApproval();
      announce(t("aiRequestExpired"), "warn");
    }, Math.max(0, expires.getTime() - Date.now()));
  }
  // "Negar" is the first, filled and focused answer; the two that allow wait a moment before they work.
  for (const button of [$("approval-once"), $("approval-session")]) {
    button.disabled = true;
  }
  $("approval-deny").disabled = false;
  approval.arm = setTimeout(() => {
    $("approval-once").disabled = false;
    $("approval-session").disabled = false;
  }, 1000);
  $("approval").hidden = false;
  $("approval-elsewhere").hidden = true;
  $("approval-deny").focus();
  announce(t("aiRequestWants", [request.agent, t(`aiCap_${request.capability}`)]), "warn");
}

async function answerApproval(value) {
  const id = approval?.id;
  if (!id) {
    return;
  }
  for (const button of $("approval").querySelectorAll("button")) {
    button.disabled = true;
  }
  gone.add(id);
  try {
    await ai.answer(id, value);
    announce(t(value === "deny" ? "aiAnsweredDeny" : value === "session" ? "assistantAnsweredTask" : "aiAnsweredOnce"));
  } catch (e) {
    announce(e?.message === "invalid" || e?.message === "expired" ? t("aiRequestExpired") : errorText(e), "warn");
  }
  if (approval?.id === id) {
    hideApproval(); // never a newer card that came while this answer went
  }
}

/** What went with an answered question, all of it (review UX5-D/G F2): the page, the selection, and the
    conversation (with the page copies it carried), never "only the question" when more went. */
function receipt(result) {
  const parts = [
    result.pageChars ? t("assistantPartPage", [count(result.pageChars)]) : null,
    result.selectionChars ? t("assistantPartSelection", [count(result.selectionChars)]) : null,
    result.historyChars ? t(result.historyPage ? "assistantPartConversationPage" : "assistantPartConversation", [count(result.historyChars)]) : null,
  ].filter(Boolean);
  if (!parts.length) {
    return t("assistantSentQuestionOnly", [result.recipient, count(result.chars)]);
  }
  if (parts.length === 1 && result.pageChars) {
    return t("assistantSentPage", [count(result.pageChars), result.recipient, count(result.chars)]);
  }
  return t("assistantSentParts", [result.recipient, count(result.chars), parts.join(", ")]);
}

function showResult(result, task) {
  const halted = task && result.stopped;
  const text = result.answer || (halted ? "" : t("assistantNoAnswer"));
  shownAnswer = result.answer || "";
  if (result.answer) {
    renderMarkdown($("answer"), result.answer); // when it is whole: safe Markdown, nothing that loads (UX5-E)
  } else {
    $("answer").textContent = text;
  }
  $("answer").hidden = !text;
  // The provider's limit stopped the answer (AI-08): said where the answer ends, not only announced.
  $("truncated").hidden = !result.truncated;
  $("continue").hidden = task;
  $("receipt").textContent = task ? t("assistantSentTask", [result.recipient ?? state.recipient]) : receipt(result);
  showSteps(result.steps);
  showSources(task ? [] : result.sources);
  $("answer-section").hidden = false;
  if (halted) {
    const why = result.stopped === "step-limit" ? t("assistantStoppedStepLimit", [count(result.limit ?? 8)]) : errorText(result.stopped);
    $("activity-actions").hidden = false;
    announce(result.steps?.length ? `${why} ${t("assistantTaskMayHaveActed")}` : why, "error");
    if (STATE_CHANGED.has(result.stopped)) {
      render().catch(() => {}); // the provider changed in Settings: the panel names the new one
    }
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
  } else if (reason === "page-changed" || reason === "tab-changed") {
    // The item went with the refusal, and the page offered may be the one left: "Incluir esta página" and "Resumir"
    // come back with the page of the tab selected now, once it is read, never naming one and taking another (#861).
    // Before any await: the run's end turned them on again.
    current = null;
    $("include-page").hidden = true;
    $("summarize").hidden = true;
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

/** What an entry point left for this window (the selection menu, the shortcut): its item is already
    in the browser's context; the panel shows it and puts the person in the question. */
async function takeOffer() {
  if (document.body.dataset.state !== "ready") {
    return;
  }
  const delivery = await ai.assistantTakeOffer().catch(() => null);
  if (!delivery) {
    return;
  }
  if (delivery.draft) {
    // From "@ia" in the address bar: written here, sent only by Send; during a run it waits for its end.
    // Decided before the list is read: a later read must not write it over a question typed since. A Send that waits
    // for a tab check (#816) counts as a run: the question it took stays until it goes.
    if (run || waiting) {
      laterDraft = delivery.draft;
    } else {
      $("prompt").value = delivery.draft;
      showSendLine(); // its size counts the draft while the list is on its way
    }
  }
  await restoring.catch(() => {}); // the items the panel opens with are checked against the selected tab first (#758)
  // Its item too, against the tab selected now: one from a tab the person left while it was read does not go (#773).
  // No new context, so an Include on its way stays; the drift notice of an item dropped stays too.
  if (!(await checkedChips(() => chips))) {
    return;
  }
  const added = chips.find(c => c.chipId === delivery.chipId);
  if (added) {
    announce(t(added.kind === "selection" ? "assistantSelectionAdded" : "assistantPageAdded", [added.title]));
  }
  if (!run) {
    $("prompt").focus();
  }
}

function onRunEvent(event) {
  if (event.type === "offer") {
    // The browser changed the list (an item added, or a selection replaced): a list read before this is read again (#759).
    // The shortcut and "@ia" change no item (`items` false): a list read on its way is drawn as it is.
    if (event.items !== false) {
      ++revision;
      cancelWait(); // a Send that waits did not see this item: it may not take the browser's items with it (#816)
    }
    takeOffer();
    return;
  }
  if (!run && event.type === "approval" && event.place === "panel") {
    adoptTask(); // it came before this panel took the run: take it now, with its card
    return;
  }
  if (!run || event.runId !== run.runId) {
    if (run && !run.runId) {
      early.push(event); // assistantStart has not answered yet
    }
    return;
  }
  if (event.type === "delta") {
    run.text += event.text;
    paint ||= requestAnimationFrame(showPartial);
  } else if (event.type === "step") {
    // The timeline: a step appears when it starts and says what happened when it ends.
    const at = run.steps.findIndex(step => step.index === event.index);
    const step = { index: event.index, tool: event.tool, state: event.state };
    if (at < 0) {
      run.steps.push(step);
    } else {
      run.steps[at] = step;
    }
    if (event.state !== "started") {
      if (approval) {
        gone.add(approval.id);
      }
      if (showing) {
        gone.add(showing);
      }
      hideApproval(); // the call that waited for an answer is over
    }
    showSteps(run.steps);
    $("answer-section").hidden = false;
  } else if (event.type === "approval") {
    if (event.place === "panel") {
      showApproval(event.id);
    } else if (event.place === "tab" || event.place === "elsewhere") {
      gone.add(event.id);
      hideApproval();
      $("approval-elsewhere").textContent = t(event.place === "tab" ? "assistantApprovalInTab" : "assistantApprovalElsewhere");
      $("approval-elsewhere").hidden = false;
      announce($("approval-elsewhere").textContent, "warn");
    }
  } else if (event.type === "done") {
    finishRun(event);
  } else if (event.type === "error") {
    const { kind, text } = run;
    endRun();
    if (kind === "ask" && text) {
      // What came before the error stays, said to be incomplete, without the "still arriving" cursor.
      $("answer-section").hidden = false;
      shownAnswer = text;
      renderMarkdown($("answer"), text);
      $("answer").hidden = false;
      $("interrupted-text").textContent = t("assistantIncomplete");
      $("interrupted").hidden = false;
    }
    showError({ message: event.code }, kind === "task").then(refreshThread).then(applyLaterDraft);
  }
}

let laterDraft = null; // "@ia" text that came during a run: written in once it ends

function applyLaterDraft() {
  if (laterDraft && !run && !waiting) {
    $("prompt").value = laterDraft;
    laterDraft = null;
    showSendLine();
  }
}

function endRun() {
  hideApproval();
  gone.clear();
  showing = null;
  $("approval-elsewhere").hidden = true;
  cancelAnimationFrame(paint);
  paint = 0;
  run = null;
  early = [];
  setRunning(false);
}

async function finishRun(result) {
  const { kind, text, stopping, steps } = run;
  if (steps.length) {
    result = { ...result, steps }; // the timeline as it went, with what happened to each step
  }
  const task = kind === "task";
  if (!result.cancelled && !task) {
    // The question is in the conversation now; after an error or a stop it stays. Emptied before any await: an
    // "@ia" draft written in while the conversation is on its way is the next question, not this one.
    $("prompt").value = "";
  }
  endRun();
  if (!result.cancelled) {
    // Written in as the composer opens, before any await: text typed or delivered since stays on top of it.
    applyLaterDraft();
  }
  // The conversation first, so the panel is whole when it says the answer is ready.
  thread = await ai.assistantThread().catch(() => thread);
  if (!result.cancelled) {
    showResult(result, task);
    renderThread();
    if (stopping) {
      announce(t("assistantArrivedBeforeStop")); // the answer came before the stop reached the tools
    }
    return;
  }
  // Stopped: say what may have left, never "nothing changed" once a request went (UX5-C2).
  $("answer-section").hidden = false;
  shownAnswer = text;
  renderMarkdown($("answer"), text); // what came before the stop, in the same form
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
  applyLaterDraft();
  if (result.cutBy) {
    await render().catch(() => {});
  }
}

/** While a Send waits for the tab check, nothing else changes the message it was pressed for (#816): Send, the question
    and the controls that write it or add an item are off. A run adopted meanwhile (a Task going on) keeps what
    setRunning set. */
function holdComposer(on) {
  $("continue").disabled = on;
  $("retry").disabled = on;
  if (run) {
    return;
  }
  $("include-page").disabled = on;
  $("summarize").disabled = on;
  $("prompt").readOnly = on;
  if (on) {
    $("send").disabled = true;
  } else {
    showSendLine(); // the size of what is left
  }
}

/** A Send that waits for the tab check sends nothing: the person changed the mode or the conversation meanwhile. */
function cancelWait() {
  waiting?.cancel();
}

async function send(question, { retry = false } = {}) {
  if (waiting) {
    return; // a Send that waits for the tab check below: one is enough
  }
  const task = mode() === "task";
  // What the line above Send says now is what the tools check: where it goes, and its size. Taken at the press, so a
  // Send that waits below still goes as an Ask, and to the recipient shown, or is refused (#816).
  const expected = { recipient: state.recipient, model: state.provider.model };
  let dropNotice = false;
  if (tabCheck && !task && !retry) {
    // Another tab was selected, or an included one changed, and the panel's check of the selected tab is on its way:
    // Send waits for it, so an item that tab does not hold leaves first and never goes (#816, AI-02). What it was
    // pressed for is the items shown then: one drawn meanwhile (an entry point's selection) is not among them.
    const pressed = new Set(chips.map(c => c.chipId));
    const dropsBefore = drops;
    let cancelled = false;
    const wait = new Promise(resolve => {
      waiting = {
        cancel() {
          cancelled = true;
          resolve();
        },
      };
    });
    holdComposer(true);
    try {
      await Promise.race([wait, tabChecked().catch(() => {})]);
    } finally {
      waiting = null;
      holdComposer(false);
    }
    if (cancelled || run || document.body.dataset.state !== "ready" || mode() === "task" || chips.some(c => !pressed.has(c.chipId))) {
      // The person changed the mode or the conversation, an item came, or the panel went to another state (a pause)
      // or adopted a Task meanwhile: nothing goes. The question stays in the composer, and a new item stays shown for
      // another press, unless an "@ia" draft came meanwhile: that is written in, as after a refused start.
      applyLaterDraft();
      return;
    }
    dropNotice = drops !== dropsBefore; // the check this Send waited for dropped an item: its notice stays with it
  }
  const items = task || retry ? [] : chips.map(c => c.chipId);
  const chars = retry ? Number($("retry").dataset.chars) : requestChars(question);
  newContext();
  ++sends;
  // Consent is per message: what was included goes with this one only, or with none for a Task or a retry.
  // The browser drops its copy too, whatever the start (#678).
  setChips([]);
  if (!dropNotice) {
    $("drift").hidden = true;
  }
  showContext();
  $("answer-section").hidden = true;
  $("activity-actions").hidden = true;
  $("interrupted").hidden = true;
  $("truncated").hidden = true;
  $("steps").replaceChildren();
  $("steps").hidden = true;
  $("receipt").textContent = ""; // the receipt of the message before never stands under this one
  showSources([]);
  $("answer").replaceChildren();
  $("copy-answer").hidden = true;
  delete document.body.dataset.answered;
  run = { runId: null, kind: task ? "task" : "ask", text: "", stopping: false, steps: [] };
  setRunning(true);
  renderThread(); // the turn that was below joins the list above
  // One polite announcement now, one when it ends (AI-12); no check mark until then.
  const asking = t(task ? "assistantWorking" : "assistantAsking", [expected.recipient]); // where it goes, as at the press
  announce(dropNotice ? `${$("drift-text").textContent} ${asking}` : asking, "progress");
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
    // An "@ia" draft that came while the start was on its way, written in as the composer opens (before any
    // await): what the person types during the error's handling stays.
    applyLaterDraft();
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
  if (question && !busy && !waiting) {
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
    cancelWait(); // a Send that waits was pressed for the mode before: nothing goes (#816)
    // An Include on its way is void either way. A read of the selected tab on its way is made again, not dropped: after
    // a refusal (#861) it is the only one that brings the page offer back.
    if (tabCheck) {
      refreshPage();
    } else {
      newContext();
    }
    syncMode();
  }
});
$("include-page").addEventListener("click", async () => {
  if (busy || waiting) {
    return;
  }
  await includeCurrent();
  $("prompt").focus(); // the offer button is gone either way; the question comes next
});
// "Resumir" includes this page and writes the request; Send stays the person's (Q5).
$("summarize").addEventListener("click", async () => {
  if (busy || waiting) {
    return;
  }
  if (await includeCurrent()) {
    $("prompt").value = t("assistantSummarizePrompt");
    showSendLine();
    $("send").focus();
  }
});
$("approval-deny").addEventListener("click", () => answerApproval("deny"));
$("approval-once").addEventListener("click", () => answerApproval("once"));
$("approval-session").addEventListener("click", () => answerApproval("session"));
$("retry").addEventListener("click", () => {
  if (!run && !waiting) {
    send("", { retry: true });
  }
});
$("copy-answer").addEventListener("click", () => copy(shownAnswer)); // the answer as written, Markdown included
// A Send that waits for the tab check was written for the conversation as it was: a change to it ends the wait (#816).
const newThread = async () => {
  cancelWait();
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
  cancelWait();
  await ai.assistantThreadLeavePage().catch(() => {});
  await refreshThread();
  announce(t("assistantPageLeftOut"));
};
$("leave-page").addEventListener("click", leavePage);
$("large-leave").addEventListener("click", leavePage);
$("moved-carry").addEventListener("click", async () => {
  cancelWait();
  await ai.assistantThreadCarry(state.recipient).catch(() => {});
  await refreshThread();
  announce(t("assistantThreadCarried", [state.recipient]));
});
const openShell = page =>
  page.startsWith("settings:") && browser.nulavioPersonalise?.openSettings
    ? browser.nulavioPersonalise.openSettings(page.slice("settings:".length))
    : browser.tabs.create({ url: browser.runtime.getURL(page.startsWith("settings:") ? "settings/settings.html#ai-assistant" : page) });
$("open-settings").addEventListener("click", () => openShell(SETTINGS));
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
  if (document.body.dataset.state === "ready" && (chips.some(c => c.tabId === tabId) || here)) {
    refreshPage(tabId);
  }
});
browser.tabs.onRemoved.addListener(tabId => {
  if (document.body.dataset.state === "ready" && chips.some(c => c.tabId === tabId)) {
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
// "Continuar" after a cut answer is an ordinary next turn: written for the person, the size shown, Send theirs (Q14).
$("continue").addEventListener("click", () => {
  if (waiting) {
    return; // a Send that waits for a tab check holds the question it took (#816)
  }
  $("prompt").value = t("assistantContinuePrompt");
  showSendLine();
  $("send").focus();
});
// In the side panel its header already names the assistant: the page's own title stays for screen readers only.
browser.tabs
  .getCurrent()
  .then(tab => $("title").classList.toggle("visually-hidden", !tab))
  .catch(() => {});
$("interrupted").prepend(icon("warning", "callout__icon"));
browser.windows
  .getCurrent()
  .then(win => (windowId = win.id))
  .catch(() => {})
  .then(render)
  .catch(e => announce(errorText(e), "error"))
  .finally(() => (document.documentElement.dataset.ready = "true"));
