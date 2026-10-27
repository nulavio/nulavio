/* Nulavio Assistant panel (A12). The question goes to the model the user chose; the page's text
   only when "include this page" is ticked, and the panel names where it goes. Tasks run in the
   assistant's AI Workspace under the permissions the user gave it. Answers are shown as plain text. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText } from "../lib/ui.js";

const ai = browser.nulavioAI;
let state = null;

const $ = id => document.getElementById(id);

async function showPage() {
  const page = await ai.assistantPage().catch(() => null);
  $("include-page").disabled = !page;
  $("summarize").disabled = !page;
  $("page-label").textContent = page
    ? t("assistantIncludePage", [page.title, state.recipient])
    : t("assistantNoPage");
  if (!page) {
    $("include-page").checked = false;
  }
}

function mode() {
  return $("ask").elements.mode.value;
}

function syncMode() {
  const task = mode() === "task";
  $("page-option").hidden = task;
  $("summarize").hidden = task;
  $("task-note").hidden = !task;
  $("prompt-label").textContent = t(task ? "assistantTaskLabel" : "assistantQuestion");
  const level = state?.agent?.autonomy ?? "restricted";
  $("task-note").textContent = t("assistantTaskNote", [t(`aiLevel_${level.replace("-", "_")}`) || level]);
}

async function render() {
  state = await ai.assistantState();
  const ready = state.configured && state.profileAllowed;
  $("setup").hidden = ready;
  $("ask").hidden = !ready;
  $("allow-profile").hidden = !state.configured || state.profileAllowed;
  $("setup-text").textContent = !state.configured
    ? t("assistantNotConfigured")
    : t("assistantProfileNotAllowed", [state.recipient]);
  if (state.configured) {
    $("footer").textContent = t("assistantFooter", [state.provider.model, state.recipient]);
  }
  document.body.dataset.state = ready ? "ready" : state.configured ? "not-allowed" : "not-configured";
  if (ready) {
    await showPage();
    syncMode();
  }
}

async function send(question, includePage) {
  const answer = $("answer");
  const steps = $("steps");
  answer.hidden = true;
  steps.hidden = true;
  $("send").disabled = true;
  announce(t(mode() === "task" ? "assistantWorking" : "assistantAsking", [state.recipient]));
  try {
    const result = mode() === "task" ? await ai.assistantTask(question) : await ai.assistantAsk(question, includePage);
    answer.textContent = result.answer || t("assistantNoAnswer");
    answer.hidden = false;
    if (result.steps?.length) {
      steps.replaceChildren(
        ...result.steps.map(s => Object.assign(document.createElement("li"), { textContent: `${s.tool}${s.error ? ` — ${t("assistantStepFailed")}` : ""}` }))
      );
      steps.hidden = false;
    }
    announce(result.pageChars ? t("assistantSentPage", [String(result.pageChars), result.recipient]) : "");
    document.body.dataset.answered = "true";
  } catch (e) {
    announce(errorText(e), "error");
  } finally {
    $("send").disabled = false;
  }
}

$("ask").addEventListener("submit", event => {
  event.preventDefault();
  const question = $("prompt").value.trim();
  if (question) {
    send(question, mode() === "ask" && $("include-page").checked);
  }
});
$("ask").addEventListener("change", event => {
  if (event.target.name === "mode") {
    syncMode();
  }
});
$("summarize").addEventListener("click", () => {
  $("include-page").checked = true;
  $("prompt").value = t("assistantSummarizePrompt");
  send($("prompt").value, true);
});
$("open-settings").addEventListener("click", () =>
  browser.tabs.create({ url: browser.runtime.getURL("settings/settings.html#ai-assistant") })
);
$("allow-profile").addEventListener("click", () => ai.assistantAllow(true).then(render, e => announce(errorText(e), "error")));
browser.tabs.onActivated.addListener(() => state && showPage());
browser.tabs.onUpdated.addListener((_id, info) => info.title && state && showPage());

localize();
render()
  .catch(e => announce(errorText(e), "error"))
  .finally(() => (document.documentElement.dataset.ready = "true"));
